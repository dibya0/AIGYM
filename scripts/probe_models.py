"""Which models does this free key actually serve? One tiny request per model (≈10 tokens), counted
in the daily request ledger. A model can be *listed* by /models yet have no free quota (429/403).

    uv run --env-file .env python scripts/probe_models.py gemini/gemini-3.8-flash gemini/gemma-4-31b-it groq/openai/gpt-oss-120b
"""

from __future__ import annotations

import os
import sys
import time

from openai import OpenAI

from paygym.eval.budget import RequestLedger, cap_for
from paygym.eval.providers import resolve


def probe(name: str) -> str:
    spec = resolve(name)
    ledger = RequestLedger(spec.name, cap_for(spec.provider))
    if not ledger.reserve(1):
        return "skipped: daily request budget reached"
    client = OpenAI(api_key=os.environ[spec.api_key_var], base_url=spec.base_url, max_retries=0, timeout=60)
    t = time.time()
    try:
        r = client.chat.completions.create(model=spec.model_id, max_tokens=16, temperature=0,
                                           messages=[{"role": "user", "content": "Reply with the single word OK."}])
        text = (r.choices[0].message.content or "").strip().replace("\n", " ")[:30]
        return f"OK   {time.time() - t:5.1f}s  -> {text!r}"
    except Exception as exc:  # 429 = listed but no free quota; 404 = wrong id
        return f"FAIL {type(exc).__name__}: {str(exc)[:160]}"


if __name__ == "__main__":
    for name in sys.argv[1:]:
        print(f"{name:40s} {probe(name)}")
