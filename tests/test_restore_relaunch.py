from transcoder import restore


def test_relaunch_argv_runs_api_module():
    argv = restore.relaunch_argv(r"C:\app\.venv\Scripts\pythonw.exe", r"C:\app")
    assert argv[0].endswith("pythonw.exe")
    assert argv[1:] == ["-m", "transcoder.api"]
