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
