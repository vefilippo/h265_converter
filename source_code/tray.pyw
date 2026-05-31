"""Windows system tray launcher for the H.265 Transcoder service.

Run via scripts/tray.bat or:  .venv\Scripts\pythonw.exe tray.pyw
Double-click the tray icon to open the web UI; right-click for the menu.
"""
import json
import logging
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError as exc:
    import tkinter.messagebox as _mb
    _mb.showerror("Missing dependency", str(exc))
    sys.exit(1)

BASE_URL = "http://localhost:8765"
SOURCE_CODE_DIR = pathlib.Path(__file__).parent
_VENV_PY = SOURCE_CODE_DIR / ".venv" / "Scripts" / "pythonw.exe"
if not _VENV_PY.exists():
    _VENV_PY = pathlib.Path(sys.executable)

_server_proc: subprocess.Popen | None = None
_poll_state: dict = {"prev_job_id": None, "prev_queue_len": None}

log = logging.getLogger("tray")


# ── icon helpers ──────────────────────────────────────────────────────────────

def _make_icon(online: bool) -> Image.Image:
    colour = "#22c55e" if online else "#6b7280"
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((6, 6, 58, 58), fill=colour)
    return img


# ── API helpers ───────────────────────────────────────────────────────────────

def _is_up() -> bool:
    try:
        urllib.request.urlopen(f"{BASE_URL}/api/health", timeout=2)
        return True
    except Exception:
        return False


def _get_json(path: str):
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── poll thread ───────────────────────────────────────────────────────────────

def _poll(icon: pystray.Icon) -> None:
    while True:
        up = _is_up()
        icon.icon = _make_icon(up)

        if up:
            _check_job_transitions(icon)
        else:
            # Reset state so we don't misfire on reconnect.
            _poll_state["prev_job_id"] = None
            _poll_state["prev_queue_len"] = None

        time.sleep(5)


def _check_job_transitions(icon: pystray.Icon) -> None:
    status = _get_json("/api/status")
    if not status:
        return

    cur = status.get("current_job")
    queue_len = status.get("queue_length", 0)
    cur_id = cur["id"] if cur else None
    prev_id = _poll_state["prev_job_id"]
    prev_q = _poll_state["prev_queue_len"]

    # A job just finished (running job changed or worker went idle).
    if prev_id is not None and cur_id != prev_id:
        job = _get_json(f"/api/jobs/{prev_id}")
        if job:
            label = _job_label(job)
            if job["state"] == "done":
                _notify("H265 Transcoder", f"✓ Transcoded: {label}")
            elif job["state"] == "failed":
                _notify("H265 Transcoder", f"✗ Failed: {label} — see logs")

    # Queue drained to empty while nothing is running.
    if prev_q is not None and prev_q > 0 and queue_len == 0 and cur_id is None:
        _notify("H265 Transcoder", "Queue clear — all jobs done")

    _poll_state["prev_job_id"] = cur_id
    _poll_state["prev_queue_len"] = queue_len


def _job_label(job: dict) -> str:
    title = job.get("title") or f"Job #{job.get('id')}"
    s, e = job.get("season"), job.get("episode")
    if s is not None and e is not None:
        return f"{title} — S{str(s).zfill(2)}E{str(e).zfill(2)}"
    return title


def _notify(title: str, msg: str) -> None:
    try:
        from winotify import Notification, audio
        n = Notification(app_id="H265 Transcoder", title=title, msg=msg)
        n.set_audio(audio.Default, loop=False)
        n.show()
    except Exception as exc:
        log.warning("toast failed: %s", exc)


# ── menu actions ──────────────────────────────────────────────────────────────

def _open_ui(_icon, _item) -> None:
    webbrowser.open(BASE_URL)


def _start_server(_icon, _item) -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        return
    _server_proc = subprocess.Popen(
        [str(_VENV_PY), "-m", "transcoder.api"],
        cwd=str(SOURCE_CODE_DIR),
    )


def _stop_server(_icon, _item) -> None:
    global _server_proc
    if _server_proc and _server_proc.poll() is None:
        _server_proc.terminate()
    _server_proc = None


def _exit(icon, item) -> None:
    _stop_server(icon, item)
    icon.stop()


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    icon = pystray.Icon(
        name="h265transcoder",
        icon=_make_icon(False),
        title="H265 Transcoder",
        menu=pystray.Menu(
            pystray.MenuItem("Open UI", _open_ui, default=True),
            pystray.MenuItem("Start", _start_server),
            pystray.MenuItem("Stop", _stop_server),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", _exit),
        ),
    )
    threading.Thread(target=_poll, args=(icon,), daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
