"""Stage the bundled payload for the installer from git-tracked files only.

Whitelist, never denylist: `git ls-files -- solution` lists exactly the tracked
build context. Everything sensitive (.env, transcoder.db, .venv, logs) is
gitignored, so it cannot appear here — leakage is structurally impossible. The
one tracked-but-not-listed thing we need is the *built* web UI (web/dist is
gitignored), so we run the Vite build and copy dist explicitly.

Run from anywhere:  python deploy/h265-transcoder/stage_payload.py
Output:             deploy/h265-transcoder/build/payload/solution/...
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import installer_lib as lib

HERE = Path(__file__).resolve().parent
# stage_payload.py lives at deploy/h265-transcoder/ → repo root is two levels up.
REPO_ROOT = HERE.parent.parent
BUILD_DIR = HERE / "build"
PAYLOAD_DIR = BUILD_DIR / "payload"


def _run(argv, cwd=None):
    print("  $", " ".join(argv))
    subprocess.run(argv, cwd=cwd, check=True)


def tracked_payload_files(repo_root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", lib.PAYLOAD_DIRNAME],
        cwd=repo_root, capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    return [rel for rel in out if rel and lib.payload_should_ship(rel)]


def stage(repo_root: Path = REPO_ROOT, payload_dir: Path = PAYLOAD_DIR,
          build_web: bool = True) -> Path:
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    payload_dir.mkdir(parents=True)

    files = tracked_payload_files(repo_root)
    print(f"[stage] copying {len(files)} tracked files from {repo_root}")
    for rel in files:
        src = repo_root / rel
        dst = Path(lib.payload_dest(rel, str(payload_dir)))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    if build_web:
        web = repo_root / lib.PAYLOAD_DIRNAME / "web"
        print("[stage] building web UI (npm run build)")
        npm = shutil.which("npm") or "npm"
        _run([npm, "install"], cwd=web)
        _run([npm, "run", "build"], cwd=web)
        dist_src = web / "dist"
        dist_dst = payload_dir / lib.PAYLOAD_DIRNAME / "web" / "dist"
        if dist_dst.exists():
            shutil.rmtree(dist_dst)
        shutil.copytree(dist_src, dist_dst)
        print(f"[stage] bundled built UI -> {dist_dst}")

    print(f"[stage] done -> {payload_dir / lib.PAYLOAD_DIRNAME}")
    return payload_dir


if __name__ == "__main__":
    sys.exit(0 if stage(build_web="--no-web" not in sys.argv) else 1)
