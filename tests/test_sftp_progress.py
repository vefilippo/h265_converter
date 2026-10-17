import transcoder.sftp_client as sftp


class _FakeSFTP:
    def __init__(self, size): self._size = size
    def stat(self, remote):
        class S: st_size = self._size
        return S()
    def get(self, remote, local, callback=None):
        callback(0, self._size); callback(self._size // 2, self._size)
        callback(self._size, self._size)
    def put(self, local, remote, callback=None):
        callback(self._size, self._size)
    def close(self): pass


class _FakeTransport:
    def __init__(self, *a, **k): pass
    def connect(self, **k): pass
    def close(self): pass


def test_download_progress_cb_receives_percent(monkeypatch, tmp_path):
    monkeypatch.setattr(sftp.paramiko, "Transport", _FakeTransport)
    monkeypatch.setattr(sftp.paramiko.SFTPClient, "from_transport",
                        staticmethod(lambda t: _FakeSFTP(100)))
    monkeypatch.setattr(sftp.Path, "mkdir", lambda *a, **k: None)
    seen = []
    res = sftp.download_file_via_sftp(
        "h", 22, "u", "p", "/r/a.mkv", str(tmp_path / "a.mkv"),
        progress_cb=seen.append)
    assert res["success"] is True
    assert seen[-1] == 100 and 50 in seen


class _DeadPipe:
    """A stderr whose reader has gone away: Windows reports EINVAL on write."""
    def isatty(self): return False
    def write(self, s): raise OSError(22, "Invalid argument")
    def flush(self): raise OSError(22, "Invalid argument")


def _fake_sftp(monkeypatch):
    monkeypatch.setattr(sftp.paramiko, "Transport", _FakeTransport)
    monkeypatch.setattr(sftp.paramiko.SFTPClient, "from_transport",
                        staticmethod(lambda t: _FakeSFTP(100)))


def test_download_survives_a_dead_stderr(monkeypatch, tmp_path):
    _fake_sftp(monkeypatch)
    monkeypatch.setattr(sftp.sys, "stderr", _DeadPipe())
    res = sftp.download_file_via_sftp(
        "h", 22, "u", "p", "/r/a.mkv", str(tmp_path / "a.mkv"))
    assert res["success"] is True, res


def test_upload_survives_a_dead_stderr(monkeypatch, tmp_path):
    _fake_sftp(monkeypatch)
    monkeypatch.setattr(sftp.sys, "stderr", _DeadPipe())
    local = tmp_path / "a.mkv"
    local.write_bytes(b"x" * 100)
    res = sftp.upload_file_via_sftp("h", 22, "u", "p", str(local), "out/a.mkv")
    assert res["success"] is True, res


def test_download_survives_no_stderr(monkeypatch, tmp_path):
    # pythonw.exe launched without redirection has sys.stderr = None.
    _fake_sftp(monkeypatch)
    monkeypatch.setattr(sftp.sys, "stderr", None)
    res = sftp.download_file_via_sftp(
        "h", 22, "u", "p", "/r/a.mkv", str(tmp_path / "a.mkv"))
    assert res["success"] is True, res
