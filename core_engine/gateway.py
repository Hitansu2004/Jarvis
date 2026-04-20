"""
J.A.R.V.I.S. — core_engine/gateway.py
FastAPI main application. ALL requests enter through here.

Author: Hitansu Parichha | Nisum Technologies
Phase 4 — Blueprint v6.0 (Infinite Personalized Memory)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Load environment FIRST — before any internal imports
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"
load_dotenv(dotenv_path=_ENV_PATH if _ENV_PATH.exists() else None)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("jarvis.gateway")

# ---------------------------------------------------------------------------
# Internal imports (after env load)
# ---------------------------------------------------------------------------
from core_engine.agent_registry import AgentRegistry
from core_engine.mode_manager import ModeManager, get_mode_manager
from core_engine.router import ComplexityRouter
from sandbox.security_enforcer import SecurityEnforcer, get_security_enforcer
from sandbox.audit_manager import AuditManager, get_audit_manager
from voice_engine.tts import get_tts_engine, TTSEngine
from voice_engine.stt import get_stt_engine, STTEngine
from voice_engine.wake_word import get_wake_word_detector, WakeWordDetector
from voice_engine.voice_session import get_voice_session_manager, VoiceSessionManager

# ---------------------------------------------------------------------------
# Phase 4 — Memory system imports (graceful: all degrade if not installed)
# ---------------------------------------------------------------------------
from memory_vault.chroma_store import ChromaStore
from memory_vault.graphiti_store import GraphitiStore
from memory_vault.retriever import HybridRetriever
from memory_vault.distiller import MemoryDistiller, setup_distiller_scheduler
from memory_vault.logger import ConversationLogger
from memory_vault.correction_parser import parse_correction_command

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------
_AUDIT_LOG_PATH = _PROJECT_ROOT / "sandbox" / "audit.log"
_MEMORY_LOGS_PATH = _PROJECT_ROOT / "memory_vault" / "logs"
_SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# ---------------------------------------------------------------------------
# Startup singletons (initialised in lifespan)
# ---------------------------------------------------------------------------
_registry: Optional[AgentRegistry] = None
_router: Optional[ComplexityRouter] = None
_mode_manager: Optional[ModeManager] = None
_security_enforcer: Optional[SecurityEnforcer] = None
_audit: Optional[AuditManager] = None
_voice_session: Optional[VoiceSessionManager] = None
_tts_engine: Optional[TTSEngine] = None
_stt_engine: Optional[STTEngine] = None

# Phase 4 memory singletons
_chroma_store: Optional[ChromaStore] = None
_graphiti_store: Optional[GraphitiStore] = None
_retriever: Optional[HybridRetriever] = None
_distiller: Optional[MemoryDistiller] = None
_conv_logger: Optional[ConversationLogger] = None
_distiller_scheduler = None


# ===========================================================================
# Pydantic models
# ===========================================================================

class ChatRequest(BaseModel):
    """Request body for POST /chat."""

    message: str
    context: Optional[str] = None
    mode_override: Optional[str] = None


class ChatResponse(BaseModel):
    """Response body for POST /chat."""

    response: str
    agent_used: str
    model_used: str
    complexity_score: int
    mode: str


class ModeRequest(BaseModel):
    """Request body for POST /mode."""

    mode: str  # "offline" | "online"


class ModeResponse(BaseModel):
    """Response body for POST /mode."""

    status: str
    mode: str
    message: str


class MemoryQueryRequest(BaseModel):
    """Request body for POST /memory/query."""

    query: Optional[str] = None
    top_k: int = 5


class MemoryQueryResponse(BaseModel):
    """Response body for POST /memory/query."""

    query: str
    context: str
    facts: list[str]


class MemoryCorrectRequest(BaseModel):
    """Request body for POST /memory/correct."""

    command: Optional[str] = None


class SpecSheet(BaseModel):
    """
    Spec Sheet data model for inter-agent task delegation.

    Used from Phase 7 onwards. Defined in Phase 1 so it is available
    as an import across all future phases.
    """

    task_id: str
    task_description: str
    context: str = ""
    relevant_files: list[str] = []
    memory_facts: list[str] = []
    tech_stack: list[str] = []
    acceptance_criteria: str = ""
    constraints: str = ""
    previous_output: str = ""
    tools_allowed: list[str] = []
    agent_name: str = ""
    model_used: str = ""
    created_at: str = ""


class SecurityConfirmRequest(BaseModel):
    confirmation_key: str

class VoiceSpeakRequest(BaseModel):
    text: str
    language: str = "en"
    urgent: bool = False

class VoiceListenRequest(BaseModel):
    duration_seconds: float = 5.0
    language: Optional[str] = None

class SuppressRequest(BaseModel):
    seconds: int = 120

# ===========================================================================
# Helper utilities
# ===========================================================================

def _get_greeting() -> str:
    """
    Return time-appropriate greeting (morning / afternoon / evening).

    Returns:
        Greeting string based on the current local hour.
    """
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


def _write_audit_log(entry: dict) -> None:
    """
    Append a JSON-Lines entry to sandbox/audit.log via AuditManager.

    Args:
        entry: Dict to serialise and write to the audit chain.
    """
    try:
        from sandbox.audit_manager import get_audit_manager
        get_audit_manager().write(entry)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write audit log via manager: %s", exc)


def _iso_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ===========================================================================
# FastAPI lifespan (startup / shutdown)
# ===========================================================================

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Handles startup and shutdown logic:
    - Creates required directories and files
    - Loads JARVIS_CORE.md
    - Initialises singletons (AgentRegistry, ComplexityRouter, ModeManager)
    - Prints JARVIS boot message
    """
    global _registry, _router, _mode_manager, _security_enforcer, _audit, _voice_session, _tts_engine, _stt_engine
    global _chroma_store, _graphiti_store, _retriever, _distiller, _conv_logger, _distiller_scheduler

    import asyncio

    # ---- Create required directories ----
    _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _MEMORY_LOGS_PATH.mkdir(parents=True, exist_ok=True)
    (_AUDIT_LOG_PATH.parent.parent / "memory_vault" / "chroma_db").mkdir(parents=True, exist_ok=True)

    # ---- Create audit.log if it does not exist ----
    if not _AUDIT_LOG_PATH.exists():
        _AUDIT_LOG_PATH.touch()

    # ---- Initialise singletons ----
    _registry = AgentRegistry()
    _router = ComplexityRouter()
    _mode_manager = get_mode_manager()
    _security_enforcer = get_security_enforcer()
    _audit = get_audit_manager()

    # Initialize voice engines
    _tts_engine = get_tts_engine()
    _stt_engine = get_stt_engine()

    # Wire voice session callback to gateway chat pipeline
    _voice_session = get_voice_session_manager()

    async def _voice_transcription_callback(text: str, session_id: str):
        """
        Called when wake word + STT produces a transcribed command.
        Passes text directly to LLM — no translation needed, Gemma4 is multilingual.
        Language detection is only used to select the right TTS voice.
        """
        _write_audit_log({
            "timestamp": _iso_now(),
            "agent_name": "voice_triage",
            "model_used": "whisper-small",
            "action_type": "VOICE_COMMAND",
            "command_or_url": f"VOICE: {text[:100]}",
            "confirmation_status": "AUTO_APPROVED",
            "outcome": "SUCCESS",
            "error_message": None,
        })

        # Terminal display — always show what was heard
        print(f"\n{'─'*60}")
        print(f"🎤 YOU  : {text}")
        print(f"{'─'*60}")

        tts_language = "auto" # Always auto-detect voice based on LLM response text, not input text

        logger.info("Voice command [%s]: '%s'", session_id, text[:80])

        classification = _router.classify(text)
        system_prompt = _registry.get_system_prompt(classification["recommended_agent"])
        system_prompt += (
            "\n\n[VOICE MODE RULES]\n"
            "1. No markdown (no **, *, #, bullets).\n"
            "2. Keep it very short (max 2-3 sentences).\n"
            "3. Say 'Jarvis', not 'J.A.R.V.I.S.'.\n"
            "4. CRITICAL: If you respond in Hindi, you MUST write in the DEVANAGARI script (e.g., नमस्ते). "
            "Never use Roman/Latin script for Hindi (e.g., namaste) because the text-to-speech engine cannot pronounce it."
        )

        try:
            result = await _mode_manager.complete(
                agent_name=classification["recommended_agent"],
                system_prompt=system_prompt,
                user_message=text,
                complexity_score=classification["score"],
            )
            response_text = result.get("content", "")
            if not response_text:
                return

            print(f"🤖 JARVIS: {response_text}")
            print(f"{'─'*60}\n")
            await _voice_session.speak_response(response_text, language=tts_language)

        except Exception as e:
            logger.error("Voice command processing failed: %s", e)
            await _voice_session.speak_immediately("I encountered an error processing that command, Sir.")




    _voice_session.set_transcription_callback(_voice_transcription_callback)
    _voice_session.start()
    logger.info("Voice session manager started.")

    async def cleanup_loop():
        while True:
            await asyncio.sleep(60)
            _security_enforcer.cleanup_expired()
            
    asyncio.create_task(cleanup_loop())

    # ---- JARVIS Boot Message ----
    greeting = _get_greeting()
    agents_loaded = _registry.agent_count
    mode = _mode_manager.get_current_mode()
    boot_msg = (
        f"\n{'='*60}\n"
        f"  J.A.R.V.I.S. v5.0 — Online. {greeting}, Sir.\n"
        f"  Mode     : {mode.upper()}\n"
        f"  Agents   : {agents_loaded} registered\n"
        f"  Port     : {_SERVER_PORT}\n"
        f"  Audit    : {_AUDIT_LOG_PATH}\n"
        f"{'='*60}\n"
    )
    print(boot_msg)
    logger.info("JARVIS Phase 1 gateway started — %d agents loaded.", agents_loaded)

    # ---- Audit startup event ----
    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": "gateway",
        "model_used": "none",
        "action_type": "STARTUP",
        "command_or_url": f"uvicorn core_engine.gateway:app --port {_SERVER_PORT}",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS",
        "error_message": None,
    })

    # ── Phase 4: Initialize memory system ────────────────────────────────────
    _conv_logger = ConversationLogger()

    _chroma_store = ChromaStore()
    chroma_ok = _chroma_store.initialize()

    _graphiti_store = GraphitiStore()
    graphiti_ok = await _graphiti_store.initialize()

    _retriever = HybridRetriever(
        graphiti_store=_graphiti_store,
        chroma_store=_chroma_store,
    )

    _distiller = MemoryDistiller(
        chroma_store=_chroma_store,
        graphiti_store=_graphiti_store,
        mode_manager=_mode_manager,
    )
    _distiller_scheduler = setup_distiller_scheduler(_distiller)

    # Expose memory components on app.state for tests
    app.state.chroma_store = _chroma_store
    app.state.graphiti_store = _graphiti_store
    app.state.conv_logger = _conv_logger

    memory_status = []
    if chroma_ok:
        memory_status.append("ChromaDB")
    if graphiti_ok:
        memory_status.append("Graphiti")
    memory_status.extend(["Wiki", "Logger"])
    logger.info("Memory system initialized: %s", " + ".join(memory_status))
    print(f"  Memory   : {' + '.join(memory_status)}")

    yield  # ← server runs here

    # ---- Shutdown ----
    if _distiller_scheduler:
        try:
            _distiller_scheduler.shutdown(wait=False)
        except Exception:
            pass
    if _graphiti_store:
        await _graphiti_store.close()
    logger.info("J.A.R.V.I.S. shutting down. Standing by, Sir.")


# ===========================================================================
# FastAPI application
# ===========================================================================

app = FastAPI(
    title="J.A.R.V.I.S. v5.0",
    description=(
        "Just A Rather Very Intelligent System — "
        "Personal AI Operating System by Hitansu Parichha"
    ),
    version="5.0.0",
    lifespan=lifespan,
)

# ---- CORS (for Phase 10 web dashboard at localhost:3000) ----
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Request logging middleware
# ===========================================================================

@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    """
    Log every HTTP request to sandbox/audit.log.

    Records: timestamp, method, path, status_code, duration_ms.
    """
    start = time.monotonic()
    response: Response = await call_next(request)
    duration_ms = round((time.monotonic() - start) * 1000, 2)

    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": "gateway.middleware",
        "model_used": "none",
        "action_type": "HTTP_REQUEST",
        "command_or_url": f"{request.method} {request.url.path}",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS" if response.status_code < 400 else "FAILURE",
        "error_message": None,
        "status_code": response.status_code,
        "duration_ms": duration_ms,
    })

    return response


# ===========================================================================
# Routes
# ===========================================================================

@app.get("/health")
async def health_check():
    """
    Simple health check endpoint for monitoring systems.

    Returns:
        JSON with status "alive" and current UTC timestamp.
    """
    return {"status": "alive", "timestamp": _iso_now()}


@app.get("/status")
async def get_status():
    """
    Full system status — mode, models, agents, connectivity.

    Pings Ollama /api/tags to check availability.
    Checks Vertex AI credentials file existence.

    Returns:
        JSON with mode, prototype_mode, ollama_alive, vertex_configured,
        agents_loaded, models_available.
    """
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    ollama_alive = False
    models_available: list[str] = []

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{ollama_host}/api/tags")
            if resp.status_code == 200:
                ollama_alive = True
                data = resp.json()
                models_available = [m.get("name", "") for m in data.get("models", [])]
    except Exception:  # noqa: BLE001
        pass

    creds_path_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    vertex_configured = bool(
        creds_path_raw and Path(os.path.expanduser(creds_path_raw)).exists()
    )

    return {
        "mode": _mode_manager.get_current_mode(),
        "prototype_mode": _router.prototype_mode,
        "ollama_alive": ollama_alive,
        "vertex_configured": vertex_configured,
        "agents_loaded": _registry.agent_count,
        "models_available": models_available,
    }


@app.get("/agents")
async def list_agents():
    """
    Return the full agent registry dump.

    Returns:
        JSON with a list of all agent definition dicts.
    """
    return {"agents": _registry.list_agents(enabled_only=False)}


@app.post("/agents/reload")
async def reload_agents():
    """
    Hot-reload agents.json without restarting the server.

    Returns:
        JSON with status "reloaded" and count of loaded agents.
    """
    count = _registry.reload()
    logger.info("Agent registry reloaded — %d agents.", count)
    return {"status": "reloaded", "agents_loaded": count}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, speak: bool = False):
    """
    Primary chat endpoint — all user messages enter here.

    Logic:
      1. Determine effective mode (env or mode_override from request).
      2. Classify complexity via ComplexityRouter.
      3. Prepend JARVIS_CORE.md to the message context.
      4. Look up correct agent from registry.
      5. Call ModeManager.complete() with the agent + prompt + score.
      6. Return structured response.

    Args:
        request: ChatRequest with message, optional context, optional mode_override.

    Returns:
        ChatResponse with response text, agent_used, model_used, complexity_score, mode.
    """
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    # ── Phase 4 Step A: Check for memory correction commands FIRST ─────────────
    _CORRECTION_TRIGGERS = [
        "forget that", "remember that", "what do you know about me",
        "show me my", "clear everything", "do not learn", "don't learn",
        "stop remembering", "remove that", "stop learning",
    ]
    msg_lower = request.message.lower()
    if any(trigger in msg_lower for trigger in _CORRECTION_TRIGGERS):
        action = parse_correction_command(request.message)
        if action.action_type != "UNKNOWN":
            return await _handle_memory_command(action)

    # Step 1: Determine effective mode
    original_mode = _mode_manager.get_current_mode()
    if request.mode_override:
        override = request.mode_override.lower()
        if override in ("offline", "online"):
            _mode_manager.set_mode(override)
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid mode_override '{override}'. Use 'offline' or 'online'.",
            )

    # Step 2: Classify complexity
    context_str = request.context or ""
    classification = _router.classify(request.message, context_str)
    score: int = classification["score"]
    recommended_agent: str = classification["recommended_agent"]

    # Step 3: Build system prompt + Phase 4 memory context
    system_prompt = _registry.get_system_prompt(recommended_agent)

    # ── Phase 4 Step B: Inject memory context into system prompt ──────────────
    if _retriever:
        try:
            memory_context = await _retriever.get_context(request.message)
            if memory_context:
                system_prompt = f"{system_prompt}\n\n{memory_context}"
        except Exception as _mem_exc:
            logger.warning("Memory context retrieval failed (non-critical): %s", _mem_exc)

    # Read per-agent temperature from registry
    agent_def = _registry.get_agent(recommended_agent)
    agent_temperature: float = agent_def.get("temperature", 0.7) if agent_def else 0.7

    # Append any user-supplied context
    user_message = request.message
    if context_str:
        user_message = f"[Context]\n{context_str}\n\n[Message]\n{request.message}"

    # Step 4 & 5: Call ModeManager
    try:
        result = await _mode_manager.complete(
            agent_name=recommended_agent,
            system_prompt=system_prompt,
            user_message=user_message,
            complexity_score=score,
            temperature=agent_temperature,
        )
    finally:
        if request.mode_override:
            _mode_manager.set_mode(original_mode)

    response_text = result.get("content", "")

    # ── Phase 4 Step C: Log conversation turn ────────────────────────────────
    if _conv_logger:
        try:
            _conv_logger.log_conversation(
                user_message=request.message,
                jarvis_response=response_text,
                agent_used=recommended_agent,
                model_used=result.get("model_used", "unknown"),
            )
        except Exception as _log_exc:
            logger.warning("Conversation logging failed (non-critical): %s", _log_exc)

    # Step 6: Audit and return
    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": recommended_agent,
        "model_used": result.get("model_used", "unknown"),
        "action_type": "CHAT",
        "command_or_url": f"POST /chat — complexity={score}",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS",
        "error_message": None,
    })

    if speak and response_text:
        await _voice_session.speak_response(response_text)

    return ChatResponse(
        response=response_text,
        agent_used=recommended_agent,
        model_used=result.get("model_used", "unknown"),
        complexity_score=score,
        mode=result.get("mode", _mode_manager.get_current_mode()),
    )


async def _handle_memory_command(action) -> ChatResponse:
    """
    Dispatch a parsed memory correction command and return a JARVIS response.
    Called when the user issues a memory command before routing to any agent.
    """
    from memory_vault.correction_parser import MemoryAction
    from pathlib import Path

    action_type = action.action_type
    response_text = "Understood, Sir."

    try:
        if action_type == "FORGET" and action.entity:
            if _chroma_store and _chroma_store.is_available:
                _chroma_store.delete_facts_by_date("")
            if _graphiti_store and _graphiti_store.is_available:
                await _graphiti_store.invalidate_fact_by_text(action.entity)
            # Append to corrections wiki
            _append_correction(f"FORGET | {action.entity}")
            response_text = f"Understood, Sir. I have removed all memory of your use of {action.entity}."

        elif action_type == "REMEMBER" and action.entity:
            if _chroma_store and _chroma_store.is_available:
                _chroma_store.add_fact(action.entity, category="user_correction")
            if _graphiti_store and _graphiti_store.is_available:
                await _graphiti_store.add_fact(action.entity, category="user_correction", source="user_correction")
            _append_correction(f"REMEMBER | {action.entity}")
            response_text = f"Noted, Sir. I have updated my memory: {action.entity}."

        elif action_type == "SHOW_PROFILE":
            wiki_file = Path("./memory_vault/wiki/user_profile.md")
            profile = wiki_file.read_text() if wiki_file.exists() else "No profile compiled yet, Sir. Check back after the first nightly distillation."
            response_text = f"Here is what I know about you, Sir:\n{profile}"

        elif action_type == "SHOW_WIKI":
            wiki_file = Path(f"./memory_vault/wiki/{action.wiki_file}.md")
            content = wiki_file.read_text() if wiki_file.exists() else f"No {action.wiki_file} wiki compiled yet, Sir."
            response_text = content

        elif action_type == "CLEAR_DATE" and action.target_date:
            if _chroma_store and _chroma_store.is_available:
                _chroma_store.delete_facts_by_date(action.target_date)
            if _graphiti_store and _graphiti_store.is_available:
                await _graphiti_store.invalidate_facts_by_date(action.target_date)
            response_text = f"Understood, Sir. I have cleared everything I learned on {action.target_date}."

        elif action_type == "PAUSE_LEARNING":
            import memory_vault.logger as log_module
            log_module.PASSIVE_LEARNING_ENABLED = False
            asyncio.get_event_loop().call_later(
                action.pause_minutes * 60,
                lambda: setattr(log_module, "PASSIVE_LEARNING_ENABLED", True)
            )
            response_text = f"Understood, Sir. I will not learn from the next {action.pause_minutes} minutes."

    except Exception as e:
        logger.error("Memory command execution failed: %s", e)
        response_text = "I encountered an issue processing that memory command, Sir."

    return ChatResponse(
        response=response_text,
        agent_used="memory_system",
        model_used="none",
        complexity_score=0,
        mode=_mode_manager.get_current_mode() if _mode_manager else "offline",
    )


def _append_correction(entry: str) -> None:
    """Append a correction entry to wiki/corrections.md."""
    try:
        from datetime import datetime, timezone
        corrections_file = Path("./memory_vault/wiki/corrections.md")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(corrections_file, "a", encoding="utf-8") as f:
            f.write(f"\n- [{timestamp}] {entry}")
    except Exception as e:
        logger.warning("Could not write corrections.md: %s", e)


@app.post("/mode", response_model=ModeResponse)
async def switch_mode(request: ModeRequest):
    """
    Switch the operation mode between OFFLINE and ONLINE.

    Validates Vertex AI credentials before switching to online.

    Args:
        request: ModeRequest with "mode" field ("offline" or "online").

    Returns:
        ModeResponse with status, mode, and human-readable message.
    """
    target = request.mode.lower()
    if target not in ("offline", "online"):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid mode '{target}'. Use 'offline' or 'online'.",
        )

    validation = _mode_manager.validate_mode_switch(target)
    if not validation.get("valid", False):
        error_msg = validation.get("error", "Mode switch validation failed.")
        _write_audit_log({
            "timestamp": _iso_now(),
            "agent_name": "gateway",
            "model_used": "none",
            "action_type": "MODE_SWITCH",
            "command_or_url": f"POST /mode → {target}",
            "confirmation_status": "DENIED",
            "outcome": "BLOCKED",
            "error_message": error_msg,
        })
        return ModeResponse(
            status="error",
            mode=_mode_manager.get_current_mode(),
            message=f"Cannot switch to online mode, Sir. {error_msg}",
        )

    _mode_manager.set_mode(target)

    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": "gateway",
        "model_used": "none",
        "action_type": "MODE_SWITCH",
        "command_or_url": f"POST /mode → {target}",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS",
        "error_message": None,
    })

    msg_map = {
        "offline": "Switching to local Ollama models, Sir. All processing is now private and on-device.",
        "online": "Switching to Vertex AI, Sir. Gemini 2.5 family is now handling all requests.",
    }

    return ModeResponse(
        status="switched",
        mode=target,
        message=msg_map[target],
    )


# ===========================================================================
# Phase 4 — Memory Routes
# ===========================================================================

@app.get("/memory/stats")
async def memory_stats():
    """
    Return memory system statistics.

    Returns:
        JSON with chroma_vectors, graphiti_nodes, wiki_files, log_files.
    """
    # Use app.state if available (allows test injection of mocks)
    chroma = getattr(app.state, "chroma_store", _chroma_store)
    graphiti = getattr(app.state, "graphiti_store", _graphiti_store)
    conv_log = getattr(app.state, "conv_logger", _conv_logger)

    chroma_count = 0
    if chroma and chroma.is_available:
        chroma_count = chroma.get_count()

    graphiti_nodes = 0
    if graphiti and graphiti.is_available:
        try:
            graphiti_nodes = await graphiti.get_node_count()
        except Exception:
            graphiti_nodes = 0

    wiki_files = []
    wiki_dir = Path("./memory_vault/wiki")
    if wiki_dir.exists():
        wiki_files = [f.name for f in wiki_dir.glob("*.md")]

    log_files = []
    if conv_log:
        try:
            log_files = conv_log.list_log_files()
        except Exception:
            log_files = []

    return {
        "chroma_vectors": chroma_count,
        "graphiti_nodes": graphiti_nodes,
        "wiki_files": wiki_files,
        "log_files": len(log_files),
        "chroma_available": bool(chroma and chroma.is_available),
        "graphiti_available": bool(graphiti and graphiti.is_available),
    }


@app.get("/memory/wiki")
async def memory_wiki():
    """
    List all compiled wiki files with their sizes.

    Returns:
        JSON with wiki_files list of {name, size_kb} dicts.
    """
    wiki_dir = Path("./memory_vault/wiki")
    files = []
    if wiki_dir.exists():
        for f in sorted(wiki_dir.glob("*.md")):
            size_kb = round(f.stat().st_size / 1024, 2)
            files.append({"name": f.name, "size_kb": size_kb})
    return {"wiki_files": files}


@app.post("/memory/query")
async def memory_query(request: MemoryQueryRequest):
    """
    Query the JARVIS hybrid memory system for relevant facts.

    Args:
        request: MemoryQueryRequest with query string and optional top_k.

    Returns:
        JSON with query, context block, and list of raw facts.
    """
    if not request.query or not request.query.strip():
        return {"error": "query field is required", "query": "", "context": "", "facts": []}

    chroma = getattr(app.state, "chroma_store", _chroma_store)
    graphiti = getattr(app.state, "graphiti_store", _graphiti_store)

    if not _retriever and not chroma and not graphiti:
        return {"query": request.query, "context": "", "facts": [], "status": "degraded"}

    try:
        retriever = _retriever or HybridRetriever(graphiti_store=graphiti, chroma_store=chroma)
        context = await retriever.get_context(request.query, top_k=request.top_k)
        # Extract individual fact lines from the context block
        facts = [
            line.lstrip("• ").split("  [")[0].strip()
            for line in context.splitlines()
            if line.startswith("•")
        ]
        return {"query": request.query, "context": context, "facts": facts}
    except Exception as e:
        logger.error("Memory query failed: %s", e)
        return {"query": request.query, "context": "", "facts": [], "error": str(e)}


@app.post("/memory/correct")
async def memory_correct(request: MemoryCorrectRequest):
    """
    Process a memory correction command from the user.

    Args:
        request: MemoryCorrectRequest with command string.

    Returns:
        JSON with action_type, entity, and JARVIS response.
    """
    if not request.command or not request.command.strip():
        return {"error": "command field is required"}

    action = parse_correction_command(request.command)
    if action.action_type == "UNKNOWN":
        return {
            "action_type": "UNKNOWN",
            "entity": "",
            "response": "I did not recognize that as a memory command, Sir.",
        }

    chat_response = await _handle_memory_command(action)
    return {
        "action_type": action.action_type,
        "entity": action.entity,
        "wiki_file": action.wiki_file,
        "pause_minutes": action.pause_minutes,
        "target_date": action.target_date,
        "response": chat_response.response,
    }


@app.post("/screen/capture")
async def screen_capture():
    """
    Capture and describe the current screen.

    Phase 5 stub — returns placeholder description until vision is activated.

    Returns:
        JSON with placeholder description and current timestamp.
    """
    logger.info("Screen capture stub called — awaiting Phase 5.")
    return {
        "description": (
            "Screen capture is not yet active, Sir. "
            "The vision engine will be fully operational in Phase 5."
        ),
        "timestamp": _iso_now(),
    }


@app.post("/control/override")
async def control_override():
    """
    Return screen control to the user immediately.

    Phase 6 stub — real mutex and overlay implementation in Phase 6.

    Returns:
        JSON with status "control_returned" and current timestamp.
    """
    logger.info("Control override stub called — awaiting Phase 6.")
    return {
        "status": "control_returned",
        "timestamp": _iso_now(),
    }

# ===========================================================================
# Phase 2 — Security Routes
# ===========================================================================

@app.post("/security/confirm")
async def security_confirm(request: SecurityConfirmRequest):
    result = _security_enforcer.confirm(request.confirmation_key)
    return result

@app.post("/security/cancel")
async def security_cancel(request: SecurityConfirmRequest):
    result = _security_enforcer.cancel(request.confirmation_key)
    return result

@app.get("/security/status")
async def security_status():
    return _security_enforcer.get_security_status()

@app.get("/security/audit")
async def security_audit(limit: int = 50, action_type: Optional[str] = None):
    # Retrieve via AuditManager which is the security log engine
    entries = _audit.get_recent(limit=limit, action_type=action_type)
    return {"entries": entries, "total": len(entries)}

@app.get("/security/violations")
async def security_violations(since_hours: int = 24):
    violations = _audit.get_violations(since_hours=since_hours)
    return {"violations": violations, "count": len(violations)}

# ===========================================================================
# Phase 3 — Voice Routes
# ===========================================================================

@app.post("/voice/speak")
async def voice_speak(request: VoiceSpeakRequest):
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=422, detail="Text cannot be empty.")
    
    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": "gateway.voice",
        "model_used": "none",
        "action_type": "VOICE_COMMAND",
        "command_or_url": f"TTS: {request.text[:100]}",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS",
        "error_message": None,
    })
    
    spoken = await _tts_engine.speak(request.text, request.language, request.urgent)
    return {"spoken": spoken, "engine_used": _tts_engine.get_status()["active_engine"], "text": request.text}

@app.post("/voice/listen")
async def voice_listen(request: VoiceListenRequest):
    _write_audit_log({
        "timestamp": _iso_now(),
        "agent_name": "gateway.voice",
        "model_used": "whisper",
        "action_type": "VOICE_COMMAND",
        "command_or_url": "STT manual listen",
        "confirmation_status": "AUTO_APPROVED",
        "outcome": "SUCCESS",
        "error_message": None,
    })
    text = await _stt_engine.record_and_transcribe(request.duration_seconds, request.language)
    return {"text": text, "language_detected": request.language or "auto", "duration": request.duration_seconds}

@app.post("/voice/wake")
async def voice_wake():
    loop = asyncio.get_event_loop()
    asyncio.run_coroutine_threadsafe(_voice_session._handle_voice_session(), loop)
    return {"status": "wake_triggered", "session_id": _voice_session._current_session_id or str(uuid.uuid4())}

@app.post("/voice/suppress")
async def voice_suppress(request: SuppressRequest):
    _voice_session.suppress_suggestions(request.seconds)
    await _voice_session.speak_immediately("Understood, Sir. I will hold my suggestions for now.")
    return {"status": "suppressed", "seconds": request.seconds, "until": _iso_now()}

@app.get("/voice/suppressed")
async def voice_suppressed():
    suggestions = _voice_session.get_suppressed_suggestions()
    if suggestions:
        await _voice_session.speak_immediately("Sir, I noticed several things while I was quiet — shall I share them?")
    return {"suggestions": suggestions, "count": len(suggestions)}

@app.get("/voice/status")
async def voice_status():
    return _voice_session.get_status()
