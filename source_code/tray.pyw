"""Windows system tray launcher for the H.265 Transcoder service.

Run via scripts/tray.bat or:  .venv\Scripts\pythonw.exe tray.pyw
Double-click the tray icon to open the web UI; right-click for the menu.
"""
import http.cookiejar
import json
import logging
import logging.handlers
import os
import pathlib
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

_LOG_DIR = pathlib.Path(__file__).parent / "log"
_ARCHIVE_DIR = _LOG_DIR / "archive"
_FMT = "%(asctime)s - %(levelname)s - %(message)s"


def _make_daily_handler(path: pathlib.Path, backup_days: int = 30) -> logging.handlers.TimedRotatingFileHandler:
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    h = logging.handlers.TimedRotatingFileHandler(
        str(path), when="midnight", backupCount=backup_days, encoding="utf-8", utc=False
    )
    h.namer = lambda name: str(_ARCHIVE_DIR / pathlib.Path(name).name)
    h.rotator = lambda src, dst: os.rename(src, dst)
    fmt = logging.Formatter(_FMT)
    fmt.converter = time.localtime
    h.setFormatter(fmt)
    return h


_LOG_DIR.mkdir(exist_ok=True)
logging.root.setLevel(logging.INFO)
logging.root.addHandler(_make_daily_handler(_LOG_DIR / "tray.log"))

log = logging.getLogger("tray")
log.info("tray.pyw starting")

# Separate logger for server subprocess output — goes to server_start.log only.
_srv_log = logging.getLogger("server_start")
_srv_log.propagate = False
_srv_log.setLevel(logging.INFO)
_srv_log.addHandler(_make_daily_handler(_LOG_DIR / "server_start.log"))

try:
    import pystray
    from PIL import Image, ImageDraw
    log.info("pystray + PIL imported OK")
except ImportError as exc:
    log.exception("Missing dependency: %s", exc)
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

# Cookie jar so the tray maintains an authenticated session across requests.
_cookie_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_cookie_jar))


def _read_app_password() -> str:
    env_file = SOURCE_CODE_DIR / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("APP_PASSWORD="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _ensure_authed() -> None:
    """POST /api/login if the session cookie is not yet established."""
    password = _read_app_password()
    if not password:
        return
    payload = json.dumps({"password": password}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/api/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        _opener.open(req, timeout=3)
    except Exception:
        pass

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
        _opener.open(f"{BASE_URL}/api/health", timeout=2)
        return True
    except Exception:
        return False


def _get_json(path: str):
    try:
        with _opener.open(f"{BASE_URL}{path}", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        return None


# ── poll thread ───────────────────────────────────────────────────────────────

def _poll(icon: pystray.Icon) -> None:
    was_up = False
    while True:
        up = _is_up()
        icon.icon = _make_icon(up)

        if up:
            if not was_up:
                # Server just came online — authenticate so cookie is set.
                _ensure_authed()
            _check_job_transitions(icon)
        else:
            # Reset state so we don't misfire on reconnect.
            _poll_state["prev_job_id"] = None
            _poll_state["prev_queue_len"] = None

        was_up = up
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

def _find_server_pid() -> int | None:
    """Return the PID of whatever process is listening on port 8765, or None."""
    try:
        out = subprocess.check_output(
            ["netstat", "-ano"], text=True, stderr=subprocess.DEVNULL
        )
        for line in out.splitlines():
            if ":8765 " in line and "LISTENING" in line:
                return int(line.split()[-1])
    except Exception:
        pass
    return None


def _open_ui(_icon, _item) -> None:
    webbrowser.open(BASE_URL)


def _pipe_stream(stream, level: int) -> None:
    for line in stream:
        line = line.rstrip("\r\n")
        if line:
            _srv_log.log(level, line)


def _start_server(_icon, _item) -> None:
    global _server_proc
    # Don't start a second instance if anything is already serving.
    if _is_up():
        log.info("Start clicked but server already up")
        return
    if _server_proc and _server_proc.poll() is None:
        return
    log.info("Starting server via %s", _VENV_PY)
    _server_proc = subprocess.Popen(
        [str(_VENV_PY), "-m", "transcoder.api"],
        cwd=str(SOURCE_CODE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    threading.Thread(target=_pipe_stream, args=(_server_proc.stdout, logging.INFO), daemon=True).start()
    threading.Thread(target=_pipe_stream, args=(_server_proc.stderr, logging.WARNING), daemon=True).start()


def _stop_server(_icon, _item) -> None:
    global _server_proc
    # Terminate process we own.
    if _server_proc and _server_proc.poll() is None:
        log.info("Terminating owned server process")
        _server_proc.terminate()
    _server_proc = None
    # Also kill any externally-started process on the port.
    pid = _find_server_pid()
    if pid:
        log.info("Killing external server PID %s", pid)
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           check=True, capture_output=True)
        except Exception as exc:
            log.warning("taskkill failed: %s", exc)


def _exit(icon, item) -> None:
    _stop_server(icon, item)
    icon.stop()
    import os
    os._exit(0)


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
    _start_server(None, None)
    icon.run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("tray crashed")
        raise
