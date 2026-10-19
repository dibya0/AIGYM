"""Compatibility shim for verifiers 0.2.1 with non-OpenAI providers.

verifiers 0.2.1 parses every chat response with ``ChatCompletion.model_validate_json``. The OpenAI
SDK types ``service_tier`` as a closed ``Literal["auto", "default", "flex", "scale", "priority", "fast"]``,
but Groq answers ``"on_demand"``, so *every* Groq response failed validation and the rollout was
aborted (found in the Step 12 smoke eval, 2026-10-19). verifiers fixed this in its v1 stack
(``verifiers/v1/dialects/chat.py`` widens the field to ``str``); this applies the same fix to the
pinned v0 path, by blanking an unknown tier before validation. Nothing else in the response is touched,
and the field is informational only (we never read it).

Second fix (tool mode, same day): when replaying earlier assistant turns, verifiers 0.2.1 sends each one
back with a ``reasoning_content`` field (the model's hidden reasoning). Groq rejects that field with a
400 (``property 'reasoning_content' is unsupported``), so every tool rollout failed on its second turn.
We drop the field from outgoing assistant messages for every provider: the model still sees its own
visible replies and tool calls, which is what the OpenAI chat format defines as the conversation. Hidden
reasoning is not part of what we score, and no model we evaluate needs it replayed.

Third fix (tool mode on Gemini, same day): Gemini 3.x returns an opaque ``thought_signature`` with each
function call (OpenAI-compat: ``tool_calls[i].extra_content.google.thought_signature``) and rejects the
next turn with a 400 if it is not sent back. verifiers 0.2.1 converts tool calls into its own type and
drops ``extra_content``. We remember each signature by tool-call id when the response arrives and
re-attach it to that tool call when the conversation is replayed, which is exactly what Google's docs ask
a client to do. Nothing is invented: a call we never saw a signature for is sent as is.

Fourth fix (free-tier pacing, same day): a tool rollout makes ~8 requests back to back inside
verifiers, so a per-rollout rate limit cannot hold a per-minute quota (Gemini Flash-Lite: 15/min). Every
outgoing request is now paced per model at the free tier's RPM (``paygym.eval.budget``), and a 429 whose
body says "retry in Ns" (Gemini puts it in the body, not in a Retry-After header, so the SDK's own short
backoff gives up) is waited out and retried, up to 3 times.
"""

from __future__ import annotations

import asyncio
import json
import re
import time

_KNOWN_TIERS = {"auto", "default", "flex", "scale", "priority", "fast", None}
_applied = False
_SIGNATURES: dict[str, dict] = {}  # tool_call id -> extra_content (bounded below)
_MAX_SIGNATURES = 20_000
_NEXT_SLOT: dict[str, float] = {}  # model -> monotonic time of its next free request slot
_RPM_OVERRIDE: dict[str, int] = {}
_RETRY_IN = re.compile(r"retry in ([0-9.]+)s", re.IGNORECASE)


def set_rpm(model_id: str, rpm: int) -> None:
    """Explicit pacing for a model id (the runner passes its --rpm / free-tier value; 0 = none)."""
    _RPM_OVERRIDE[model_id] = rpm


def _rpm_for(base_url: str, model_id: str) -> int:
    if model_id in _RPM_OVERRIDE:
        return _RPM_OVERRIDE[model_id]
    from paygym.eval.budget import caps_for

    provider = "gemini" if "googleapis" in base_url else "groq" if "groq" in base_url else None
    caps = caps_for(f"{provider}/{model_id}") if provider else None
    return caps.rpm if caps else 0


async def _pace(base_url: str, model_id: str) -> None:
    rpm = _rpm_for(base_url, model_id)
    if not rpm:
        return
    now = time.monotonic()
    slot = max(now, _NEXT_SLOT.get(model_id, 0.0))
    _NEXT_SLOT[model_id] = slot + 60.0 / rpm  # no await between read and write: atomic under asyncio
    if slot > now:
        await asyncio.sleep(slot - now)


def _normalise(raw: bytes) -> bytes:
    if b'"service_tier"' not in raw:
        return raw
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return raw
    if isinstance(data, dict) and data.get("service_tier") not in _KNOWN_TIERS:
        data["service_tier"] = None
        return json.dumps(data).encode()
    return raw


def apply() -> None:
    global _applied
    if _applied:
        return
    from verifiers.utils import client_utils

    original = client_utils.strip_routed_experts_data

    def strip_and_normalise(content, *args, **kwargs):
        stripped, routed = original(content, *args, **kwargs)
        return _normalise(stripped), routed

    client_utils.strip_routed_experts_data = strip_and_normalise

    from verifiers.clients import openai_chat_completions_client as chat_client

    original_post = chat_client.post_chat_completion_with_routed_experts_sidecar

    async def post_without_replayed_reasoning(client, path, *, body, **kwargs):
        body = reattach_signatures(strip_replayed_reasoning(body))
        base_url, model_id = str(getattr(client, "base_url", "")), str(body.get("model", ""))
        for attempt in range(4):
            await _pace(base_url, model_id)
            try:
                response = await original_post(client, path, body=body, **kwargs)
                break
            except Exception as exc:
                delay = _retry_delay(exc)
                if delay is None or attempt == 3:
                    raise
                await asyncio.sleep(delay)
        remember_signatures(response)
        return response

    chat_client.post_chat_completion_with_routed_experts_sidecar = post_without_replayed_reasoning
    _applied = True


def strip_replayed_reasoning(body: dict) -> dict:
    messages = body.get("messages")
    if not isinstance(messages, list) or not any(isinstance(m, dict) and "reasoning_content" in m for m in messages):
        return body
    cleaned = [{k: v for k, v in m.items() if k != "reasoning_content"} if isinstance(m, dict) and m.get("role") == "assistant" else m
               for m in messages]
    return {**body, "messages": cleaned}


def remember_signatures(response) -> None:
    try:
        tool_calls = response.choices[0].message.tool_calls or []
    except (AttributeError, IndexError, TypeError):
        return
    for tc in tool_calls:
        extra = getattr(tc, "extra_content", None) or (getattr(tc, "model_extra", None) or {}).get("extra_content")
        if extra and getattr(tc, "id", None):
            if len(_SIGNATURES) >= _MAX_SIGNATURES:
                _SIGNATURES.pop(next(iter(_SIGNATURES)))
            _SIGNATURES[tc.id] = extra


def reattach_signatures(body: dict) -> dict:
    messages = body.get("messages")
    if not isinstance(messages, list) or not _SIGNATURES:
        return body
    changed, out = False, []
    for m in messages:
        calls = m.get("tool_calls") if isinstance(m, dict) and m.get("role") == "assistant" else None
        if calls and any(isinstance(c, dict) and c.get("id") in _SIGNATURES and "extra_content" not in c for c in calls):
            calls = [{**c, "extra_content": _SIGNATURES[c["id"]]} if isinstance(c, dict) and c.get("id") in _SIGNATURES
                     and "extra_content" not in c else c for c in calls]
            m, changed = {**m, "tool_calls": calls}, True
        out.append(m)
    return {**body, "messages": out} if changed else body


def _retry_delay(exc: Exception) -> float | None:
    """Seconds to wait for a rate-limit error that names its own retry delay; None = not retryable here."""
    text = str(exc)
    if "429" not in text and "RESOURCE_EXHAUSTED" not in text and "rate_limit" not in text:
        return None
    match = _RETRY_IN.search(text)
    return min(90.0, float(match.group(1)) + 1.0) if match else None
