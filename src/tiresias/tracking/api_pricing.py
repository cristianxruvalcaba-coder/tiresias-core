from __future__ import annotations

# API Pricing for usage-based REST APIs (Phase 5 — APIP-05)
# Costs are per-request unless otherwise noted.

# Stripe pricing: per API call (approximate — Stripe doesn't charge per API call by default,
# but for cost attribution in high-volume environments we track estimated compute cost).
# These values represent a reasonable operational cost estimate per endpoint type.
STRIPE_PRICING: dict[str, float] = {
    # Pattern -> cost_usd per request
    "/v1/charges": 0.0,
    "/v1/payment_intents": 0.0,
    "/v1/customers": 0.0,
    "/v1/subscriptions": 0.0,
    "/v1/refunds": 0.0,
    "/v1/invoices": 0.0,
    "/v1/products": 0.0,
    "/v1/prices": 0.0,
    "/v1/events": 0.0,
    # Default — Stripe API calls are free; cost is $0 per request
    "__default__": 0.0,
}

# Twilio pricing: per outbound SMS $0.0079, per inbound SMS $0.0075
# Per outbound voice minute $0.013, per inbound voice minute $0.0085
TWILIO_PRICING: dict[str, float] = {
    "/2010-04-01/Accounts/{id}/Messages": 0.0079,          # outbound SMS
    "/2010-04-01/Accounts/{id}/Messages.json": 0.0079,
    "/2010-04-01/Accounts/{id}/Calls": 0.013,              # outbound call per minute
    "/2010-04-01/Accounts/{id}/Calls.json": 0.013,
    "/2010-04-01/Accounts/{id}/IncomingPhoneNumbers": 0.0,
    "__default__": 0.0,
}

# Generic service registry: service_name -> pricing table
_SERVICE_TABLES: dict[str, dict[str, float]] = {
    "stripe": STRIPE_PRICING,
    "twilio": TWILIO_PRICING,
}


def calculate_api_cost(api_service: str | None, path_pattern: str) -> float:
    """
    Return estimated USD cost for a single API call.

    Args:
        api_service: Service identifier (e.g. "stripe", "twilio"). None = unknown.
        path_pattern: Normalized path pattern (with {id} placeholders).

    Returns:
        Cost in USD (float). Returns 0.0 if service/path not in pricing tables.
    """
    if not api_service:
        return 0.0

    table = _SERVICE_TABLES.get(api_service.lower())
    if table is None:
        return 0.0

    # Exact match first
    if path_pattern in table:
        return table[path_pattern]

    # Prefix match — find longest matching prefix
    best_match: str | None = None
    for key in table:
        if key == "__default__":
            continue
        if path_pattern.startswith(key):
            if best_match is None or len(key) > len(best_match):
                best_match = key

    if best_match is not None:
        return table[best_match]

    return table.get("__default__", 0.0)


def list_services() -> list[str]:
    """Return list of known API service names."""
    return list(_SERVICE_TABLES.keys())


def get_service_pricing(api_service: str) -> dict[str, float] | None:
    """Return full pricing table for a service, or None if unknown."""
    return _SERVICE_TABLES.get(api_service.lower())

