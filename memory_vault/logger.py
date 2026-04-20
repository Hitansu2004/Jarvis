"""
memory_vault/logger.py
───────────────────────
Conversation logger for JARVIS — writes raw conversation to daily log files.

Every conversation turn (user message + JARVIS response) is appended to:
  memory_vault/logs/YYYY-MM-DD.log

These logs are the input to the nightly distillation job.
Logs are NEVER injected into prompts directly — they are too raw and too long.
Only the distilled facts from these logs get injected (via ChromaDB/Graphiti/Wiki).

Passive screen observations are also appended to the same log file
(prefixed with [SCREEN]) so the distiller can extract style/habit facts.
"""

import os
import logging
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOG_DIR = Path("./memory_vault/logs")
PASSIVE_LEARNING_ENABLED = os.getenv("PASSIVE_LEARNING_ENABLED", "true").lower() == "true"


class ConversationLogger:
    """
    Appends conversation turns and screen observations to daily log files.

    Thread-safe via file append mode (OS-level atomic appends on most systems).
    Each log entry is newline-terminated and timestamped.
    """

    def __init__(self):
        LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _get_log_file(self, log_date: Optional[date] = None) -> Path:
        """Return the path to the log file for the given date (defaults to today)."""
        log_date = log_date or date.today()
        return LOG_DIR / f"{log_date.isoformat()}.log"

    def log_conversation(
        self,
        user_message: str,
        jarvis_response: str,
        agent_used: str = "unknown",
        model_used: str = "unknown",
    ) -> None:
        """
        Append a conversation turn to today's log.

        Args:
            user_message:    The user's input text.
            jarvis_response: JARVIS's response text.
            agent_used:      Which agent handled this turn.
            model_used:      Which model was used.
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_file = self._get_log_file()

        entry = (
            f"[{timestamp}] [AGENT:{agent_used}] [MODEL:{model_used}]\n"
            f"USER: {user_message.strip()}\n"
            f"JARVIS: {jarvis_response.strip()}\n"
            f"---\n"
        )

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.error(f"ConversationLogger: failed to write log entry: {e}")

    def log_screen_observation(self, observation: str, source: str = "passive_watcher") -> None:
        """
        Append a screen observation to today's log.

        Args:
            observation: Text description of what was observed on screen.
            source:      Which component generated this observation.
        """
        if not PASSIVE_LEARNING_ENABLED:
            return

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log_file = self._get_log_file()

        entry = (
            f"[{timestamp}] [SCREEN] [{source}]\n"
            f"OBSERVATION: {observation.strip()}\n"
            f"---\n"
        )

        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.error(f"ConversationLogger: failed to write screen observation: {e}")

    def get_log_size_mb(self, log_date: Optional[date] = None) -> float:
        """Return the size of the given date's log file in megabytes."""
        log_file = self._get_log_file(log_date)
        if not log_file.exists():
            return 0.0
        return log_file.stat().st_size / (1024 * 1024)

    def read_log(self, log_date: Optional[date] = None) -> str:
        """Read and return the full content of the given date's log file."""
        log_file = self._get_log_file(log_date)
        if not log_file.exists():
            return ""
        try:
            return log_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.error(f"ConversationLogger: failed to read log: {e}")
            return ""

    def list_log_files(self) -> list[dict]:
        """
        List all existing log files with their sizes and dates.

        Returns:
            List of dicts: [{date, filename, size_mb, is_distilled}]
        """
        results = []
        for log_file in sorted(LOG_DIR.glob("*.log")):
            if log_file.name.startswith("distillation_"):
                continue  # Skip distillation summary files
            size_mb = log_file.stat().st_size / (1024 * 1024)
            date_str = log_file.stem
            distillation_file = LOG_DIR / f"distillation_{date_str}.log"
            results.append({
                "date": date_str,
                "filename": log_file.name,
                "size_mb": round(size_mb, 3),
                "is_distilled": distillation_file.exists(),
            })
        return results
