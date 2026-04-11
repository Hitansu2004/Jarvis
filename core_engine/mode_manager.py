"""
J.A.R.V.I.S. — core_engine/mode_manager.py
Dual-mode switching layer. ALL agents call through here —
never directly to Ollama or Vertex AI.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_instance: Optional["ModeManager"] = None


def get_mode_manager() -> "ModeManager":
    """
    Return the singleton ModeManager instance.

    Creates it on first call. Thread-safe for single-process FastAPI.

    Returns:
        The global ModeManager singleton.
    """
    global _instance
    if _instance is None:
        _instance = ModeManager()
    return _instance


# ---------------------------------------------------------------------------
# ModeManager
# ---------------------------------------------------------------------------

class ModeManager:
    """
    Abstraction layer between all JARVIS agents and the underlying LLM backends.

    In OFFLINE mode: all calls go to Ollama at localhost.
    In ONLINE mode: all calls go to Vertex AI (Gemini 2.5 family) with
    automatic fallback to Ollama on any Vertex AI failure.

    CRITICAL: gemma4:26b and qwen3.5:27b-q4_K_M must NEVER be loaded
    simultaneously — combined RAM would exceed 48 GB on the M4 Pro.
    """

    # Large model RAM guard — these two must never coexist
    _LARGE_MODEL_A = "gemma4:26b"
    _LARGE_MODEL_B = "qwen3.5:27b-q4_K_M"

    def __init__(self) -> None:
        """
        Initialise mode manager from environment variables.

        Loads operation mode, model assignments, and Vertex AI credentials
        if switching to online mode.
        """
        self.operation_mode: str = os.getenv("OPERATION_MODE", "offline").lower()
        self.prototype_mode: bool = os.getenv("PROTOTYPE_MODE", "false").lower() == "true"
        self.ollama_host: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")

        # Model assignments from env
        self.model_receptionist = os.getenv("MODEL_RECEPTIONIST", "gemma4:e4b")
        self.model_orchestrator = os.getenv("MODEL_ORCHESTRATOR", "qwen3.5:27b-q4_K_M")
        self.model_code = os.getenv("MODEL_SPECIALIST_CODE", "gemma4:26b")

        # Online model assignments
        self.model_online_complex = os.getenv("MODEL_ONLINE_COMPLEX", "gemini-2.5-pro")
        self.model_online_medium = os.getenv("MODEL_ONLINE_MEDIUM", "gemini-2.5-flash")
        self.model_online_light = os.getenv("MODEL_ONLINE_LIGHT", "gemini-2.5-flash-lite")

        # RAM tracker: set of model names currently loaded in Ollama
        self.loaded_models: set[str] = set()

        logger.info(
            "ModeManager initialised — mode=%s, prototype=%s, ollama=%s",
            self.operation_mode,
            self.prototype_mode,
            self.ollama_host,
        )

    # ------------------------------------------------------------------
    # Public: main entry point for all agent LLM calls
    # ------------------------------------------------------------------

    async def complete(
        self,
        agent_name: str,
        system_prompt: str,
        user_message: str,
        complexity_score: int,
        images: Optional[list[bytes]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """
        Route a completion request to the correct backend.

        Agents call ONLY this method. Never call _call_ollama or _call_vertex
        directly from outside ModeManager.

        Args:
            agent_name: Name of the calling agent (for model selection).
            system_prompt: Full system prompt (JARVIS_CORE.md + agent prompt).
            user_message: The user's message.
            complexity_score: Score 1-10 from ComplexityRouter.
            images: Optional list of raw image bytes for multimodal calls.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            dict with keys: content (str), model_used (str), mode (str),
            tokens_in (int), tokens_out (int).
        """
        # PRIVACY RULE: voice_triage is ALWAYS local, even in online mode
        effective_mode = self.operation_mode
        if agent_name == "voice_triage":
            effective_mode = "offline"
            logger.info("voice_triage: forcing offline mode for privacy.")

        if effective_mode == "online":
            try:
                model = self._select_online_model(complexity_score)
                return await self._call_vertex(
                    model=model,
                    system_prompt=system_prompt,
                    user_message=user_message,
                    images=images,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Vertex AI call failed: %s — falling back to Ollama.", exc)
                self._speak_fallback_notice()
                # Fall through to offline

        # Offline path
        from core_engine.router import ComplexityRouter  # lazy import to avoid circular
        router = ComplexityRouter()
        model = router.get_offline_model(agent_name, complexity_score)
        return await self._call_ollama(
            model=model,
            system_prompt=system_prompt,
            user_message=user_message,
            images=images,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ------------------------------------------------------------------
    # Private: Ollama backend
    # ------------------------------------------------------------------

    async def _call_ollama(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        images: Optional[list[bytes]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """
        Make an async call to the local Ollama /api/chat endpoint.

        Enforces the critical RAM guard before sending the request:
          - gemma4:26b and qwen3.5:27b-q4_K_M must NEVER be loaded simultaneously.

        Args:
            model: Ollama model tag (e.g. "gemma4:e4b").
            system_prompt: System prompt string.
            user_message: User message string.
            images: Optional list of raw image bytes for multimodal calls.
            temperature: Sampling temperature.
            max_tokens: Max tokens to generate (num_predict in Ollama).

        Returns:
            dict with content, model_used, mode, tokens_in, tokens_out.

        Raises:
            RuntimeError: If RAM guard detects both large models would be loaded.
        """
        # ---- CRITICAL RAM GUARD ----
        if model == self._LARGE_MODEL_A and self._LARGE_MODEL_B in self.loaded_models:
            raise RuntimeError(
                f"BLOCKED: Cannot load {self._LARGE_MODEL_A} while "
                f"{self._LARGE_MODEL_B} is loaded. "
                "Combined RAM would exceed 48 GB on the M4 Pro."
            )
        if model == self._LARGE_MODEL_B and self._LARGE_MODEL_A in self.loaded_models:
            raise RuntimeError(
                f"BLOCKED: Cannot load {self._LARGE_MODEL_B} while "
                f"{self._LARGE_MODEL_A} is loaded. "
                "Combined RAM would exceed 48 GB on the M4 Pro."
            )
        # ---- END RAM GUARD ----

        user_content: dict = {"role": "user", "content": user_message}

        # Attach images as base64 if provided
        if images:
            encoded_images = [base64.b64encode(img).decode("utf-8") for img in images]
            user_content["images"] = encoded_images

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                user_content,
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        url = f"{self.ollama_host}/api/chat"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

            content = data.get("message", {}).get("content", "")
            tokens_in = data.get("prompt_eval_count", 0)
            tokens_out = data.get("eval_count", 0)

            # Track loaded model for RAM guard
            self.loaded_models.add(model)

            return {
                "content": content,
                "model_used": model,
                "mode": "offline",
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }

        except httpx.ConnectError:
            logger.error("Ollama not reachable at %s — is it running?", self.ollama_host)
            return {
                "content": (
                    "I am afraid Ollama is not currently reachable, Sir. "
                    "Please ensure Ollama is running with `ollama serve` and try again."
                ),
                "model_used": model,
                "mode": "offline",
                "tokens_in": 0,
                "tokens_out": 0,
            }
        except httpx.HTTPStatusError as exc:
            logger.error("Ollama returned HTTP %s: %s", exc.response.status_code, exc.response.text)
            return {
                "content": f"Ollama returned an error (HTTP {exc.response.status_code}), Sir. Please check the Ollama logs.",
                "model_used": model,
                "mode": "offline",
                "tokens_in": 0,
                "tokens_out": 0,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Unexpected Ollama error: %s", exc)
            return {
                "content": f"An unexpected error occurred communicating with Ollama, Sir: {exc}",
                "model_used": model,
                "mode": "offline",
                "tokens_in": 0,
                "tokens_out": 0,
            }

    # ------------------------------------------------------------------
    # Private: Vertex AI backend
    # ------------------------------------------------------------------

    async def _call_vertex(
        self,
        model: str,
        system_prompt: str,
        user_message: str,
        images: Optional[list[bytes]] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> dict:
        """
        Make an async call to Vertex AI (Gemini 2.5 family).

        Args:
            model: Vertex AI / Gemini model name (e.g. "gemini-2.5-pro").
            system_prompt: System prompt string.
            user_message: User message string.
            images: Optional list of raw image bytes for multimodal calls.
            temperature: Sampling temperature.
            max_tokens: Max output tokens.

        Returns:
            dict with content, model_used, mode, tokens_in, tokens_out.

        Raises:
            Exception: If Vertex AI SDK is unavailable or call fails.
        """
        try:
            import vertexai
            from vertexai.generative_models import GenerativeModel, Part, GenerationConfig
        except ImportError as exc:
            raise ImportError(
                "Vertex AI SDK not installed. Install with: "
                "pip install google-cloud-aiplatform vertexai"
            ) from exc

        project = os.getenv("VERTEX_PROJECT", "")
        location = os.getenv("VERTEX_LOCATION", "us-central1")

        if not project:
            raise ValueError("VERTEX_PROJECT env var not set. Cannot use online mode.")

        vertexai.init(project=project, location=location)
        gen_model = GenerativeModel(
            model_name=model,
            system_instruction=system_prompt,
        )

        generation_config = GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )

        contents: list = [user_message]

        if images:
            for img_bytes in images:
                encoded = base64.b64encode(img_bytes).decode("utf-8")
                contents.append(Part.from_data(data=base64.b64decode(encoded), mime_type="image/png"))

        response = await gen_model.generate_content_async(
            contents=contents,
            generation_config=generation_config,
        )

        content = response.text if hasattr(response, "text") else ""
        tokens_in = getattr(response.usage_metadata, "prompt_token_count", 0)
        tokens_out = getattr(response.usage_metadata, "candidates_token_count", 0)

        return {
            "content": content,
            "model_used": model,
            "mode": "online",
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }

    # ------------------------------------------------------------------
    # Mode validation & switching
    # ------------------------------------------------------------------

    def validate_mode_switch(self, target_mode: str) -> dict:
        """
        Validate whether switching to the target mode is possible.

        For "online" mode: checks Vertex AI credentials file exists and
        required env vars are set.

        Args:
            target_mode: "offline" or "online".

        Returns:
            dict with keys: valid (bool), error (str, if not valid).
        """
        if target_mode == "offline":
            return {"valid": True}

        if target_mode == "online":
            # Check GCP credentials file
            creds_path_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
            creds_path = Path(os.path.expanduser(creds_path_raw))
            if not creds_path_raw or not creds_path.exists():
                return {
                    "valid": False,
                    "error": (
                        f"Missing Vertex AI credentials file at '{creds_path_raw}'. "
                        "Set GOOGLE_APPLICATION_CREDENTIALS in .env to your service account JSON."
                    ),
                }

            # Check project and location
            if not os.getenv("VERTEX_PROJECT"):
                return {
                    "valid": False,
                    "error": "VERTEX_PROJECT env var not set. Cannot switch to online mode.",
                }
            if not os.getenv("VERTEX_LOCATION"):
                return {
                    "valid": False,
                    "error": "VERTEX_LOCATION env var not set. Cannot switch to online mode.",
                }

            # Check SDK availability
            try:
                import vertexai  # noqa: F401
            except ImportError:
                return {
                    "valid": False,
                    "error": (
                        "Vertex AI SDK not installed. "
                        "Run: pip install google-cloud-aiplatform vertexai"
                    ),
                }

            return {"valid": True}

        return {"valid": False, "error": f"Unknown mode: '{target_mode}'. Use 'offline' or 'online'."}

    def set_mode(self, new_mode: str) -> None:
        """
        Update the in-memory operation mode.

        Args:
            new_mode: "offline" or "online".
        """
        self.operation_mode = new_mode
        os.environ["OPERATION_MODE"] = new_mode
        logger.info("Operation mode switched to: %s", new_mode)

    def get_current_mode(self) -> str:
        """
        Return the current operation mode.

        Returns:
            "offline" or "online".
        """
        return self.operation_mode

    async def get_loaded_models(self) -> list[str]:
        """
        Query Ollama /api/ps to get currently loaded model names.

        Returns:
            List of model name strings currently loaded in Ollama VRAM/RAM.
        """
        url = f"{self.ollama_host}/api/ps"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not query Ollama /api/ps: %s", exc)
            return list(self.loaded_models)

    async def unload_model(self, model_name: str) -> bool:
        """
        Force-unload a model from Ollama by sending keep_alive=0.

        Args:
            model_name: The Ollama model tag to unload.

        Returns:
            True if the unload request succeeded, False otherwise.
        """
        url = f"{self.ollama_host}/api/generate"
        payload = {"model": model_name, "keep_alive": 0}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
            self.loaded_models.discard(model_name)
            logger.info("Unloaded model: %s", model_name)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to unload model '%s': %s", model_name, exc)
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_online_model(self, complexity_score: int) -> str:
        """
        Select the appropriate Vertex AI model based on complexity score.

        Args:
            complexity_score: Score 1-10 from ComplexityRouter.

        Returns:
            Vertex AI model name string.
        """
        vertex_pro_threshold = int(os.getenv("COMPLEXITY_VERTEX_PRO", "8"))
        vertex_flash_threshold = int(os.getenv("COMPLEXITY_VERTEX_FLASH", "5"))

        if complexity_score >= vertex_pro_threshold:
            return self.model_online_complex
        if complexity_score >= vertex_flash_threshold:
            return self.model_online_medium
        return self.model_online_light

    def _speak_fallback_notice(self) -> None:
        """
        Print / speak a fallback notice when Vertex AI becomes unavailable.

        In Phase 3, this will call TTSEngine.speak(). In Phase 1, it logs and prints.
        """
        msg = "Vertex AI unavailable, Sir. Switching to offline mode."
        logger.warning(msg)
        print(f"[JARVIS]: {msg}")
