"""
J.A.R.V.I.S. — memory_vault/distiller.py
Nightly memory distillation job using APScheduler. Full activation in Phase 4.

Runs at 2:00 AM daily. Reads daily conversation logs, passes them to the
memory_distiller agent, and stores extracted facts in ChromaDB.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_LOGS_DIR = Path(__file__).parent / "logs"


class MemoryDistiller:
    """
    Nightly memory distillation scheduler.

    Phase 1 stub: the job is scheduled but logs a placeholder message.
    Phase 4 will activate full ChromaDB fact extraction.
    """

    def __init__(self) -> None:
        """Initialise the distiller and attempt to start APScheduler."""
        self._scheduler = None
        self._try_start_scheduler()

    def _try_start_scheduler(self) -> None:
        """
        Initialise APScheduler and schedule the nightly 2 AM distillation job.

        Warns gracefully if APScheduler is not installed.
        """
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            self._scheduler = BackgroundScheduler()
            self._scheduler.add_job(
                func=self._run_distillation,
                trigger="cron",
                hour=2,
                minute=0,
                id="nightly_distillation",
                name="JARVIS Nightly Memory Distillation",
            )
            self._scheduler.start()
            logger.info(
                "Memory distiller scheduled — nightly at 02:00 AM "
                "(Phase 4 will activate full extraction)."
            )
        except ImportError:
            logger.warning(
                "APScheduler not installed — nightly distillation job not scheduled. "
                "Install with: pip install APScheduler"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to start distillation scheduler: %s", exc)

    def _run_distillation(self) -> None:
        """
        Execute the nightly distillation job.

        Phase 1: logs placeholder message.
        Phase 4: reads today's log file, calls memory_distiller agent,
                 stores facts in ChromaDB.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = _LOGS_DIR / f"{today}.log"

        logger.info("Distillation job triggered for date: %s", today)

        if not log_file.exists():
            logger.info("No conversation log found for %s — nothing to distill.", today)
            return

        # Phase 1 stub message
        logger.info(
            "Distillation job triggered — awaiting Phase 4 implementation. "
            "Log file: %s",
            log_file,
        )
        print(
            f"[JARVIS Memory Distiller]: Would process {log_file} — "
            "Phase 4 will activate full ChromaDB extraction."
        )

    def shutdown(self) -> None:
        """Gracefully shut down the APScheduler."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Memory distillation scheduler shut down.")
