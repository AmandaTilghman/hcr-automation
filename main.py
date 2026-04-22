#!/usr/bin/env python3
"""
Radio Automation Pipeline
=========================
Monitors email for notifications, downloads audio from FTP,
transcodes WAV → MP2, and uploads/publishes to PRX.

Run via cron/Task Scheduler every 15 minutes during the afternoon window.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime

from config_loader import load_config
from email_watcher import check_for_notification
from ftp_downloader import download_audio
from transcoder import transcode_wav_to_mp2
from prx_uploader import PRXClient
from state import ProcessingState

def setup_logging(config: dict) -> logging.Logger:
    """Configure logging to file + console."""
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = log_cfg.get("file", "radio-automation.log")

    logger = logging.getLogger("radio-automation")
    logger.setLevel(level)

    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"
    ))
    logger.addHandler(ch)

    return logger


def is_within_schedule(config: dict) -> bool:
    """Check if current time is within the polling window."""
    try:
        import pytz
    except ImportError:
        # If pytz not installed, skip time check
        return True

    schedule = config.get("schedule", {})
    tz_name = schedule.get("timezone", "US/Eastern")
    start_hour = schedule.get("start_hour", 11)
    end_hour = schedule.get("end_hour", 20)

    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)
    current_hour = now.hour

    return start_hour <= current_hour < end_hour


def run_pipeline(config: dict, logger: logging.Logger) -> bool:
    """
    Execute the full pipeline. Returns True if a file was processed.
    """
    state = ProcessingState(config["paths"]["processed_log"])
    paths = config["paths"]

    # Ensure directories exist
    Path(paths["download_dir"]).mkdir(parents=True, exist_ok=True)
    Path(paths["output_dir"]).mkdir(parents=True, exist_ok=True)

    # --- Step 1: Check email ---
    logger.info("Checking email for new notifications...")
    notification = check_for_notification(config["email"])

    if notification is None:
        logger.info("No new notifications found. Done.")
        return False

    email_id = notification["email_id"]
    if state.is_processed(email_id):
        logger.info(f"Email {email_id} already processed. Skipping.")
        return False

    logger.info(f"Found notification: {notification['subject']}")

    # --- Step 2: Download from FTP ---
    logger.info("Connecting to FTP and downloading audio...")
    try:
        downloaded_file = download_audio(
            config["ftp"],
            download_dir=paths["download_dir"]
        )
    except Exception as e:
        logger.error(f"FTP download failed: {e}")
        return False

    logger.info(f"Downloaded: {downloaded_file}")

    # --- Step 3: Transcode WAV → MP2 ---
    logger.info("Transcoding WAV → MP2...")
    try:
        output_file = transcode_wav_to_mp2(
            input_path=downloaded_file,
            output_dir=paths["output_dir"],
            config=config["transcode"]
        )
    except Exception as e:
        logger.error(f"Transcode failed: {e}")
        return False

    logger.info(f"Transcoded: {output_file}")

    # --- Step 4: Upload to PRX ---
    logger.info("Uploading to PRX...")
    try:
        prx = PRXClient(config["prx"])
        prx.authenticate()

        # Extract metadata from email/filename
        metadata = extract_metadata(notification, downloaded_file)

        story_url = prx.create_and_upload_story(
            audio_path=output_file,
            title=metadata["title"],
            description=metadata.get("description", ""),
            tags=metadata.get("tags", []),
            publish=config["prx"].get("auto_publish", False)
        )
    except Exception as e:
        logger.error(f"PRX upload failed: {e}")
        return False

    logger.info(f"Published to PRX: {story_url}")

    # --- Step 5: Mark as processed ---
    state.mark_processed(email_id, {
        "subject": notification["subject"],
        "downloaded_file": str(downloaded_file),
        "output_file": str(output_file),
        "prx_url": story_url,
        "processed_at": datetime.utcnow().isoformat()
    })

    logger.info("Pipeline complete!")
    return True


def extract_metadata(notification: dict, audio_path: Path) -> dict:
    """
    Pull metadata from the email notification and filename.
    Customize this based on your email format.
    """
    # Default: use filename as title, strip extension
    title = Path(audio_path).stem.replace("_", " ").replace("-", " ").title()

    return {
        "title": title,
        "description": notification.get("body_preview", ""),
        "tags": [],  # Will be merged with defaults in PRX uploader
    }


def main():
    config = load_config()
    logger = setup_logging(config)

    logger.info("=" * 50)
    logger.info("Radio Automation Pipeline starting")

    # Check if we're in the schedule window
    if not is_within_schedule(config):
        logger.info("Outside scheduled hours. Exiting.")
        sys.exit(0)

    try:
        processed = run_pipeline(config, logger)
        sys.exit(0 if processed or True else 0)  # Always exit 0 unless error
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
