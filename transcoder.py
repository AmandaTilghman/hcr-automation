"""
Audio Transcoder
================
Converts WAV files to MP2 using FFmpeg.
Works on Mac, Windows, and Linux — just needs FFmpeg installed.
"""

import subprocess
import shutil
import logging
from pathlib import Path

logger = logging.getLogger("radio-automation.transcode")


def check_ffmpeg() -> str:
    """Find ffmpeg binary. Raises if not found."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "FFmpeg not found! Install it:\n"
            "  Mac:     brew install ffmpeg\n"
            "  Windows: winget install ffmpeg  (or download from ffmpeg.org)\n"
            "  Linux:   sudo apt install ffmpeg"
        )
    return ffmpeg


def transcode_wav_to_mp2(
    input_path: Path | str,
    output_dir: str,
    config: dict,
) -> Path:
    """
    Transcode a WAV file to MP2.

    Args:
        input_path: Path to the input WAV file
        output_dir: Directory for output files
        config: Transcode config (sample_rate, bitrate, etc.)

    Returns:
        Path to the output MP2 file

    Raises:
        RuntimeError: If FFmpeg is not found or transcode fails
    """
    ffmpeg = check_ffmpeg()
    input_path = Path(input_path)
    output_path = Path(output_dir) / f"{input_path.stem}.mp2"

    sample_rate = config.get("sample_rate", 44100)
    bitrate = config.get("bitrate", "384k")

    # Build FFmpeg command
    cmd = [
        ffmpeg,
        "-y",                       # Overwrite output
        "-i", str(input_path),      # Input file
        "-codec:a", "mp2",          # MP2 audio codec
        "-ar", str(sample_rate),    # Sample rate
        "-b:a", str(bitrate),       # Audio bitrate
        "-ac", "2",                 # Stereo (standard for broadcast)
        str(output_path),
    ]

    logger.info(f"Transcoding: {input_path.name} → {output_path.name}")
    logger.debug(f"Command: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=600,  # 10 min timeout for large files
    )

    if result.returncode != 0:
        logger.error(f"FFmpeg stderr:\n{result.stderr}")
        raise RuntimeError(
            f"FFmpeg failed with exit code {result.returncode}:\n{result.stderr[-500:]}"
        )

    if not output_path.exists():
        raise RuntimeError(f"Output file not created: {output_path}")

    input_size = input_path.stat().st_size / (1024 * 1024)
    output_size = output_path.stat().st_size / (1024 * 1024)
    logger.info(
        f"Transcode complete: {input_size:.1f} MB → {output_size:.1f} MB "
        f"({sample_rate} Hz, {bitrate})"
    )

    return output_path
