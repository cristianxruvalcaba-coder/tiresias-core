from __future__ import annotations

import pytest
from tiresias.tracking.api_pricing import (
    calculate_api_cost,
    list_services,
    get_service_pricing,
)


def test_stripe_default_zero():
    cost = calculate_api_cost("stripe", "/v1/charges")
    assert cost == 0.0


def test_stripe_charges_exact():
    cost = calculate_api_cost("stripe", "/v1/charges")
    assert isinstance(cost, float)


def test_stripe_unknown_path_default():
    cost = calculate_api_cost("stripe", "/v1/unknown_resource")
    assert cost == 0.0


def test_twilio_sms_cost():
    cost = calculate_api_cost("twilio", "/2010-04-01/Accounts/{id}/Messages.json")
    assert cost == pytest.approx(0.0079)


def test_twilio_calls_cost():
    cost = calculate_api_cost("twilio", "/2010-04-01/Accounts/{id}/Calls.json")
    assert cost == pytest.approx(0.013)


def test_twilio_prefix_match():
    # A path that starts with a known prefix should match
    cost = calculate_api_cost("twilio", "/2010-04-01/Accounts/{id}/Messages.json/extra")
    assert cost == pytest.approx(0.0079)


def test_twilio_unknown_path_default():
    cost = calculate_api_cost("twilio", "/2010-04-01/unknown")
    assert cost == 0.0


def test_unknown_service_zero():
    cost = calculate_api_cost("shopify", "/admin/api/orders")
    assert cost == 0.0


def test_none_service_zero():
    cost = calculate_api_cost(None, "/v1/anything")
    assert cost == 0.0


def test_list_services_contains_known():
    services = list_services()
    assert "stripe" in services
    assert "twilio" in services


def test_get_service_pricing_stripe():
    table = get_service_pricing("stripe")
    assert table is not None
    assert "__default__" in table


def test_get_service_pricing_unknown():
    table = get_service_pricing("nonexistent")
    assert table is None


def test_case_insensitive_service():
    cost_lower = calculate_api_cost("stripe", "/v1/charges")
    cost_upper = calculate_api_cost("STRIPE", "/v1/charges")
    assert cost_lower == cost_upper
