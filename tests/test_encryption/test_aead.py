from __future__ import annotations

import pytest

from tiresias.encryption.aead import decrypt_field, encrypt_field, make_dek


def test_make_dek_returns_32_bytes():
    dek = make_dek()
    assert isinstance(dek, bytes)
    assert len(dek) == 32


def test_make_dek_is_random():
    dek1 = make_dek()
    dek2 = make_dek()
    assert dek1 != dek2


def test_encrypt_field_returns_bytes():
    dek = make_dek()
    ct = encrypt_field("hello", dek)
    assert isinstance(ct, bytes)
    # nonce(12) + ciphertext(5) + tag(16) = 33 bytes minimum
    assert len(ct) >= 33


def test_encrypt_decrypt_roundtrip():
    dek = make_dek()
    plaintext = "The quick brown fox jumps over the lazy dog"
    ct = encrypt_field(plaintext, dek)
    assert decrypt_field(ct, dek) == plaintext


def test_encrypt_field_random_nonce():
    dek = make_dek()
    ct1 = encrypt_field("hello", dek)
    ct2 = encrypt_field("hello", dek)
    # Different nonces produce different ciphertexts
    assert ct1 != ct2


def test_plaintext_not_in_ciphertext():
    dek = make_dek()
    plaintext = "super secret message"
    ct = encrypt_field(plaintext, dek)
    assert plaintext.encode() not in ct
    assert b"super" not in ct


def test_decrypt_with_wrong_dek_raises():
    dek1 = make_dek()
    dek2 = make_dek()
    ct = encrypt_field("hello", dek1)
    with pytest.raises(Exception):
        decrypt_field(ct, dek2)


def test_encrypt_empty_string():
    dek = make_dek()
    ct = encrypt_field("", dek)
    assert decrypt_field(ct, dek) == ""


def test_encrypt_unicode():
    dek = make_dek()
    plaintext = "Hello 世界 🌍"
    ct = encrypt_field(plaintext, dek)
    assert decrypt_field(ct, dek) == plaintext
