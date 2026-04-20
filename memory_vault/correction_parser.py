"""
memory_vault/correction_parser.py
───────────────────────────────────
Parses memory correction commands into structured MemoryAction objects.

Called when JARVIS detects a memory-related command in the user's message.
The correction_parser classifies the command type and extracts the relevant
entity so that the gateway can dispatch the correct memory operation.

Command Examples:
  "Jarvis, forget that I use Tailwind CSS."         → FORGET, entity="Tailwind CSS"
  "Jarvis, remember that I now prefer TypeScript."   → REMEMBER, entity="TypeScript"
  "Jarvis, what do you know about me?"              → SHOW_PROFILE
  "Jarvis, clear everything from last Tuesday."     → CLEAR_DATE, entity="Tuesday"
  "Jarvis, do not learn from the next 10 minutes."  → PAUSE_LEARNING, minutes=10
  "Jarvis, show me my coding wiki."                 → SHOW_WIKI, entity="coding_style"
  "Jarvis, show me my user profile."                → SHOW_WIKI, entity="user_profile"
"""

import re
import logging
from dataclasses import dataclass, field
from typing import Optional, Literal
from datetime import date, timedelta

logger = logging.getLogger(__name__)

MemoryActionType = Literal[
    "FORGET",
    "REMEMBER",
    "SHOW_PROFILE",
    "SHOW_WIKI",
    "CLEAR_DATE",
    "PAUSE_LEARNING",
    "UNKNOWN",
]

WIKI_KEYWORD_TO_FILE = {
    "coding": "coding_style",
    "code": "coding_style",
    "projects": "projects",
    "project": "projects",
    "shopping": "shopping_patterns",
    "shop": "shopping_patterns",
    "daily": "daily_patterns",
    "routine": "daily_patterns",
    "schedule": "daily_patterns",
    "profile": "user_profile",
    "user": "user_profile",
    "corrections": "corrections",
    "correction": "corrections",
}

DAY_NAME_TO_OFFSET = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    "yesterday": -1, "today": 0,
}


@dataclass
class MemoryAction:
    """Structured representation of a memory correction command."""
    action_type: MemoryActionType
    raw_command: str
    entity: str = ""                    # The thing to forget/remember/show
    wiki_file: str = ""                 # For SHOW_WIKI actions
    pause_minutes: int = 0              # For PAUSE_LEARNING actions
    target_date: Optional[str] = None  # For CLEAR_DATE actions (YYYY-MM-DD)
    confidence: float = 0.9

    @property
    def is_destructive(self) -> bool:
        """Return True if this action deletes or invalidates memory."""
        return self.action_type in ("FORGET", "CLEAR_DATE")


def parse_correction_command(command: str) -> MemoryAction:
    """
    Parse a natural language memory correction command.

    Args:
        command: The user's raw message text.

    Returns:
        MemoryAction with the parsed action type and parameters.
    """
    text = command.lower().strip()

    # ── FORGET ────────────────────────────────────────────────────────────────
    patterns_forget = [
        r"forget (?:that )?(?:i )?(?:use |like |prefer |am )?(.+?)[\.!]?$",
        r"stop remembering (?:that )?(.+?)[\.!]?$",
        r"don't remember (?:that )?(.+?)[\.!]?$",
        r"remove (?:that )?(?:i )?(?:use |like |prefer )?(.+?) from (?:your )?memory",
    ]
    for pattern in patterns_forget:
        match = re.search(pattern, text)
        if match:
            entity = match.group(1).strip().rstrip(".,!")
            return MemoryAction(
                action_type="FORGET",
                raw_command=command,
                entity=entity,
                confidence=0.95,
            )

    # ── REMEMBER ──────────────────────────────────────────────────────────────
    patterns_remember = [
        r"remember (?:that )?(?:i (?:now )?)?(?:use |like |prefer |am )?(.+?)[\.!]?$",
        r"note (?:that )?(?:i )?(?:now )?(?:prefer |use |like )?(.+?)[\.!]?$",
        r"update (?:your )?memory[,:] (?:i )?(?:now )?(?:prefer |use |like )?(.+?)[\.!]?$",
        r"(?:i )?(?:now )?prefer (.+?)[\.!]?$",
    ]
    for pattern in patterns_remember:
        match = re.search(pattern, text)
        if match:
            entity = match.group(1).strip().rstrip(".,!")
            return MemoryAction(
                action_type="REMEMBER",
                raw_command=command,
                entity=entity,
                confidence=0.95,
            )

    # ── SHOW PROFILE ──────────────────────────────────────────────────────────
    if any(phrase in text for phrase in [
        "what do you know about me",
        "what have you learned about me",
        "show me what you know",
        "tell me what you know about me",
        "what's in my profile",
    ]):
        return MemoryAction(
            action_type="SHOW_PROFILE",
            raw_command=command,
            confidence=0.98,
        )

    # ── SHOW WIKI ─────────────────────────────────────────────────────────────
    wiki_match = re.search(r"show (?:me )?(?:my )?(.+?) wiki", text)
    if wiki_match:
        keyword = wiki_match.group(1).lower().replace(" ", "_")
        wiki_file = WIKI_KEYWORD_TO_FILE.get(keyword, "user_profile")
        # Handle "user profile" manually as well
        if "user profile" in keyword:
            wiki_file = "user_profile"
        return MemoryAction(
            action_type="SHOW_WIKI",
            raw_command=command,
            wiki_file=wiki_file,
            confidence=0.95,
        )

    # ── CLEAR DATE ────────────────────────────────────────────────────────────
    clear_match = re.search(
        r"clear (?:everything|all) (?:you (?:learned|know) )?from (?:last )?(\w+)",
        text
    )
    if clear_match:
        day_word = clear_match.group(1).lower()
        target_date = _resolve_day_name(day_word)
        return MemoryAction(
            action_type="CLEAR_DATE",
            raw_command=command,
            target_date=target_date,
            confidence=0.9,
        )

    # ── PAUSE LEARNING ────────────────────────────────────────────────────────
    pause_match = re.search(
        r"(?:do not|don't|stop) learn(?:ing)? (?:from )?(?:the next )?(\d+) minute",
        text
    )
    if pause_match:
        minutes = int(pause_match.group(1))
        return MemoryAction(
            action_type="PAUSE_LEARNING",
            raw_command=command,
            pause_minutes=minutes,
            confidence=0.9,
        )

    # ── UNKNOWN ───────────────────────────────────────────────────────────────
    return MemoryAction(
        action_type="UNKNOWN",
        raw_command=command,
        confidence=0.0,
    )


def _resolve_day_name(day_word: str) -> str:
    """
    Resolve a day name like "Tuesday" or "yesterday" to a YYYY-MM-DD string.

    Args:
        day_word: Day name or relative term.

    Returns:
        ISO date string, or empty string if unresolvable.
    """
    today = date.today()

    if day_word == "yesterday":
        return (today - timedelta(days=1)).isoformat()
    if day_word == "today":
        return today.isoformat()

    # Try to find the most recent occurrence of the named weekday
    target_weekday = DAY_NAME_TO_OFFSET.get(day_word)
    if target_weekday is None:
        # Might be a date string like "2026-04-14"
        try:
            return date.fromisoformat(day_word).isoformat()
        except ValueError:
            return ""

    current_weekday = today.weekday()  # Monday=0, Sunday=6
    days_back = (current_weekday - target_weekday) % 7
    if days_back == 0:
        days_back = 7  # If today is Tuesday and user says Tuesday, go back a week
    target = today - timedelta(days=days_back)
    return target.isoformat()
