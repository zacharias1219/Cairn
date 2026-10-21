"""One model gateway interface (F2, principle 6).

Every model call in Cairn goes through ``ModelGateway.run``. Which model
runs a step is configuration (``config["models"][step]``), so changing it
needs no code change. Each call asks for structured JSON that is validated
against the step's schema before anyone trusts it.

Two providers sit behind the interface:

* **Claude**, through the official Anthropic SDK, used when an API key is
  configured.
* **Sandbox**, a deterministic stand-in that implements each step in plain
  code. It powers demos, tests and the CI evaluation suite without network
  access, and makes seeded failures reproducible. Its costs are estimates
  priced as if the configured Claude model had run.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import jsonschema

from cairn.config import get_settings

# USD per million tokens (input, output).
PRICING: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Models that accept server-side refusal fallbacks ("fallbacks": "default").
SERVER_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5"}

DEFAULT_MODELS: dict[str, dict[str, str]] = {
    "triage": {"primary": "claude-haiku-5-5", "fallback": "claude-sonnet-5-5", "effort": "low"},
    "plan": {"primary": "claude-opus-5-5", "fallback": "claude-sonnet-5-5", "effort": "medium"},
    "draft": {"primary": "claude-opus-5-5", "fallback": "claude-sonnet-5-5", "effort": "medium"},
    "supervisor": {"primary": "claude-haiku-5-5", "fallback": "claude-sonnet-5-5", "effort": "low"},
    "summarize": {"primary": "claude-haiku-5-5", "fallback": "claude-sonnet-5-5", "effort": "low"},
}


class ModelRefused(RuntimeError):
    """The model declined; the next model in the chain is tried."""


class ModelUnavailable(RuntimeError):
    """Every configured model for a step failed. Callers fail closed."""


@dataclass
class ModelCall:
    step: str
    system: str
    prompt: str
    schema: dict
    sandbox: Callable[[], dict | Awaitable[dict]]
    max_tokens: int = 4096
    timeout_s: float = 30.0


@dataclass
class ModelResult:
    data: dict
    model: str
    provider: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    estimated: bool = False
    fallback_used: bool = False
    attempts: list[dict] = field(default_factory=list)


def price(model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = PRICING.get(model, (4.0, 20.0))
    return round((input_tokens * pin + output_tokens * pout) / 1_000_000, 6)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class ModelGateway:
    def __init__(self, models: dict[str, Any] | None = None, *, use_claude: bool | None = None):
        merged = {k: dict(v) for k, v in DEFAULT_MODELS.items()}
        for step, spec in (models or {}).items():
            if isinstance(spec, str):
                merged.setdefault(step, {})["primary"] = spec
            elif isinstance(spec, dict):
                merged.setdefault(step, {}).update(spec)
        self.models = merged
        self.use_claude = get_settings().use_claude if use_claude is None else use_claude
        self._client = None

    def spec(self, step: str) -> dict[str, str]:
        return self.models.get(step) or DEFAULT_MODELS["draft"]

    def label(self, step: str) -> str:
        m = self.spec(step)["primary"]
        return m if self.use_claude else f"sandbox · {m}"

    # ------------------------------------------------------------- run

    async def run(self, call: ModelCall) -> ModelResult:
        if not self.use_claude:
            return await self._run_sandbox(call)
        spec = self.spec(call.step)
        chain = [spec["primary"]] + ([spec["fallback"]] if spec.get("fallback") else [])
        attempts: list[dict] = []
        for i, model in enumerate(chain):
            try:
                res = await self._run_claude(call, model, spec.get("effort", "medium"))
                res.fallback_used = i > 0 or res.fallback_used
                res.attempts = attempts
                return res
            except Exception as e:  # noqa: BLE001 - recorded and handled by the fallback chain
                attempts.append({"model": model, "error": f"{type(e).__name__}: {e}"[:300]})
        raise ModelUnavailable(f"all models failed for step {call.step}: {attempts}")

    async def _run_sandbox(self, call: ModelCall) -> ModelResult:
        t0 = time.perf_counter()
        out = call.sandbox()
        if asyncio.iscoroutine(out):
            out = await out
        jsonschema.validate(out, call.schema)
        model = self.spec(call.step)["primary"]
        tin = _estimate_tokens(call.system) + _estimate_tokens(call.prompt)
        tout = _estimate_tokens(json.dumps(out))
        return ModelResult(
            data=out, model=f"sandbox · {model}", provider="sandbox",
            latency_ms=int((time.perf_counter() - t0) * 1000),
            input_tokens=tin, output_tokens=tout, cost_usd=price(model, tin, tout), estimated=True,
        )

    def _anthropic(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(max_retries=2)
        return self._client

    async def _run_claude(self, call: ModelCall, model: str, effort: str) -> ModelResult:
        client = self._anthropic().with_options(timeout=call.timeout_s)
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=call.max_tokens,
            system=[{"type": "text", "text": call.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": call.prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": call.schema}},
        )
        t0 = time.perf_counter()
        if model in SERVER_FALLBACK_MODELS:
            resp = await client.beta.messages.create(
                **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
            )
        else:
            resp = await client.messages.create(**kwargs)
        latency = int((time.perf_counter() - t0) * 1000)

        if resp.stop_reason == "refusal":
            raise ModelRefused(getattr(getattr(resp, "stop_details", None), "category", None) or "refusal")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError("model output truncated at max_tokens")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        data = json.loads(text)
        jsonschema.validate(data, call.schema)
        served = getattr(resp, "model", model) or model
        u = resp.usage
        tin = (u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0) + (
            getattr(u, "cache_creation_input_tokens", 0) or 0)
        return ModelResult(
            data=data, model=served, provider="anthropic", latency_ms=latency,
            input_tokens=tin, output_tokens=u.output_tokens or 0,
            cost_usd=price(served, tin, u.output_tokens or 0),
            fallback_used=served != model,
        )
