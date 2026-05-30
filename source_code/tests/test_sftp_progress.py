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
