import logging
import paramiko, os
from pathlib import Path
from tqdm import tqdm
from pathlib import PureWindowsPath

from transcoder.config import settings

log = logging.getLogger("transcoder")


class SftpClient:
    """Thin wrapper around the standalone SFTP helpers that accepts runtime-
    overridable connection parameters (DB settings take precedence over .env)."""

    def __init__(self, host=None, port=None, username=None, password=None):
        cfg = settings
        self.host = host or cfg.SFTP_HOST
        self.port = int(port) if port else cfg.SFTP_PORT
        self.username = username or cfg.SFTP_USERNAME
        self.password = password or cfg.SFTP_PASSWORD

    def upload(self, local_path, remote_path, progress_cb=None) -> dict:
        return upload_file_via_sftp(
            self.host, self.port, self.username, self.password,
            local_path, remote_path, progress_cb=progress_cb,
        )

    def download(self, remote_path, local_path, progress_cb=None) -> dict:
        return download_file_via_sftp(
            self.host, self.port, self.username, self.password,
            remote_path, local_path, progress_cb=progress_cb,
        )

def upload_file_via_sftp(host, port, username, password,
                         local_path, remote_path, progress_cb=None) -> dict:
                             
    p = PureWindowsPath(remote_path)
    remote_path = f"./{p.as_posix()}"

    log.info("Uploading file :%s", local_path)
    
    try:
        file_size = Path(local_path).stat().st_size
        progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc="Uploading")

        def progress_callback(transferred, total):
            progress_bar.n = transferred
            progress_bar.refresh()
            if progress_cb is not None and total:
                progress_cb(int(transferred / total * 100))

        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)

        sftp.put(local_path, remote_path, callback=progress_callback)

        progress_bar.close()
        sftp.close()
        transport.close()

        return {"success": True, "message": f"Uploaded to {remote_path}"}

    except Exception as e:
        return {"success": False, "message": str(e)}


def download_file_via_sftp(host, port, username, password,
                           remote_path, local_path, progress_cb=None) -> dict:
                               
    p = PureWindowsPath(remote_path)
    remote_path = f"./{p.as_posix()}"
    log.info("Downloading file :%s", remote_path)
    
    try:
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        file_size = sftp.stat(remote_path).st_size
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        progress_bar = tqdm(total=file_size, unit='B', unit_scale=True, desc="Downloading")

        def progress_callback(transferred, total):
            progress_bar.n = transferred
            progress_bar.refresh()
            if progress_cb is not None and total:
                progress_cb(int(transferred / total * 100))

        sftp.get(remote_path, local_path, callback=progress_callback)

        progress_bar.close()
        sftp.close()
        transport.close()

        return {"success": True, "message": f"Downloaded to {local_path}"}

    except Exception as e:
        log.error("%s", e)
        return {"success": False, "message": str(e)}
