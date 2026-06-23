from transcoder.convert import parse_handbrake_progress


def test_parse_progress_matches():
    line = "Encoding: task 1 of 1, 42.13 %"
    assert parse_handbrake_progress(line) == 42


def test_parse_progress_none_for_other_lines():
    assert parse_handbrake_progress("Scanning title 1...") is None
    assert parse_handbrake_progress("") is None
