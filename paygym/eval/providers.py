"""Model providers, routed by prefix (Harvey LAB pattern). Any OpenAI-compatible endpoint works
(brief p.8); the model is always a CLI flag, never a constant.

  groq/<model>      Groq free tier           GROQ_API_KEY
  gemini/<model>    Google AI Studio (free)  GEMINI_API_KEY   (OpenAI-compatible endpoint)
  local/<model>     local vLLM server        none             (docker compose --profile gpu up llm)
  baseline/<name>   no model: an adversarial baseline from paygym.baselines
  any other         pass --base-url and --api-key-var explicitly

Prices are *list* prices in USD per million tokens, used for the --max-cost guardrail and to report
what a paid run would have cost. All runs in this project use free tiers or local models, so the
actual spend is $0 and is reported as such. List prices are estimates: verify against the
provider's pricing page before relying on them.
"""

from __future__ import annotations

from dataclasses import dataclass

PROVIDERS = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "api_key_var": "GROQ_API_KEY", "free": True, "rpm": 25},
    "gemini": {"base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "api_key_var": "GEMINI_API_KEY",
               "free": True, "rpm": 8},
    "local": {"base_url": "http://localhost:8000/v1", "api_key_var": "LOCAL_API_KEY", "free": True, "rpm": 0},
}

# (input, output) USD per million tokens, list-price estimates for the cost guardrail.
LIST_PRICES: dict[str, tuple[float, float]] = {
    "groq/openai/gpt-oss-120b": (0.15, 0.75),
    "groq/openai/gpt-oss-20b": (0.10, 0.50),
    "groq/llama-3.1-8b-instant": (0.05, 0.08),
    "gemini/": (0.30, 2.50),  # Flash-class default
    "local/": (0.0, 0.0),
}
DEFAULT_PRICE = (1.0, 4.0)  # deliberately high for unknown models, so the guardrail errs safe


@dataclass(frozen=True)
class ModelSpec:
    name: str  # as given on the CLI, e.g. "groq/openai/gpt-oss-120b"
    provider: str
    model_id: str  # what the endpoint expects, e.g. "openai/gpt-oss-120b"
    base_url: str | None
    api_key_var: str | None
    free_tier: bool
    rpm: int
    price: tuple[float, float]

    @property
    def is_baseline(self) -> bool:
        return self.provider == "baseline"

    def cost_usd(self, input_tokens: float, output_tokens: float) -> float:
        return (input_tokens * self.price[0] + output_tokens * self.price[1]) / 1e6

    @property
    def slug(self) -> str:
        return self.name.replace("/", "__")


def resolve(name: str, base_url: str | None = None, api_key_var: str | None = None, rpm: int | None = None,
            paid: bool = False) -> ModelSpec:
    provider, _, rest = name.partition("/")
    if provider == "baseline":
        return ModelSpec(name, "baseline", rest, None, None, True, 0, (0.0, 0.0))
    if provider in PROVIDERS and rest:
        cfg = PROVIDERS[provider]
        model_id = rest
        url, key, free, default_rpm = cfg["base_url"], cfg["api_key_var"], cfg["free"], cfg["rpm"]
    else:
        if not base_url:
            raise ValueError(f"unknown provider for {name!r}: use groq/, gemini/, local/, baseline/ or pass --base-url")
        model_id, url, key, free, default_rpm = name, None, api_key_var or "OPENAI_API_KEY", False, 0
    price = next((p for prefix, p in LIST_PRICES.items() if name == prefix or (prefix.endswith("/") and name.startswith(prefix))),
                 DEFAULT_PRICE)
    return ModelSpec(name, provider if provider in PROVIDERS else "custom", model_id, base_url or url,
                     api_key_var or key, free and not paid, rpm if rpm is not None else default_rpm, price)
