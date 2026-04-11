"""
J.A.R.V.I.S. — core_engine/gateway.py
FastAPI main application. ALL requests enter through here.

Author: Hitansu Parichha | Nisum Technologies
Phase 1 — Blueprint v5.0
"""

from __future__ import annotations

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

    query: str
    top_k: int = 5


class MemoryQueryResponse(BaseModel):
    """Response body for POST /memory/query (Phase 4 stub)."""

    facts: list[str]


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
    Append a JSON-Lines entry to sandbox/audit.log.

    Args:
        entry: Dict to serialise as a single JSON line.
    """
    try:
        _AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _AUDIT_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to write audit log: %s", exc)


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
    global _registry, _router, _mode_manager, _security_enforcer, _audit

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

    yield  # ← server runs here

    # ---- Shutdown ----
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
async def chat(request: ChatRequest):
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

    # Step 3: Build system prompt (JARVIS_CORE.md prepended inside get_system_prompt)
    system_prompt = _registry.get_system_prompt(recommended_agent)

    # Read per-agent temperature from registry (code_specialist=0.1, auditor=0.1, etc.)
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
            temperature=agent_temperature,   # ← FIX 1: use per-agent temperature
        )
    finally:
        # Restore original mode if it was overridden for this request
        if request.mode_override:
            _mode_manager.set_mode(original_mode)

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

    return ChatResponse(
        response=result.get("content", ""),
        agent_used=recommended_agent,
        model_used=result.get("model_used", "unknown"),
        complexity_score=score,
        mode=result.get("mode", _mode_manager.get_current_mode()),
    )


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


@app.post("/memory/query", response_model=MemoryQueryResponse)
async def memory_query(request: MemoryQueryRequest):
    """
    Query the JARVIS memory system for relevant facts.

    Phase 4 stub — returns empty list until ChromaDB is activated.

    Args:
        request: MemoryQueryRequest with query string and optional top_k.

    Returns:
        MemoryQueryResponse with empty facts list (Phase 4 stub).
    """
    logger.info(
        "Memory query stub called: query='%s', top_k=%d — awaiting Phase 4.",
        request.query[:80],
        request.top_k,
    )
    # Phase 4 will replace this with: ChromaStore().query_facts(request.query, request.top_k)
    return MemoryQueryResponse(facts=[])


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

