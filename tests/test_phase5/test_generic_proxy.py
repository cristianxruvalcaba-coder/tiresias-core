from __future__ import annotations

import pytest
from tiresias.proxy.generic import normalize_path


def test_normalize_uuid():
    path = "/v1/customers/a1b2c3d4-e5f6-7890-abcd-ef1234567890/subscriptions"
    result = normalize_path(path)
    assert result == "/v1/customers/{id}/subscriptions"


def test_normalize_numeric_id():
    path = "/api/orders/12345/items"
    result = normalize_path(path)
    assert result == "/api/orders/{id}/items"


def test_normalize_stripe_id():
    # Stripe charge ID: ch_ + alphanumeric (>= 8 chars)
    path = "/v1/charges/ch_1AbCdEfGhIjKlMnO"
    result = normalize_path(path)
    assert result == "/v1/charges/{id}"


def test_normalize_stripe_customer_id():
    path = "/v1/customers/cus_abc123def456/subscriptions"
    result = normalize_path(path)
    assert result == "/v1/customers/{id}/subscriptions"


def test_normalize_twilio_account():
    path = "/2010-04-01/Accounts/AC1234567890abcdef1234567890abcdef/Messages"
    result = normalize_path(path)
    assert result == "/2010-04-01/Accounts/{id}/Messages"


def test_normalize_no_ids():
    path = "/v1/charges"
    result = normalize_path(path)
    assert result == "/v1/charges"


def test_normalize_multiple_ids():
    # cus_xxx and sub_xxx both have prefix_ + 12 alphanumeric chars
    path = "/v1/customers/cus_abcdef123456/subscriptions/sub_xyz789ghi012/items"
    result = normalize_path(path)
    assert "{id}" in result
    assert "cus_abcdef123456" not in result
    assert "sub_xyz789ghi012" not in result


def test_normalize_empty_path():
    result = normalize_path("/")
    assert result == "/"


def test_normalize_preserves_query_free():
    path = "/v1/events"
    result = normalize_path(path)
    assert result == "/v1/events"


def test_normalize_idempotent():
    path = "/v1/customers/{id}/subscriptions"
    result = normalize_path(path)
    assert result == path


def test_normalize_short_segment_not_replaced():
    # Short segments like "v1", "api", "charges" should NOT be replaced
    path = "/v1/charges"
    result = normalize_path(path)
    assert "v1" in result
    assert "charges" in result


def test_normalize_word_only_not_replaced():
    # Plain words should stay
    path = "/api/users/profile"
    result = normalize_path(path)
    assert result == "/api/users/profile"
