from transcoder import restore


def test_relaunch_argv_runs_api_module():
    argv = restore.relaunch_argv(r"C:\app\.venv\Scripts\pythonw.exe", r"C:\app")
    assert argv[0].endswith("pythonw.exe")
    assert argv[1:] == ["-m", "transcoder.api"]


def test_waiter_script_compiles_even_with_quote_in_path():
    # repr-serialized paths must produce syntactically valid Python source,
    # even when a path contains a single quote or backslashes.
    src = restore._waiter_script(r"C:\a b\py's\python.exe", r"C:\pkg's dir", 8765)
    compile(src, "<waiter>", "exec")  # raises SyntaxError if the fix regresses
