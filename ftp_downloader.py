"""
FTP Downloader
==============
Connects to FTP server and downloads the latest WAV file.
Supports LAN/WAN fallback — tries primary host first, then fallback.
"""

import ftplib
import fnmatch
import logging
from pathlib import Path

logger = logging.getLogger("radio-automation.ftp")


def _connect_ftp(host: str, port: int, username: str, password: str,
                 timeout: int = 10) -> ftplib.FTP:
    """Attempt to connect and login to an FTP server."""
    logger.info(f"Trying FTP connection: {host}:{port}")
    ftp = ftplib.FTP()
    ftp.connect(host, port, timeout=timeout)
    ftp.login(username, password)
    logger.info(f"Connected to {host}")
    return ftp


def connect_with_fallback(ftp_config: dict) -> ftplib.FTP:
    """
    Try primary host first, fall back to secondary if it fails.
    """
    host = ftp_config["host"]
    fallback = ftp_config.get("host_fallback", "")
    port = ftp_config.get("port", 21)
    username = ftp_config["username"]
    password = ftp_config["password"]

    # Try primary host
    try:
        return _connect_ftp(host, port, username, password)
    except Exception as e:
        logger.warning(f"Primary host {host} failed: {e}")

    # Try fallback if configured
    if fallback:
        try:
            return _connect_ftp(fallback, port, username, password)
        except Exception as e:
            logger.error(f"Fallback host {fallback} also failed: {e}")
            raise ConnectionError(
                f"Could not connect to FTP. "
                f"Tried {host} and {fallback} — both failed."
            )

    raise ConnectionError(f"Could not connect to FTP at {host}")


def download_audio(ftp_config: dict, download_dir: str) -> Path:
    """
    Connect to FTP (with LAN/WAN fallback), find the newest matching
    audio file, and download it.
    Returns the local path to the downloaded file.

    Raises Exception on failure.
    """
    remote_dir = ftp_config.get("remote_dir", "/")
    pattern = ftp_config.get("filename_pattern", "*.wav")

    download_path = Path(download_dir)
    download_path.mkdir(parents=True, exist_ok=True)

    ftp = connect_with_fallback(ftp_config)

    try:
        ftp.cwd(remote_dir)
        logger.debug(f"Changed to directory: {remote_dir}")

        # List files and filter by pattern
        files = []
        ftp.retrlines("LIST", lambda line: files.append(line))

        matching_files = []
        for line in files:
            parts = line.split()
            if not parts:
                continue
            filename = parts[-1]
            if fnmatch.fnmatch(filename.lower(), pattern.lower()):
                matching_files.append({
                    "name": filename,
                    "line": line,
                })

        if not matching_files:
            raise FileNotFoundError(
                f"No files matching '{pattern}' found in {remote_dir}"
            )

        # Try to sort by modification time if available via MLSD
        try:
            mlsd_entries = list(ftp.mlsd(facts=["modify"]))
            mlsd_matching = [
                (name, facts.get("modify", ""))
                for name, facts in mlsd_entries
                if fnmatch.fnmatch(name.lower(), pattern.lower())
            ]
            if mlsd_matching:
                mlsd_matching.sort(key=lambda x: x[1], reverse=True)
                target_file = mlsd_matching[0][0]
            else:
                target_file = matching_files[-1]["name"]
        except Exception:
            # MLSD not supported, fall back to last file in listing
            target_file = matching_files[-1]["name"]

        local_path = download_path / target_file

        # Skip if already downloaded
        if local_path.exists():
            remote_size = ftp.size(target_file)
            if remote_size and local_path.stat().st_size == remote_size:
                logger.info(f"File already downloaded: {target_file}")
                return local_path

        # Download
        logger.info(f"Downloading: {target_file}")
        with open(local_path, "wb") as f:
            ftp.retrbinary(f"RETR {target_file}", f.write)

        logger.info(f"Downloaded {local_path.stat().st_size} bytes → {local_path}")
        return local_path

    finally:
        ftp.quit()
