"""
J.A.R.V.I.S. — core_engine/agent_registry.py
JSON-driven agent loader. Adding new agents requires ZERO code changes —
only an addition to agents.json.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Path resolution: agents.json lives in the same directory as this file
_AGENTS_JSON_PATH = Path(__file__).parent / "agents.json"
_JARVIS_CORE_PATH = Path(__file__).parent.parent / "JARVIS_CORE.md"


class AgentRegistry:
    """
    Expandable, JSON-driven agent registry.

    Loads all agent definitions from agents.json. Agents are indexed by name
    for O(1) lookup. Supports hot-reload without server restart.
    """

    def __init__(self) -> None:
        """Load and validate all agent definitions from agents.json."""
        self._agents: dict[str, dict] = {}
        self._jarvis_core_content: str = ""
        self._load_jarvis_core()
        self.reload()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_jarvis_core(self) -> None:
        """
        Read JARVIS_CORE.md into memory.

        This content is prepended to EVERY agent system prompt so Ollama
        can KV-cache it after the first request.
        """
        try:
            self._jarvis_core_content = _JARVIS_CORE_PATH.read_text(encoding="utf-8")
            logger.info("JARVIS_CORE.md loaded — %d characters.", len(self._jarvis_core_content))
        except FileNotFoundError:
            logger.error(
                "JARVIS_CORE.md not found at %s. Agents will operate without core identity.",
                _JARVIS_CORE_PATH,
            )
            self._jarvis_core_content = "# JARVIS_CORE.md missing — please restore this file.\n"

    def _validate_agent(self, agent: dict) -> bool:
        """
        Validate that a single agent dict has all required fields.

        Args:
            agent: Raw agent definition dict from JSON.

        Returns:
            True if valid, False otherwise.
        """
        required = {
            "name", "model_offline", "model_online",
            "system_prompt_file", "trigger_keywords", "enabled",
        }
        missing = required - set(agent.keys())
        if missing:
            logger.warning("Agent '%s' missing required fields: %s", agent.get("name", "?"), missing)
            return False
        return True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reload(self) -> int:
        """
        Re-read agents.json from disk without requiring a server restart.

        Returns:
            Count of successfully loaded agents.
        """
        try:
            raw = _AGENTS_JSON_PATH.read_text(encoding="utf-8")
            agents_list: list[dict] = json.loads(raw)
        except FileNotFoundError:
            logger.error("agents.json not found at %s.", _AGENTS_JSON_PATH)
            return 0
        except json.JSONDecodeError as exc:
            logger.error("agents.json is malformed: %s", exc)
            return 0

        new_registry: dict[str, dict] = {}
        for agent in agents_list:
            if self._validate_agent(agent):
                new_registry[agent["name"]] = agent

        self._agents = new_registry
        logger.info("AgentRegistry loaded %d agents.", len(self._agents))
        return len(self._agents)

    def get_agent(self, name: str) -> Optional[dict]:
        """
        Retrieve an agent definition by exact name.

        Args:
            name: Agent name string (e.g. "receptionist", "code_specialist").

        Returns:
            Agent definition dict, or None if not found.
        """
        return self._agents.get(name)

    def get_agent_for_intent(self, intent_keywords: list[str]) -> dict:
        """
        Find the best-matching enabled agent using trigger_keyword overlap.

        Args:
            intent_keywords: List of keywords extracted from the user's message.

        Returns:
            Best-matching agent dict, or the receptionist as fallback.
        """
        best_agent: Optional[dict] = None
        best_score = -1

        for agent in self._agents.values():
            if not agent.get("enabled", True):
                continue
            overlap = sum(
                1 for kw in intent_keywords
                if any(kw.lower() in trigger.lower() for trigger in agent.get("trigger_keywords", []))
            )
            if overlap > best_score:
                best_score = overlap
                best_agent = agent

        if best_agent is None or best_score == 0:
            return self._agents.get("receptionist", list(self._agents.values())[0])
        return best_agent

    def list_agents(self, enabled_only: bool = True) -> list[dict]:
        """
        Return all agent definitions, optionally filtered to enabled ones.

        Args:
            enabled_only: If True, return only agents where enabled == True.

        Returns:
            List of agent definition dicts.
        """
        agents = list(self._agents.values())
        if enabled_only:
            agents = [a for a in agents if a.get("enabled", True)]
        return agents

    def get_system_prompt(self, agent_name: str) -> str:
        """
        Build the full system prompt for an agent.

        Prepends JARVIS_CORE.md to the agent's specific prompt file content.
        JARVIS_CORE.md is ALWAYS first — this enables Ollama KV-caching.

        Args:
            agent_name: Name of the agent.

        Returns:
            Combined system prompt string: JARVIS_CORE.md + agent-specific content.
        """
        agent = self._agents.get(agent_name)
        if agent is None:
            logger.warning("get_system_prompt called for unknown agent '%s'.", agent_name)
            return self._jarvis_core_content

        prompt_file_rel = agent.get("system_prompt_file", "")
        # Resolve relative to project root (two levels up from core_engine/)
        project_root = Path(__file__).parent.parent
        prompt_path = project_root / prompt_file_rel

        agent_prompt = ""
        try:
            agent_prompt = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning(
                "System prompt file '%s' not found for agent '%s'. Using JARVIS_CORE.md only.",
                prompt_path,
                agent_name,
            )
        except Exception as exc:
            logger.error("Error reading prompt file for '%s': %s", agent_name, exc)

        # JARVIS_CORE.md is ALWAYS prepended first
        separator = "\n\n---\n\n"
        if agent_prompt:
            return self._jarvis_core_content + separator + agent_prompt
        return self._jarvis_core_content

    @property
    def agent_count(self) -> int:
        """Return the number of currently loaded agents."""
        return len(self._agents)

    @property
    def jarvis_core_content(self) -> str:
        """Return the cached JARVIS_CORE.md content."""
        return self._jarvis_core_content
