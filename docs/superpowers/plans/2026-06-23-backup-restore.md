# Backup & Restore Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add web-UI **Download backup** and turnkey **Restore from backup** so a running instance can be cloned onto a new one.

**Architecture:** A `backup.zip` holds a consistent SQLite snapshot, an AES-256-GCM-encrypted `.env`, and a `manifest.json`. Backup streams from `POST /api/backup`. Restore (`POST /api/restore`) validates + decrypts, stages the files + a marker, and the app relaunches itself; a startup bootstrap applies the staged files **before the DB opens**. Restore is wholesale replace, not merge.

**Tech Stack:** FastAPI, SQLAlchemy/sqlite3, `cryptography` (AESGCM + scrypt, already present via paramiko), React + TanStack Query + Vitest.

## Global Constraints

- Backend runs from `solution/` as cwd; `transcoder.db` and `.env` are cwd-relative. Tests run from the repo root: `python -m pytest` (pytest.ini sets `pythonpath = solution`).
- Frontend suite runs `tsc -b` first: `cd solution/web && npm test`. ES2020 target — no `Array.prototype.at`.
- All API endpoints except `/api/health` and `/api/webhook/*` require auth (`Depends(require_auth)`).
- No new pip dependency: use `cryptography` (confirmed v49.0.0). No new npm dependency.
- Crypto: AES-256-GCM; key = scrypt(passphrase, salt, n=2**14, r=8, p=1, dklen=32). `salt` (16B) + `nonce` (12B) random per backup, stored base64 in `manifest.json["crypto"]`.
- Backup app id = `"h265-transcoder"`, `schema_version = 1`. Refuse restore if `app` mismatches or `schema_version` > current.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: Crypto helpers (`backup.py`)

**Files:**
- Create: `solution/transcoder/backup.py`
- Test: `tests/test_backup_crypto.py`

**Interfaces:**
- Produces:
  - `derive_key(passphrase: str, salt: bytes, n: int = 2**14, r: int = 8, p: int = 1) -> bytes` (32 bytes)
  - `encrypt_env(env_text: str, passphrase: str) -> tuple[bytes, dict]` — returns `(ciphertext, crypto_params)` where `crypto_params = {"cipher": "AES-256-GCM", "kdf": "scrypt", "n", "r", "p", "salt": <b64>, "nonce": <b64>}`
  - `decrypt_env(ciphertext: bytes, passphrase: str, crypto: dict) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backup_crypto.py
import pytest
from cryptography.exceptions import InvalidTag
from transcoder import backup


def test_encrypt_decrypt_roundtrip():
    text = "SONARR_URL=http://x\nAPP_PASSWORD=secret\n"
    ct, crypto = backup.encrypt_env(text, "hunter2")
    assert ct != text.encode()
    assert crypto["cipher"] == "AES-256-GCM" and crypto["kdf"] == "scrypt"
    assert backup.decrypt_env(ct, "hunter2", crypto) == text


def test_wrong_passphrase_raises():
    ct, crypto = backup.encrypt_env("X=1\n", "right")
    with pytest.raises(InvalidTag):
        backup.decrypt_env(ct, "wrong", crypto)


def test_tampered_ciphertext_raises():
    ct, crypto = backup.encrypt_env("X=1\n", "pw")
    bad = bytearray(ct); bad[-1] ^= 0x01
    with pytest.raises(InvalidTag):
        backup.decrypt_env(bytes(bad), "pw", crypto)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backup_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'transcoder.backup'`

- [ ] **Step 3: Write minimal implementation**

```python
# solution/transcoder/backup.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backup_crypto.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/backup.py tests/test_backup_crypto.py
git commit -m "feat(backup): AES-256-GCM env encryption with scrypt KDF"
```

---

### Task 2: Manifest build/validate (`backup.py`)

**Files:**
- Modify: `solution/transcoder/backup.py`
- Test: `tests/test_backup_manifest.py`

**Interfaces:**
- Produces:
  - `APP_ID = "h265-transcoder"`, `SCHEMA_VERSION = 1`
  - `build_manifest(app_version: str, crypto: dict, created_at: str) -> dict`
  - `validate_manifest(m: dict) -> None` — raises `ValueError` on mismatch / newer schema

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backup_manifest.py
import pytest
from transcoder import backup


def test_build_manifest_shape():
    m = backup.build_manifest("1.2.3", {"cipher": "AES-256-GCM"}, "2026-06-23T10:00:00Z")
    assert m["app"] == backup.APP_ID
    assert m["schema_version"] == backup.SCHEMA_VERSION
    assert m["app_version"] == "1.2.3"
    assert m["created_at"] == "2026-06-23T10:00:00Z"
    assert m["crypto"]["cipher"] == "AES-256-GCM"


def test_validate_accepts_current():
    m = backup.build_manifest("1.0.0", {}, "now")
    backup.validate_manifest(m)  # no raise


def test_validate_rejects_foreign_app():
    with pytest.raises(ValueError, match="not an H.265"):
        backup.validate_manifest({"app": "something-else", "schema_version": 1})


def test_validate_rejects_newer_schema():
    with pytest.raises(ValueError, match="newer"):
        backup.validate_manifest({"app": backup.APP_ID, "schema_version": backup.SCHEMA_VERSION + 1})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backup_manifest.py -v`
Expected: FAIL — `AttributeError: module 'transcoder.backup' has no attribute 'APP_ID'`

- [ ] **Step 3: Write minimal implementation** (append to `backup.py`)

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backup_manifest.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/backup.py tests/test_backup_manifest.py
git commit -m "feat(backup): manifest build + validate"
```

---

### Task 3: DB snapshot + zip pack/unpack (`backup.py`)

**Files:**
- Modify: `solution/transcoder/backup.py`
- Test: `tests/test_backup_zip.py`

**Interfaces:**
- Consumes: `encrypt_env`, `decrypt_env`, `build_manifest`, `validate_manifest`.
- Produces:
  - `snapshot_db(db_path: str, dest_path: str) -> None` — consistent sqlite copy
  - `db_path_from_url(url: str) -> str` — `"sqlite:///transcoder.db"` → `"transcoder.db"`
  - `make_backup(db_path: str, env_path: str, passphrase: str, app_version: str = "1.0.0", created_at: str | None = None) -> bytes`
  - `read_backup(zip_bytes: bytes, passphrase: str) -> tuple[bytes, str, dict]` — `(db_bytes, env_text, manifest)`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backup_zip.py
import sqlite3
import zipfile
import io
import pytest
from transcoder import backup


def _make_db(path):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (id INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    con.commit(); con.close()


def test_db_path_from_url():
    assert backup.db_path_from_url("sqlite:///transcoder.db") == "transcoder.db"
    assert backup.db_path_from_url("sqlite:////abs/x.db") == "/abs/x.db"


def test_snapshot_preserves_rows(tmp_path):
    src = tmp_path / "a.db"; dst = tmp_path / "b.db"
    _make_db(str(src))
    backup.snapshot_db(str(src), str(dst))
    con = sqlite3.connect(str(dst))
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 3
    con.close()


def test_make_and_read_backup_roundtrip(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    _make_db(str(db)); env.write_text("APP_PASSWORD=s3cret\n", encoding="utf-8")
    blob = backup.make_backup(str(db), str(env), "pw", app_version="9.9.9",
                              created_at="2026-06-23T00:00:00Z")
    names = zipfile.ZipFile(io.BytesIO(blob)).namelist()
    assert set(names) == {"transcoder.db", "env.enc", "manifest.json"}
    db_bytes, env_text, manifest = backup.read_backup(blob, "pw")
    assert env_text == "APP_PASSWORD=s3cret\n"
    assert manifest["app_version"] == "9.9.9"
    assert db_bytes[:16] == b"SQLite format 3\x00"


def test_read_backup_wrong_passphrase_raises(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    _make_db(str(db)); env.write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(db), str(env), "right", created_at="now")
    with pytest.raises(Exception):
        backup.read_backup(blob, "wrong")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_backup_zip.py -v`
Expected: FAIL — `AttributeError: module 'transcoder.backup' has no attribute 'db_path_from_url'`

- [ ] **Step 3: Write minimal implementation** (append to `backup.py`; add imports at top)

```python
# add to the imports block at the top of backup.py:
import io
import json
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_backup_zip.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/backup.py tests/test_backup_zip.py
git commit -m "feat(backup): db snapshot + zip pack/unpack"
```

---

### Task 4: Restore staging + startup bootstrap (`restore.py`)

**Files:**
- Create: `solution/transcoder/restore.py`
- Test: `tests/test_restore.py`

**Interfaces:**
- Produces:
  - `MARKER = "RESTORE_PENDING"`, `PENDING_DIR = "restore_pending"`
  - `stage_restore(db_bytes: bytes, env_text: str, base_dir: str) -> None`
  - `apply_pending_restore(base_dir: str, db_path: str, env_path: str) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_restore.py
from pathlib import Path
from transcoder import restore


def test_apply_noop_when_no_marker(tmp_path):
    assert restore.apply_pending_restore(
        str(tmp_path), str(tmp_path / "transcoder.db"), str(tmp_path / ".env")
    ) is False


def test_stage_then_apply_swaps_db_and_env(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    db.write_bytes(b"OLD-DB"); env.write_text("OLD=1\n", encoding="utf-8")

    restore.stage_restore(b"NEW-DB", "NEW=2\n", str(tmp_path))
    # marker + staged files exist
    assert (tmp_path / restore.PENDING_DIR / restore.MARKER).exists()

    applied = restore.apply_pending_restore(str(tmp_path), str(db), str(env))
    assert applied is True
    assert db.read_bytes() == b"NEW-DB"
    assert env.read_text(encoding="utf-8") == "NEW=2\n"
    # staging cleaned up so it doesn't re-apply next boot
    assert not (tmp_path / restore.PENDING_DIR).exists()
    # second call is a no-op
    assert restore.apply_pending_restore(str(tmp_path), str(db), str(env)) is False


def test_empty_env_text_skips_env_write(tmp_path):
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    db.write_bytes(b"OLD"); env.write_text("KEEP=1\n", encoding="utf-8")
    restore.stage_restore(b"NEW", "", str(tmp_path))
    restore.apply_pending_restore(str(tmp_path), str(db), str(env))
    assert db.read_bytes() == b"NEW"
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"  # unchanged when backup had no env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_restore.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'transcoder.restore'`

- [ ] **Step 3: Write minimal implementation**

```python
# solution/transcoder/restore.py
from __future__ import annotations

import os
import shutil
from pathlib import Path

MARKER = "RESTORE_PENDING"
PENDING_DIR = "restore_pending"


def stage_restore(db_bytes: bytes, env_text: str, base_dir: str) -> None:
    pend = Path(base_dir) / PENDING_DIR
    if pend.exists():
        shutil.rmtree(pend)
    pend.mkdir(parents=True)
    (pend / "transcoder.db").write_bytes(db_bytes)
    (pend / "env.txt").write_text(env_text, encoding="utf-8")
    # Marker written LAST so a half-staged restore is never applied.
    (pend / MARKER).write_text("", encoding="utf-8")


def apply_pending_restore(base_dir: str, db_path: str, env_path: str) -> bool:
    pend = Path(base_dir) / PENDING_DIR
    if not (pend / MARKER).exists():
        return False
    # Atomic DB swap: copy staged -> temp beside target -> os.replace.
    incoming = str(db_path) + ".incoming"
    shutil.copyfile(pend / "transcoder.db", incoming)
    os.replace(incoming, db_path)
    env_text = (pend / "env.txt").read_text(encoding="utf-8")
    if env_text:  # empty means the backup carried no .env — leave existing one
        Path(env_path).write_text(env_text, encoding="utf-8")
    shutil.rmtree(pend)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_restore.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/restore.py tests/test_restore.py
git commit -m "feat(restore): stage + pre-boot apply of pending restore"
```

---

### Task 5: Relauncher (`restore.py`)

**Files:**
- Modify: `solution/transcoder/restore.py`
- Test: `tests/test_restore_relaunch.py`

**Interfaces:**
- Produces:
  - `relaunch_argv(python_exe: str, package_dir: str) -> list[str]` — pure; the command that restarts the server
  - `schedule_relaunch(python_exe: str | None = None, package_dir: str | None = None) -> None` — spawns it detached (thin; not unit-tested)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_restore_relaunch.py
from transcoder import restore


def test_relaunch_argv_runs_api_module():
    argv = restore.relaunch_argv(r"C:\app\.venv\Scripts\pythonw.exe", r"C:\app")
    assert argv[0].endswith("pythonw.exe")
    assert argv[1:] == ["-m", "transcoder.api"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_restore_relaunch.py -v`
Expected: FAIL — `AttributeError: module 'transcoder.restore' has no attribute 'relaunch_argv'`

- [ ] **Step 3: Write minimal implementation** (append to `restore.py`)

```python
import subprocess
import sys
import time
import socket

_DETACHED = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW


def relaunch_argv(python_exe: str, package_dir: str) -> list[str]:
    return [python_exe, "-m", "transcoder.api"]


def _port_free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def schedule_relaunch(python_exe: str | None = None, package_dir: str | None = None,
                      port: int = 8765) -> None:
    """Spawn a detached process that waits for the port to free, then restarts
    the API. Survives this process exiting. Best-effort; not unit-tested."""
    python_exe = python_exe or sys.executable
    package_dir = package_dir or str(__import__("pathlib").Path(__file__).resolve().parent.parent)
    waiter = (
        "import socket,time,subprocess,sys\n"
        f"for _ in range(60):\n"
        f"    s=socket.socket()\n"
        f"    free=s.connect_ex(('127.0.0.1',{port}))!=0\n"
        f"    s.close()\n"
        f"    if free: break\n"
        f"    time.sleep(0.5)\n"
        f"subprocess.Popen([r'{python_exe}','-m','transcoder.api'], cwd=r'{package_dir}')\n"
    )
    subprocess.Popen([python_exe, "-c", waiter], creationflags=_DETACHED)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_restore_relaunch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/restore.py tests/test_restore_relaunch.py
git commit -m "feat(restore): detached relauncher that waits for the port"
```

---

### Task 6: Backup/restore API router

**Files:**
- Create: `solution/transcoder/api/routers/backup.py`
- Test: `tests/test_api_backup.py`

**Interfaces:**
- Consumes: `transcoder.backup.{make_backup, read_backup, db_path_from_url}`, `transcoder.restore.{stage_restore, schedule_relaunch}`, `transcoder.config.settings`, `transcoder.api.auth.require_auth`.
- Produces: `router` with `POST /api/backup` (JSON `{passphrase}` → zip stream) and `POST /api/restore` (multipart `file` + `passphrase` → `202 {status:"restarting"}`).

**Note on the test fixture:** `tests/api_conftest.py` exposes the `api` fixture which **yields a tuple `(client, Session)`** — unpack it as `client, _ = api`. The client is pre-authenticated (a session cookie is set). Restore must NOT actually relaunch during tests — monkeypatch `schedule_relaunch`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_backup.py
import io
import sqlite3
import zipfile
from transcoder import backup


def test_backup_requires_auth(api):
    client, _ = api
    client.cookies.clear()  # drop the fixture's session cookie
    r = client.post("/api/backup", json={"passphrase": "x"})
    assert r.status_code == 401


def test_backup_returns_zip(api, tmp_path, monkeypatch):
    client, _ = api
    # Point the app's DB + env at temp files with known content.
    import transcoder.config as cfg
    db = tmp_path / "transcoder.db"; env = tmp_path / ".env"
    sqlite3.connect(str(db)).close()
    env.write_text("APP_PASSWORD=z\n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "DATABASE_URL", f"sqlite:///{db}")
    monkeypatch.setattr("transcoder.api.routers.backup.ENV_PATH", str(env))

    r = client.post("/api/backup", json={"passphrase": "pw"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert set(names) == {"transcoder.db", "env.enc", "manifest.json"}


def test_restore_stages_and_returns_202(api, tmp_path, monkeypatch):
    client, _ = api
    src = tmp_path / "src.db"; sqlite3.connect(str(src)).close()
    (tmp_path / "src.env").write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(src), str(tmp_path / "src.env"), "pw", created_at="now")

    staged = {}
    monkeypatch.setattr("transcoder.api.routers.backup.stage_restore",
                        lambda db, env, base: staged.update(db=db, env=env))
    monkeypatch.setattr("transcoder.api.routers.backup.schedule_relaunch", lambda *a, **k: None)

    r = client.post("/api/restore", files={"file": ("b.zip", blob, "application/zip")},
                    data={"passphrase": "pw"})
    assert r.status_code == 202 and r.json()["status"] == "restarting"
    assert staged["env"] == "X=1\n"


def test_restore_wrong_passphrase_400(api, tmp_path, monkeypatch):
    client, _ = api
    src = tmp_path / "s.db"; sqlite3.connect(str(src)).close()
    (tmp_path / "s.env").write_text("X=1\n", encoding="utf-8")
    blob = backup.make_backup(str(src), str(tmp_path / "s.env"), "right", created_at="now")
    monkeypatch.setattr("transcoder.api.routers.backup.schedule_relaunch", lambda *a, **k: None)
    r = client.post("/api/restore", files={"file": ("b.zip", blob, "application/zip")},
                    data={"passphrase": "wrong"})
    assert r.status_code == 400
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_backup.py -v`
Expected: FAIL — router not registered (404) / `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# solution/transcoder/api/routers/backup.py
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from transcoder.api.auth import require_auth
from transcoder.config import settings
from transcoder import backup as backup_mod
from transcoder.backup import make_backup, read_backup, db_path_from_url
from transcoder.restore import stage_restore, schedule_relaunch

router = APIRouter(prefix="/api", tags=["backup"])

# cwd-relative .env (the server runs with cwd = the package dir, like tray.pyw).
ENV_PATH = ".env"


class BackupRequest(BaseModel):
    passphrase: str


def _base_dir(db_path: str) -> str:
    import os
    return os.path.dirname(os.path.abspath(db_path)) or "."


@router.post("/backup", dependencies=[Depends(require_auth)])
def create_backup(body: BackupRequest):
    db_path = db_path_from_url(settings.DATABASE_URL)
    try:
        blob = make_backup(db_path, ENV_PATH, body.passphrase)
    except Exception as exc:  # snapshot/encrypt failure
        raise HTTPException(status_code=500, detail=f"backup failed: {exc}")
    from datetime import datetime, timezone
    name = "h265-backup-" + datetime.now(timezone.utc).strftime("%Y%m%d") + ".zip"
    return Response(content=blob, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/restore", status_code=202, dependencies=[Depends(require_auth)])
async def restore_backup(file: UploadFile = File(...), passphrase: str = Form(...)):
    zip_bytes = await file.read()
    try:
        db_bytes, env_text, _manifest = read_backup(zip_bytes, passphrase)
    except Exception:
        raise HTTPException(status_code=400, detail="wrong passphrase or corrupt backup")
    db_path = db_path_from_url(settings.DATABASE_URL)
    stage_restore(db_bytes, env_text, _base_dir(db_path))
    schedule_relaunch()
    return {"status": "restarting"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_backup.py -v`
Expected: PASS (4 tests). If `test_backup_requires_auth` needs `api.app`, the fixture exposes the FastAPI app as `api.app` (TestClient attribute).

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/routers/backup.py tests/test_api_backup.py
git commit -m "feat(api): POST /api/backup + /api/restore"
```

---

### Task 7: Wire router + startup bootstrap in `app.py`

**Files:**
- Modify: `solution/transcoder/api/app.py`
- Test: `tests/test_app_restore_bootstrap.py`

**Interfaces:**
- Consumes: `transcoder.restore.apply_pending_restore`, `transcoder.backup.db_path_from_url`.
- The bootstrap MUST run **before** `init_db()` (so the swapped DB is the one opened).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_restore_bootstrap.py
import transcoder.api.app as app_module


def test_apply_pending_restore_called_before_init_db(monkeypatch):
    calls = []
    monkeypatch.setattr(app_module, "apply_pending_restore",
                        lambda *a, **k: calls.append("restore") or False)
    monkeypatch.setattr(app_module, "init_db", lambda *a, **k: calls.append("init_db"))
    monkeypatch.setattr(app_module, "backup_db", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "ensure_job_columns", lambda *a, **k: None)
    monkeypatch.setattr(app_module, "migrate_legacy", lambda *a, **k: None)

    app = app_module.create_app(start_worker=False)
    from fastapi.testclient import TestClient
    with TestClient(app):
        pass
    assert calls[:2] == ["restore", "init_db"]


def test_backup_router_registered():
    app = app_module.create_app(start_worker=False)
    paths = {r.path for r in app.routes}
    assert "/api/backup" in paths and "/api/restore" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app_restore_bootstrap.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'apply_pending_restore'` / paths missing

- [ ] **Step 3: Write minimal implementation**

In `solution/transcoder/api/app.py`:

1. Add imports near the other `transcoder` imports (top of file):

```python
from transcoder.restore import apply_pending_restore
from transcoder.backup import db_path_from_url
```

2. At the **very start** of the `lifespan` body, before `init_db()`:

```python
        init_logging("api")
        # Apply a staged restore BEFORE opening the DB, so the swapped-in DB is
        # the one we boot on.
        _dbp = db_path_from_url(settings.DATABASE_URL)
        import os as _os
        apply_pending_restore(_os.path.dirname(_os.path.abspath(_dbp)) or ".", _dbp, ".env")
        init_db()
```

(Replace the existing `init_logging("api")` + `init_db()` lines.)

3. Register the router in the protected block:

```python
    from transcoder.api.routers import library, scan, jobs, exclusions, stream, logs, backup
    ...
    app.include_router(backup.router, dependencies=protected)
```

4. **Neutralize the bootstrap in the shared test fixture** so the many tests that
use `api` don't hit the real filesystem on every app startup. In
`tests/api_conftest.py`, add to the `monkeypatch.setattr(...)` block (next to the
other `app_module` neutralizations):

```python
    monkeypatch.setattr(app_module, "apply_pending_restore", lambda *a, **k: False)
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_app_restore_bootstrap.py tests/test_api_backup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add solution/transcoder/api/app.py tests/test_app_restore_bootstrap.py
git commit -m "feat(api): apply pending restore before DB init; register backup router"
```

---

### Task 8: Web API client methods + types

**Files:**
- Modify: `solution/web/src/api/client.ts`
- Modify: `solution/web/src/api/types.ts` (if a type is needed)
- Test: `solution/web/src/api/client.test.ts`

**Interfaces:**
- Produces (exported from `client.ts`):
  - `downloadBackup(passphrase: string): Promise<Blob>`
  - `restoreBackup(file: File, passphrase: string): Promise<void>`

- [ ] **Step 1: Write the failing test** (append to `client.test.ts`)

```typescript
import { downloadBackup, restoreBackup } from './client';

describe('backup/restore', () => {
  it('downloadBackup POSTs passphrase and returns a blob', async () => {
    const blob = new Blob(['zip']);
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, blob: () => Promise.resolve(blob) });
    vi.stubGlobal('fetch', fetchMock);
    const out = await downloadBackup('pw');
    expect(out).toBe(blob);
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/backup');
    expect(opts.method).toBe('POST');
    expect(JSON.parse(opts.body)).toEqual({ passphrase: 'pw' });
    vi.unstubAllGlobals();
  });

  it('restoreBackup POSTs multipart file + passphrase', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 202 });
    vi.stubGlobal('fetch', fetchMock);
    await restoreBackup(new File(['z'], 'b.zip'), 'pw');
    const [url, opts] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/restore');
    expect(opts.method).toBe('POST');
    expect(opts.body).toBeInstanceOf(FormData);
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd solution/web && npm test -- client.test.ts`
Expected: FAIL — `downloadBackup is not a function`

- [ ] **Step 3: Write minimal implementation** (append to `client.ts`)

```typescript
export async function downloadBackup(passphrase: string): Promise<Blob> {
  const res = await fetch('/api/backup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ passphrase }),
    credentials: 'same-origin',
  });
  if (!res.ok) throw new ApiError(res.status, 'backup failed');
  return res.blob();
}

export async function restoreBackup(file: File, passphrase: string): Promise<void> {
  const fd = new FormData();
  fd.append('file', file);
  fd.append('passphrase', passphrase);
  const res = await fetch('/api/restore', { method: 'POST', body: fd, credentials: 'same-origin' });
  if (!res.ok) {
    let detail = 'restore failed';
    try { const j = await res.json(); detail = j?.detail ?? detail; } catch { /* */ }
    throw new ApiError(res.status, detail);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd solution/web && npm test -- client.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/api/client.ts solution/web/src/api/client.test.ts
git commit -m "feat(web): backup/restore API client methods"
```

---

### Task 9: Settings "Backup & Restore" card

**Files:**
- Create: `solution/web/src/pages/BackupRestoreCard.tsx`
- Modify: `solution/web/src/pages/Settings.tsx` (render the card)
- Test: `solution/web/src/pages/BackupRestoreCard.test.tsx`

**Interfaces:**
- Consumes: `downloadBackup`, `restoreBackup` from `../api/client`.
- Produces: default-exported `<BackupRestoreCard />`.

**Behavior:** a passphrase input + "Download backup" button (calls `downloadBackup`, triggers a browser save via an object URL). A file input + passphrase + "Restore" button (calls `restoreBackup`, then shows "Restarting… reconnecting" and polls `/api/health` until ok, then `location.reload()`). Show a data-loss warning near Restore.

- [ ] **Step 1: Write the failing test**

```tsx
// solution/web/src/pages/BackupRestoreCard.test.tsx
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BackupRestoreCard from './BackupRestoreCard';
import * as client from '../api/client';

it('downloads a backup with the entered passphrase', async () => {
  const spy = vi.spyOn(client, 'downloadBackup').mockResolvedValue(new Blob(['z']));
  // jsdom lacks object-URL APIs
  (URL as unknown as { createObjectURL: () => string }).createObjectURL = () => 'blob:x';
  (URL as unknown as { revokeObjectURL: () => void }).revokeObjectURL = () => {};
  render(<BackupRestoreCard />);
  fireEvent.change(screen.getByLabelText(/backup passphrase/i), { target: { value: 'pw' } });
  fireEvent.click(screen.getByRole('button', { name: /download backup/i }));
  await waitFor(() => expect(spy).toHaveBeenCalledWith('pw'));
});

it('warns about data loss near restore', () => {
  render(<BackupRestoreCard />);
  expect(screen.getByText(/replaces all data/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd solution/web && npm test -- BackupRestoreCard`
Expected: FAIL — cannot find module `./BackupRestoreCard`

- [ ] **Step 3: Write minimal implementation**

```tsx
// solution/web/src/pages/BackupRestoreCard.tsx
import { useState } from 'react';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { downloadBackup, restoreBackup } from '../api/client';

export default function BackupRestoreCard() {
  const [backupPass, setBackupPass] = useState('');
  const [restorePass, setRestorePass] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState('');

  async function onDownload() {
    setStatus('');
    try {
      const blob = await downloadBackup(backupPass);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      a.href = url; a.download = `h265-backup-${stamp}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatus(`Backup failed: ${(e as Error).message}`);
    }
  }

  async function onRestore() {
    if (!file) { setStatus('Choose a backup file first.'); return; }
    setStatus('Uploading…');
    try {
      await restoreBackup(file, restorePass);
      setStatus('Restarting… reconnecting');
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        try {
          const res = await fetch('/api/health');
          if (res.ok) { location.reload(); return; }
        } catch { /* server still down */ }
      }
      setStatus('Restore applied, but the server did not come back — check the service.');
    } catch (e) {
      setStatus(`Restore failed: ${(e as Error).message}`);
    }
  }

  return (
    <Card>
      <CardHeader>Backup &amp; Restore</CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="backup-pass" className="block text-xs font-medium text-muted">
            Backup passphrase (encrypts your credentials)
          </label>
          <Input id="backup-pass" type="password" value={backupPass}
                 onChange={(e) => setBackupPass(e.target.value)} />
          <Button onClick={onDownload} disabled={!backupPass}>Download backup</Button>
        </div>
        <div className="space-y-2 border-t pt-4">
          <p className="text-xs text-red-500">
            ⚠ Restore replaces all data on this instance (database + credentials) and restarts it.
          </p>
          <input aria-label="backup file" type="file" accept=".zip"
                 onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <label htmlFor="restore-pass" className="block text-xs font-medium text-muted">
            Backup passphrase
          </label>
          <Input id="restore-pass" type="password" value={restorePass}
                 onChange={(e) => setRestorePass(e.target.value)} />
          <Button onClick={onRestore} disabled={!file || !restorePass}>Restore</Button>
        </div>
        {status && <p className="text-sm text-muted">{status}</p>}
      </CardContent>
    </Card>
  );
}
```

4. In `Settings.tsx`: import and render it. Add near the top with the other imports:

```tsx
import BackupRestoreCard from './BackupRestoreCard';
```

And render `<BackupRestoreCard />` at the end of the settings cards list (inside the same container that holds the other `<Card>`s).

- [ ] **Step 4: Run tests**

Run: `cd solution/web && npm test -- BackupRestoreCard`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add solution/web/src/pages/BackupRestoreCard.tsx solution/web/src/pages/BackupRestoreCard.test.tsx solution/web/src/pages/Settings.tsx
git commit -m "feat(web): Backup & Restore card on Settings"
```

---

### Task 10: Docs

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: Update CLAUDE.md** — in the API endpoints list (Serve section), add:

```
`POST /api/backup` (JSON `{passphrase}` → streams an encrypted `backup.zip`),
`POST /api/restore` (multipart `file` + `passphrase`; stages the backup, then the
app relaunches itself and a pre-DB-init bootstrap applies it),
```

And in the Web UI Screens list, add to Settings: "…and a Backup & Restore section (download an encrypted state backup; restore one onto a new instance)."

- [ ] **Step 2: Update README.md** — under Features/Architecture, add a line:

```
- **Backup & Restore** — download an encrypted (AES-256-GCM) state backup (DB + .env)
  from Settings; restore it onto a freshly installed instance to clone it.
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -q && cd solution/web && npm test`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document backup & restore"
```

---

## Self-Review

**Spec coverage:**
- Backup contents (db snapshot + encrypted env + manifest) → Tasks 1–3. ✓
- AES-256-GCM + scrypt → Task 1. ✓
- Backup flow (`POST /api/backup`, stream zip) → Task 6. ✓
- Restore flow (validate, decrypt, stage, relaunch, pre-init bootstrap) → Tasks 4, 5, 6, 7. ✓
- Wholesale replace + empty-env handling → Task 4. ✓
- UI card (download + restore + reconnect + warning) → Tasks 8, 9. ✓
- Error handling (wrong passphrase 400, foreign/newer manifest) → Tasks 2, 3, 6. ✓
- Testing across units → every task. ✓
- Docs → Task 10. ✓

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `make_backup`/`read_backup`/`db_path_from_url`/`stage_restore`/`apply_pending_restore`/`schedule_relaunch`/`downloadBackup`/`restoreBackup` signatures match between producing and consuming tasks.

**Note for implementer:** the `api` fixture in `tests/api_conftest.py` **yields `(client, Session)`** — always unpack `client, _ = api`. The client is pre-authenticated; drop its cookie with `client.cookies.clear()` to test the 401 path. The restore tests MUST monkeypatch `schedule_relaunch` so no real process spawns during the suite. Task 7 adds `apply_pending_restore` to the fixture's neutralized list — don't skip that, or every API test will touch the cwd filesystem.
