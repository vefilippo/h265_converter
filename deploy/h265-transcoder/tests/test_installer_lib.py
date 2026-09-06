"""Unit tests for the pure installer helpers (no Windows/GUI/subprocess needed).

These cover the path resolution, schtasks argv, registry value, shortcut spec,
and payload path-mapping logic. The actual subprocess/registry/GUI I/O in
host_setup.py / stage_payload.py is live and smoke-tested by running the frozen
exe once — see windows-installer.md.
"""
import os
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import installer_lib as lib  # noqa: E402


def test_default_install_dir_uses_localappdata():
    env = {"LOCALAPPDATA": r"C:\Users\me\AppData\Local"}
    assert lib.default_install_dir(env) == r"C:\Users\me\AppData\Local\H265Transcoder"


def test_default_install_dir_falls_back_to_home_when_unset():
    got = lib.default_install_dir({})
    assert got.endswith("H265Transcoder")
    assert "AppData" in got


def test_payload_layout_paths_nest_under_solution():
    inst = r"C:\X\H265Transcoder"
    assert lib.payload_root(inst) == r"C:\X\H265Transcoder\solution"
    assert lib.tray_script(inst).endswith(r"\solution\tray.pyw")
    assert lib.venv_pythonw(inst).endswith(r"\solution\.venv\Scripts\pythonw.exe")
    assert lib.venv_python(inst).endswith(r"\solution\.venv\Scripts\python.exe")
    assert lib.setup_exe_path(inst) == r"C:\X\H265Transcoder\h265-transcoder-setup.exe"


def test_logon_task_tr_quotes_both_paths_as_one_arg():
    tr = lib.logon_task_tr(r"C:\a\pythonw.exe", r"C:\a\tray.pyw")
    # schtasks /tr needs the program AND its arg quoted inside one string.
    assert tr == r'"C:\a\pythonw.exe" "C:\a\tray.pyw"'


def test_create_task_argv_onlogon_and_preserves_highest():
    argv = lib.create_task_argv("H265Transcoder", r"C:\a\pythonw.exe", r"C:\a\tray.pyw")
    assert argv[:4] == ["schtasks", "/create", "/tn", "H265Transcoder"]
    assert "/sc" in argv and argv[argv.index("/sc") + 1] == "onlogon"
    assert "/f" in argv
    # We deliberately keep /rl highest (GPU + network-share access), matching the
    # legacy install-service.bat — see CLAUDE.md / the migration decision.
    assert "/rl" in argv and argv[argv.index("/rl") + 1] == "highest"


def test_create_task_argv_can_drop_highest():
    argv = lib.create_task_argv("T", "pw", "t", highest=False)
    assert "/rl" not in argv


def test_delete_task_argv():
    assert lib.delete_task_argv("H265Transcoder") == [
        "schtasks", "/delete", "/tn", "H265Transcoder", "/f",
    ]


def test_uninstall_registry_values_complete_and_self_referential():
    inst = r"C:\X\H265Transcoder"
    vals = lib.uninstall_registry_values(inst, "1.2.3")
    assert vals["DisplayVersion"] == "1.2.3"
    assert vals["InstallLocation"] == inst
    # UninstallString points at the copied-in exe with --uninstall.
    assert vals["UninstallString"] == r'"C:\X\H265Transcoder\h265-transcoder-setup.exe" --uninstall'
    assert vals["QuietUninstallString"].endswith("--uninstall --quiet")
    assert vals["NoModify"] == 1 and vals["NoRepair"] == 1
    assert vals["DisplayName"] and vals["Publisher"]


def test_uninstall_key_path_is_per_user_hkcu_relative():
    # Relative to HKCU (the caller opens HKEY_CURRENT_USER); no admin needed.
    assert lib.UNINSTALL_KEY.endswith("H265Transcoder")
    assert "CurrentVersion\\Uninstall" in lib.UNINSTALL_KEY
    assert not lib.UNINSTALL_KEY.startswith("HKEY")


def test_shortcut_spec_points_pythonw_at_tray_no_console():
    inst = r"C:\X\H265Transcoder"
    spec = lib.shortcut_spec(inst)
    assert spec["target"].endswith("pythonw.exe")
    assert spec["arguments"] == r'"C:\X\H265Transcoder\solution\tray.pyw"'
    assert spec["working_dir"] == r"C:\X\H265Transcoder\solution"


def test_uninstall_script_wipes_whole_dir_with_bounded_retry():
    s = lib.uninstall_script(r"C:\Users\me\AppData\Local\H265Transcoder")
    # Targets the whole install dir, recursively + quietly.
    assert 'set "DIR=C:\\Users\\me\\AppData\\Local\\H265Transcoder"' in s
    assert 'rmdir /s /q "%DIR%"' in s
    # Retries until the folder is actually gone (single rmdir races the exe lock).
    assert ":retry" in s and "goto retry" in s
    assert 'if not exist "%DIR%" goto done' in s
    # Bounded so a permanent lock can't loop forever.
    assert "geq 30 goto done" in s
    # Self-deletes the script afterwards.
    assert 'del "%~f0"' in s


def test_uninstall_script_has_no_parens_inside_if_block():
    # Literal ( ) inside an `if (...)` closes the block early (". was unexpected").
    # The only legitimate parens are the `(goto)` self-delete idiom.
    s = lib.uninstall_script(r"C:\X")
    for line in s.splitlines():
        if line.startswith("if "):
            assert "(" not in line and ")" not in line


def test_payload_should_ship_only_solution_tree():
    assert lib.payload_should_ship("solution/transcoder/api/app.py")
    assert lib.payload_should_ship("solution/tray.pyw")
    # forward/back slash agnostic
    assert lib.payload_should_ship(r"solution\requirements.txt")
    # never ship trees outside the build context
    assert not lib.payload_should_ship("tests/conftest.py")
    assert not lib.payload_should_ship("deploy/h265-transcoder/host_setup.py")
    assert not lib.payload_should_ship("README.md")


def test_payload_dest_preserves_relative_tree_under_dest_root():
    dest = lib.payload_dest("solution/transcoder/api/app.py", os.path.join("build", "payload"))
    assert pathlib.Path(dest) == pathlib.Path("build/payload/solution/transcoder/api/app.py")


# --- port_is_free / first_free_port -----------------------------------------
#
# port_is_free duplicates the tiny connect_ex probe in
# transcoder/api/__main__.py deliberately: deploy/ is a separate toolchain
# that runs before the app's own venv (and thus transcoder package) exists,
# so it cannot import from solution/. See CLAUDE.md's solution-deploy-layout
# note on the two toolchains being separate.

def test_port_is_free_true_when_nothing_listens():
    # Extremely unlikely to have a real listener on this high port during tests.
    assert lib.port_is_free(58631) is True


def test_port_is_free_false_when_something_listens():
    import socket

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert lib.port_is_free(port) is False
    finally:
        srv.close()


def test_first_free_port_returns_start_when_free():
    assert lib.first_free_port(start=58631, limit=5) == 58631


def test_first_free_port_skips_occupied_ports():
    import socket

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert lib.first_free_port(start=port, limit=5) != port
    finally:
        srv.close()


def test_first_free_port_returns_none_when_all_taken(monkeypatch):
    monkeypatch.setattr(lib, "port_is_free", lambda port, host="127.0.0.1": False)
    assert lib.first_free_port(start=8765, limit=20) is None


# --- upsert_env_var -----------------------------------------------------

def test_upsert_env_var_empty_content_produces_one_line():
    assert lib.upsert_env_var("", "API_PORT", "8765") == "API_PORT=8765\n"


def test_upsert_env_var_replaces_existing_key_in_place():
    text = "SONARR_API_KEY=abc\nAPI_PORT=8765\nRADARR_API_KEY=def\n"
    got = lib.upsert_env_var(text, "API_PORT", "9000")
    lines = got.splitlines()
    assert lines == ["SONARR_API_KEY=abc", "API_PORT=9000", "RADARR_API_KEY=def"]


def test_upsert_env_var_preserves_unrelated_lines_byte_for_byte():
    text = "# a comment\nSONARR_API_KEY=abc\n\nSFTP_PASSWORD=hunter2\n"
    got = lib.upsert_env_var(text, "API_PORT", "8765")
    for line in ["# a comment", "SONARR_API_KEY=abc", "", "SFTP_PASSWORD=hunter2"]:
        assert line in got.splitlines()


def test_upsert_env_var_no_trailing_newline_does_not_join_lines():
    text = "SONARR_API_KEY=abc"
    got = lib.upsert_env_var(text, "API_PORT", "8765")
    lines = got.splitlines()
    assert lines == ["SONARR_API_KEY=abc", "API_PORT=8765"]


def test_upsert_env_var_commented_out_key_is_not_replaced():
    text = "#API_PORT=9000\n"
    got = lib.upsert_env_var(text, "API_PORT", "8765")
    lines = got.splitlines()
    assert "#API_PORT=9000" in lines
    assert "API_PORT=8765" in lines
    assert len(lines) == 2


def test_upsert_env_var_recognises_key_with_surrounding_whitespace():
    text = "  API_PORT = 8765  \n"
    got = lib.upsert_env_var(text, "API_PORT", "9000")
    lines = got.splitlines()
    assert lines == ["API_PORT=9000"]


def test_upsert_env_var_preserves_crlf_line_endings():
    text = "SONARR_API_KEY=abc\r\nAPI_PORT=8765\r\n"
    got = lib.upsert_env_var(text, "API_PORT", "9000")
    assert got == "SONARR_API_KEY=abc\r\nAPI_PORT=9000\r\n"


def test_upsert_env_var_crlf_content_appends_new_key_with_crlf():
    text = "SONARR_API_KEY=abc\r\n"
    got = lib.upsert_env_var(text, "API_PORT", "8765")
    assert got == "SONARR_API_KEY=abc\r\nAPI_PORT=8765\r\n"


def test_upsert_env_var_duplicate_key_replaces_first_and_drops_rest():
    # Decision: on a duplicate key, keep the FIRST occurrence's position (so
    # unrelated surrounding lines keep their order) and drop later duplicates,
    # rather than leaving two live (ambiguous) or appending a third.
    text = "API_PORT=1111\nSONARR_API_KEY=abc\nAPI_PORT=2222\n"
    got = lib.upsert_env_var(text, "API_PORT", "9000")
    lines = got.splitlines()
    assert lines == ["API_PORT=9000", "SONARR_API_KEY=abc"]
