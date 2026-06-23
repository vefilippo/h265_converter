import logging
import pathlib


def test_init_logging_api_creates_fixed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from transcoder.logging_setup import init_logging
    # Reset root logger so basicConfig actually runs in this test
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    logger = init_logging("api")
    log_file = tmp_path / "log" / "api.log"
    assert log_file.exists(), f"expected {log_file} to exist"
    # No dated filename pattern
    dated = list((tmp_path / "log").glob("????-??-??_??-??-??.log"))
    assert dated == [], f"unexpected dated log files: {dated}"


def test_init_logging_cli_creates_fixed_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from transcoder.logging_setup import init_logging
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    logger = init_logging("cli")
    log_file = tmp_path / "log" / "cli.log"
    assert log_file.exists(), f"expected {log_file} to exist"
