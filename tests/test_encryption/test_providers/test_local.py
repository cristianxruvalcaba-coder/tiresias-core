from __future__ import annotations

import base64
import os

import pytest

from tiresias.encryption.aead import make_dek
from tiresias.encryption.providers.local import LocalKEKProvider


def test_provider_name():
    provider = LocalKEKProvider(os.urandom(32))
    assert provider.provider_name == "local"


async def test_wrap_unwrap_roundtrip():
    provider = LocalKEKProvider(os.urandom(32))
    dek = make_dek()
    wrapped = await provider.wrap_dek(dek)
    assert isinstance(wrapped, bytes)
    assert wrapped != dek
    unwrapped = await provider.unwrap_dek(wrapped)
    assert unwrapped == dek


async def test_wrap_is_nondeterministic():
    provider = LocalKEKProvider(os.urandom(32))
    dek = make_dek()
    w1 = await provider.wrap_dek(dek)
    w2 = await provider.wrap_dek(dek)
    assert w1 != w2  # random nonce each time


async def test_from_api_key_wrap_unwrap():
    provider = LocalKEKProvider.from_api_key("test-api-key-abc123")
    dek = make_dek()
    wrapped = await provider.wrap_dek(dek)
    unwrapped = await provider.unwrap_dek(wrapped)
    assert unwrapped == dek


async def test_from_api_key_same_key_same_kek():
    p1 = LocalKEKProvider.from_api_key("same-key")
    p2 = LocalKEKProvider.from_api_key("same-key")
    assert p1._kek == p2._kek


async def test_from_api_key_different_keys_different_kek():
    p1 = LocalKEKProvider.from_api_key("key-one")
    p2 = LocalKEKProvider.from_api_key("key-two")
    assert p1._kek != p2._kek


def test_from_explicit_value_hex():
    kek_bytes = os.urandom(32)
    kek_hex = kek_bytes.hex()
    provider = LocalKEKProvider.from_explicit_value(kek_hex)
    assert provider._kek == kek_bytes


def test_from_explicit_value_base64():
    kek_bytes = os.urandom(32)
    kek_b64 = base64.b64encode(kek_bytes).decode()
    provider = LocalKEKProvider.from_explicit_value(kek_b64)
    assert provider._kek == kek_bytes


def test_from_explicit_value_invalid_raises():
    with pytest.raises(ValueError):
        LocalKEKProvider.from_explicit_value("not-valid-key-material")


def test_init_wrong_key_length_raises():
    with pytest.raises(ValueError):
        LocalKEKProvider(b"too-short")
