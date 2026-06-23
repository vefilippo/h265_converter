from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


def derive_key(passphrase: str, salt: bytes, n: int = 2 ** 14, r: int = 8, p: int = 1) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase.encode())


def encrypt_env(env_text: str, passphrase: str) -> tuple[bytes, dict]:
    salt, nonce = os.urandom(16), os.urandom(12)
    n, r, p = 2 ** 14, 8, 1
    key = derive_key(passphrase, salt, n, r, p)
    ct = AESGCM(key).encrypt(nonce, env_text.encode(), None)
    crypto = {
        "cipher": "AES-256-GCM", "kdf": "scrypt", "n": n, "r": r, "p": p,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
    }
    return ct, crypto


def decrypt_env(ciphertext: bytes, passphrase: str, crypto: dict) -> str:
    salt = base64.b64decode(crypto["salt"])
    nonce = base64.b64decode(crypto["nonce"])
    key = derive_key(passphrase, salt, crypto["n"], crypto["r"], crypto["p"])
    return AESGCM(key).decrypt(nonce, ciphertext, None).decode()
