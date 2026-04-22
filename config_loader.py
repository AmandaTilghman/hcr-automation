"""Load and validate configuration."""

import os
import sys
from pathlib import Path

import yaml


def load_config(config_path: str = None) -> dict:
    """
    Load config from YAML file. Checks for:
    1. Explicit path argument
    2. CONFIG_PATH environment variable
    3. config.yaml in the script directory
    """
    if config_path is None:
        config_path = os.environ.get(
            "RADIO_CONFIG_PATH",
            str(Path(__file__).parent / "config.yaml")
        )

    config_file = Path(config_path)
    if not config_file.exists():
        print(f"Error: Config file not found: {config_file}")
        print("Copy config.example.yaml to config.yaml and fill in your values.")
        sys.exit(1)

    with open(config_file, "r") as f:
        config = yaml.safe_load(f)

    # Resolve relative paths against config file location
    base_dir = config_file.parent
    paths = config.get("paths", {})
    for key in ("download_dir", "output_dir", "processed_log"):
        if key in paths and not Path(paths[key]).is_absolute():
            paths[key] = str(base_dir / paths[key])

    # Resolve log file path too
    log_cfg = config.get("logging", {})
    if "file" in log_cfg and not Path(log_cfg["file"]).is_absolute():
        log_cfg["file"] = str(base_dir / log_cfg["file"])

    return config
