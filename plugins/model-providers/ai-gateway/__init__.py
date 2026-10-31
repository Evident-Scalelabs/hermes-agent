"""Vercel AI Gateway provider profile: attribution headers, reasoning passthrough, reported cost."""

from decimal import Decimal, InvalidOperation
from typing import Any

from providers import register_provider
from providers.base import ProviderProfile


class VercelAIGatewayProfile(ProviderProfile):
    """Vercel AI Gateway — attribution headers + reasoning passthrough."""

    def build_api_kwargs_extras(
        self, *, reasoning_config: dict | None = None, supports_reasoning: bool = True, **ctx: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not supports_reasoning:
            return {}, {}
        reasoning = dict(reasoning_config) if reasoning_config is not None else {"enabled": True, "effort": "medium"}
        return {"reasoning": reasoning}, {}

    def get_usage_cost(self, model: str, usage: Any) -> Any | None:
        """The Gateway reports the USD it debited as `usage.cost`, streamed or not."""
        from agent.usage_pricing import CostResult, format_cost_label

        raw = getattr(usage, "raw_usage", None)
        try:
            amount = Decimal(str(raw.get("cost") if isinstance(raw, dict) else None))
        except InvalidOperation:
            return None
        if not amount.is_finite() or amount < 0:
            return None
        return CostResult(amount_usd=amount, status="actual", source="provider_cost_api", label=format_cost_label(amount))


vercel = VercelAIGatewayProfile(
    name="ai-gateway", aliases=("vercel", "vercel-ai-gateway", "ai_gateway", "aigateway"),
    env_vars=("AI_GATEWAY_API_KEY",), base_url="https://ai-gateway.vercel.sh/v1",
    default_headers={"HTTP-Referer": "https://hermes-agent.nousresearch.com", "X-Title": "Hermes Agent"},
    default_aux_model="google/gemini-3-flash",
)

register_provider(vercel)
