"""
Processing State
================
Tracks which emails/files have been processed to avoid duplicates.
Uses a simple JSON file as persistent storage.
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger("radio-automation.state")


class ProcessingState:
    """Track processed items in a JSON file."""

    def __init__(self, state_file: str):
        self.state_file = Path(state_file)
        self.data = self._load()

    def _load(self) -> dict:
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Could not load state file: {e}")
        return {"processed": {}}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(self.data, f, indent=2)

    def is_processed(self, email_id: str) -> bool:
        return email_id in self.data.get("processed", {})

    def mark_processed(self, email_id: str, details: dict = None):
        if "processed" not in self.data:
            self.data["processed"] = {}

        self.data["processed"][email_id] = {
            "timestamp": datetime.utcnow().isoformat(),
            **(details or {}),
        }
        self._save()
        logger.info(f"Marked as processed: {email_id}")

    def get_history(self, limit: int = 20) -> list:
        """Return recent processing history."""
        items = list(self.data.get("processed", {}).items())
        items.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
        return items[:limit]
