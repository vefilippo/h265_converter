import logging
import os
import re
import subprocess
import time

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

    for line in process.stdout:
        if cancel_event is not None and cancel_event.is_set():
            process.kill()
            raise TranscodeCancelled()
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
        log.error("HandBrake conversion failed. Skipping this file.")
        return None, False

    original_size = os.path.getsize(input_file) / (1024 * 1024)
    new_size = os.path.getsize(output_file) / (1024 * 1024)
    reduction = ((original_size - new_size) / original_size) * 100 if original_size > 0 else 0
    log.info("Size Reduction: %.2f%% (took %.0fs)", reduction, elapsed)

    return output_file, new_size >= original_size
