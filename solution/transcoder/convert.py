import logging
import os
import re
import subprocess
import time
from collections import deque

from transcoder.config import settings

log = logging.getLogger("transcoder")

_PROGRESS_RE = re.compile(r"Encoding: .*?\s(\d{1,3})\.\d+ %")


class TranscodeCancelled(Exception):
    """Raised when a transcode is cancelled via its cancel_event."""


def parse_handbrake_progress(line: str):
    match = _PROGRESS_RE.search(line)
    return int(match.group(1)) if match else None


def convert_with_handbrake(input_file, output_filename, preset, progress_cb=None, cancel_event=None, handbrake_cli=None):
    output_file = settings.OUTPUT_FOLDER + output_filename

    command = [
        handbrake_cli if handbrake_cli is not None else settings.HANDBRAKE_CLI,
        "-i", input_file,
        "-o", output_file,
        "--preset", preset,
        "--all-audio",
        "-f", settings.OUTPUT_FORMAT,
        "--all-subtitles",
    ]

    # HandBrake won't create the destination directory; if it's missing it exits
    # immediately with "avio_open2 failed ... Could not write to indicated output
    # file" (error 3). OUTPUT_FOLDER defaults to a relative "./out/", which exists
    # in a dev checkout but not in a fresh install — so create it up front.
    out_dir = os.path.dirname(output_file)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    start = time.time()
    log.info("Conversion Started for %s", output_filename)
    # CREATE_NO_WINDOW (Windows only) stops HandBrakeCLI — a console app — from
    # popping up an empty console window when launched from a service/tray with
    # no console of its own. Flag is absent on non-Windows platforms.
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
        creationflags=creationflags,
    )

    # HandBrake's stderr is merged into stdout; keep the last lines so a non-zero
    # exit can report the actual cause (e.g. "avio_open2 failed ...") instead of a
    # bare "conversion failed" — most of the stream is progress noise we drop.
    tail: deque[str] = deque(maxlen=20)
    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            raise TranscodeCancelled()
        stripped = line.rstrip()
        if stripped:
            tail.append(stripped)
        pct = parse_handbrake_progress(line)
        if pct is not None and progress_cb is not None:
            try:
                progress_cb(pct)
            except Exception:
                # A progress-update failure (e.g. a transient DB write error)
                # must not abort the transcode or orphan the subprocess.
                pass

    process.wait()
    elapsed = time.time() - start

    # NOTE: the caller (worker) owns temp-file cleanup of input_file via its
    # finally block; this function no longer deletes it, to keep a single
    # owner of the file lifecycle.
    if process.returncode != 0:
        log.error(
            "HandBrake conversion failed (exit %s). Last output:\n%s",
            process.returncode, "\n".join(tail),
        )
        return None, False

    original_size = os.path.getsize(input_file) / (1024 * 1024)
    new_size = os.path.getsize(output_file) / (1024 * 1024)
    reduction = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
    log.info("Size Reduction: %.2f%% (took %.0fs)", reduction, elapsed)

    return output_file, new_size >= original_size
