import socket

import pytest


def test_port_is_free_reports_false_when_something_is_listening():
    from transcoder.api.__main__ import port_is_free

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(1)
    port = s.getsockname()[1]
    try:
        assert port_is_free("127.0.0.1", port) is False
    finally:
        s.close()


def test_port_is_free_reports_true_for_an_unused_port():
    from transcoder.api.__main__ import port_is_free

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()  # now free
    assert port_is_free("127.0.0.1", port) is True


def test_main_exits_with_a_clear_message_when_the_port_is_taken(monkeypatch, capsys):
    """Must NOT start uvicorn: a server nobody can reach is worse than a
    refusal, because the browser then shows whatever else owns the port."""
    import transcoder.api.__main__ as m

    started = []
    monkeypatch.setattr(m.uvicorn, "run", lambda *a, **k: started.append(True))
    monkeypatch.setattr(m, "port_is_free", lambda host, port: False)
    with pytest.raises(SystemExit) as exc:
        m.main()
    assert exc.value.code != 0
    assert not started
    out = capsys.readouterr()
    assert str(m.settings.API_PORT) in (out.out + out.err)
