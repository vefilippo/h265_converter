from __future__ import annotations

import base64
import io
import json
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone

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


APP_ID = "h265-transcoder"
SCHEMA_VERSION = 1


def build_manifest(app_version: str, crypto: dict, created_at: str) -> dict:
    return {
        "app": APP_ID,
        "schema_version": SCHEMA_VERSION,
        "app_version": app_version,
        "created_at": created_at,
        "crypto": crypto,
    }


def validate_manifest(m: dict) -> None:
    if m.get("app") != APP_ID:
        raise ValueError("not an H.265 Transcoder backup")
    if int(m.get("schema_version", 0)) > SCHEMA_VERSION:
        raise ValueError("backup is from a newer version of the app")


def db_path_from_url(url: str) -> str:
    # sqlite:///rel.db -> rel.db ; sqlite:////abs/x.db -> /abs/x.db
    return url.replace("sqlite:///", "", 1)


def snapshot_db(db_path: str, dest_path: str) -> None:
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        src.close(); dst.close()


def make_backup(db_path: str, env_path: str, passphrase: str,
                app_version: str = "1.0.0", created_at: str | None = None) -> bytes:
    created_at = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with tempfile.TemporaryDirectory() as td:
        snap = f"{td}/snap.db"
        snapshot_db(db_path, snap)
        with open(snap, "rb") as fh:
            db_bytes = fh.read()
    try:
        env_text = open(env_path, encoding="utf-8").read()
    except FileNotFoundError:
        env_text = ""
    ct, crypto = encrypt_env(env_text, passphrase)
    manifest = build_manifest(app_version, crypto, created_at)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("transcoder.db", db_bytes)
        z.writestr("env.enc", ct)
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def read_backup(zip_bytes: bytes, passphrase: str) -> tuple[bytes, str, dict]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        manifest = json.loads(z.read("manifest.json"))
        validate_manifest(manifest)
        db_bytes = z.read("transcoder.db")
        ct = z.read("env.enc")
    env_text = decrypt_env(ct, passphrase, manifest["crypto"])
    return db_bytes, env_text, manifest
