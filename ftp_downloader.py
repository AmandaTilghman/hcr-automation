"""
SFTP Downloader
===============
Connects to SFTP server and downloads the latest WAV file.
Supports LAN/WAN fallback — tries primary host first, then fallback.
"""

import fnmatch
import logging
import stat
from pathlib import Path

import paramiko

logger = logging.getLogger("radio-automation.sftp")


def _connect_sftp(host: str, port: int, username: str, password: str,
                  timeout: int = 10) -> tuple:
    """
    Attempt to connect to an SFTP server.
    Returns (SSHClient, SFTPClient) tuple.
    """
    logger.info(f"Trying SFTP connection: {host}:{port}")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        timeout=timeout,
    )
    sftp = ssh.open_sftp()
    logger.info(f"Connected to {host}")
    return ssh, sftp


def connect_with_fallback(ftp_config: dict) -> tuple:
    """
    Try primary host first, fall back to secondary if it fails.
    Returns (SSHClient, SFTPClient) tuple.
    """
    host = ftp_config["host"]
    port = ftp_config.get("port", 22)
    fallback = ftp_config.get("host_fallback", "")
    fallback_port = ftp_config.get("port_fallback", port)
    username = ftp_config["username"]
    password = ftp_config["password"]

    # Try primary host
    try:
        return _connect_sftp(host, port, username, password)
    except Exception as e:
        logger.warning(f"Primary host {host}:{port} failed: {e}")

    # Try fallback if configured
    if fallback:
        try:
            return _connect_sftp(fallback, fallback_port, username, password)
        except Exception as e:
            logger.error(f"Fallback host {fallback}:{fallback_port} also failed: {e}")
            raise ConnectionError(
                f"Could not connect to SFTP. "
                f"Tried {host}:{port} and {fallback}:{fallback_port} — both failed."
            )

    raise ConnectionError(f"Could not connect to SFTP at {host}")


def download_audio(ftp_config: dict, download_dir: str) -> Path:
    """
    Connect to SFTP (with LAN/WAN fallback), find the newest matching
    audio file, and download it.
    Returns the local path to the downloaded file.

    Raises Exception on failure.
    """
    remote_dir = ftp_config.get("remote_dir", "/")
    pattern = ftp_config.get("filename_pattern", "*.wav")

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    ssh, sftp = connect_with_fallback(ftp_config)

    try:
        sftp.chdir(remote_dir)
        logger.debug(f"Changed to directory: {remote_dir}")

        # List files and filter by pattern
        entries = sftp.listdir_attr()
        matching_files = []
        for entry in entries:
            if stat.S_ISDIR(entry.st_mode):
                continue
            if fnmatch.fnmatch(entry.filename.lower(), pattern.lower()):
                matching_files.append(entry)

        if not matching_files:
            raise FileNotFoundError(
                f"No files matching '{pattern}' found in {remote_dir}"
            )

        # Sort by modification time — newest first
        matching_files.sort(key=lambda e: e.st_mtime, reverse=True)
        target = matching_files[0]
        target_file = target.filename

        local_path = download_path / target_file

        # Skip if already downloaded and same size
        if local_path.exists():
            if local_path.stat().st_size == target.st_size:
                logger.info(f"File already downloaded: {target_file}")
                return local_path

        # Download
        logger.info(f"Downloading: {target_file} ({target.st_size} bytes)")
        sftp.get(f"{remote_dir}/{target_file}", str(local_path))

        logger.info(f"Downloaded {local_path.stat().st_size} bytes → {local_path}")
        return local_path

    finally:
        sftp.close()
        ssh.close()
