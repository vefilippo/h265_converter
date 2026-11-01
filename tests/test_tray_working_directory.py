"""The tray must read API_PORT from the .env beside it, whatever cwd it starts in.

The installed logon scheduled task starts tray.pyw with no working directory, so
it ran in C:\\Windows\\System32. transcoder.config resolves env_file=".env"
against the cwd, so the tray missed .env and fell back to port 8765, while the
server child (spawned with cwd=SOURCE_CODE_DIR) read API_PORT=8766 from it. The
tray then polled the wrong port and reported "Server failed to start".

This runs in a subprocess because the behaviour under test is what a fresh
interpreter does at import time from a foreign cwd.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys

_SOLUTION = pathlib.Path(__file__).resolve().parents[1] / "solution"

_LAUNCH = """
import json, pathlib, runpy, sys
tray = pathlib.Path(sys.argv[1])
sys.path.insert(0, str(tray.parent))
ns = runpy.run_path(str(tray), run_name="tray_under_test")
import transcoder.config
print(json.dumps({
    "port": ns["_API_PORT"],
    "config_imported": "_settings" in ns,
    "config_file": transcoder.config.__file__,
}))
"""


def test_tray_reads_port_from_env_beside_it_when_started_elsewhere(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "transcoder").mkdir(parents=True)
    tray = app_dir / "tray.pyw"
    shutil.copy(_SOLUTION / "tray.pyw", tray)
    for name in ("__init__.py", "config.py"):
        shutil.copy(_SOLUTION / "transcoder" / name, app_dir / "transcoder" / name)
    (app_dir / ".env").write_text("API_PORT=9871\n", encoding="utf-8")

    foreign_cwd = tmp_path / "foreign_cwd"
    foreign_cwd.mkdir()

    env = {k: v for k, v in os.environ.items() if k not in ("API_PORT", "PYTHONPATH")}
    result = subprocess.run(
        [sys.executable, "-c", _LAUNCH, str(tray)],
        cwd=foreign_cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    seen = json.loads(result.stdout.strip().splitlines()[-1])
    # Guard against the tray's except-branch: it also yields 8765, for a
    # different reason (the copied config failed to import).
    assert seen["config_imported"], "tray fell back: transcoder.config did not import"
    assert pathlib.Path(seen["config_file"]).parent == app_dir / "transcoder"
    assert seen["port"] == 9871
