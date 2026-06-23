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
