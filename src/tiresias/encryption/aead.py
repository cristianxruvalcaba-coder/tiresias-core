from __future__ import annotations

import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

NONCE_SIZE = 12  # 96 bits — standard for AES-GCM


def make_dek() -> bytes:
    """Generate a fresh 256-bit Data Encryption Key."""
    return os.urandom(32)


def encrypt_field(plaintext: str, dek: bytes) -> bytes:
    """Encrypt a plaintext string with AES-256-GCM.

    Returns nonce (12 bytes) || ciphertext+tag.
    Never logs the DEK.
    """
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(dek)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt_field(blob: bytes, dek: bytes) -> str:
    """Decrypt a blob produced by encrypt_field.

    Splits off the 12-byte nonce prefix, decrypts, returns plaintext string.
    Never logs the DEK.
    """
    nonce = blob[:NONCE_SIZE]
    ciphertext = blob[NONCE_SIZE:]
    aesgcm = AESGCM(dek)
    plaintext_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext_bytes.decode("utf-8")

