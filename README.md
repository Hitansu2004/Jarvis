# J.A.R.V.I.S. v5.0 — Just A Rather Very Intelligent System

> "Good evening, Sir. All systems are online."

A complete autonomous AI operating system for a personal laptop.
Built by Hitansu Parichha | Nisum Technologies | April 2026

## Quick Start

```bash
git clone https://github.com/YOUR_REPO/jarvis.git
cd jarvis
./setup.sh
uvicorn core_engine.gateway:app --reload
```

## Phase 1 — What's Built

- ✅ FastAPI gateway on port 8000
- ✅ Complexity router (score 1-10)
- ✅ OFFLINE/ONLINE mode manager with Vertex AI fallback
- ✅ Expandable agent registry (13 agents defined)
- ✅ Security sandbox skeleton (Phase 2 will add enforcement)
- ✅ Memory system stubs (Phase 4 will activate ChromaDB)
- ✅ Voice engine stubs (Phase 3 will add F5-TTS + Whisper)
- ✅ Screen engine stubs (Phase 5 will add live vision)
- ✅ MCP registry (Phase 8 will activate all tools)
- ✅ JARVIS_CORE.md persona file
- ✅ Full pytest test suite (30+ tests)

## API

```
POST /chat          — Send a message to JARVIS
GET  /status        — System status
GET  /agents        — Agent registry (all 13 agents)
POST /agents/reload — Hot-reload agents.json without restart
POST /mode          — Switch OFFLINE/ONLINE
GET  /health        — Health check
POST /memory/query  — Query memory (Phase 4 stub)
POST /screen/capture — Capture screen (Phase 5 stub)
POST /control/override — Return control to user (Phase 6 stub)
```

## Models Required

```bash
ollama pull gemma4:e4b          # ~10 GB — Always-on backbone
ollama pull gemma4:26b          # ~18 GB — Code + Vision specialist
ollama pull qwen3.5:27b-q4_K_M # ~16 GB — Manager/Planner
```

## RAM Budget

| State               | RAM Used | Free   |
|---------------------|----------|--------|
| Baseline (macOS)    | ~19.6 GB | ~28 GB |
| + gemma4:e4b        | ~29.6 GB | ~18 GB |
| + Code Task (26b)   | ~37.6 GB | ~10 GB |
| + Plan Task (27b)   | ~35.6 GB | ~12 GB |
| ⚠️ BLOCKED: Both   | ~53.6 GB |  N/A   |

**Critical Rule:** `gemma4:26b` (~18 GB) and `qwen3.5:27b-q4_K_M` (~16 GB) must
NEVER be loaded simultaneously. The gateway enforces this with a hard RAM guard.

## The Agent Team (13 Agents)

| Agent | Model (Offline) | Always-on? |
|-------|----------------|------------|
| Receptionist / Router | gemma4:e4b | Yes |
| Manager / Planner | qwen3.5:27b-q4_K_M | No |
| Code Specialist | gemma4:26b | No |
| Screen Vision (Passive) | gemma4:e4b | Yes |
| Screen Vision (Deep) | gemma4:26b | No |
| Browser / Shopping | qwen3.5:27b-q4_K_M | No |
| Research | qwen3.5:27b-q4_K_M | No |
| Auditor / QA | gemma4:e4b | Yes |
| Memory Distiller | gemma4:e4b | Yes |
| File Manager | qwen3.5:27b-q4_K_M | No |
| Voice Triage | gemma4:e4b | Yes (ALWAYS LOCAL) |
| System Control | qwen3.5:27b-q4_K_M | No |
| Communication | qwen3.5:27b-q4_K_M | No |

## Phases

| Phase | Status     | Description                     |
|-------|------------|---------------------------------|
| 1     | ✅ DONE    | Foundation, Routing, Dual-Mode  |
| 2     | ⏳ Next    | Enterprise Security             |
| 3     | ⏳         | Voice Engine (TTS/STT/Wake)     |
| 4     | ⏳         | Infinite Memory                 |
| 5     | ⏳         | Screen Vision                   |
| 6     | ⏳         | Computer Control                |
| 7     | ⏳         | Multi-Agent Team                |
| 8     | ⏳         | MCP Skills Library              |
| 9     | ⏳         | Persona Engine                  |
| 10    | ⏳         | Packaging & Deployment          |

## Privacy Rules

- **Voice Triage is ALWAYS local** — even in ONLINE mode, voice commands never go to Vertex AI.
- **API keys are invisible to all agents** — ModeManager handles credentials internally.
- **Clipboard access is explicit-only** — only when user says "use what's in my clipboard."
- **File deletions require double confirmation** — no silent deletes, ever.
- **sudo/admin commands are completely blocked** — the sandbox policy prevents this at every level.

## Directory Structure

```
jarvis/
├── core_engine/        # FastAPI gateway, router, mode manager, agent registry
├── screen_engine/      # Screen capture, vision, control, passive watcher
├── voice_engine/       # TTS (F5-TTS/Chatterbox/Kokoro), STT (Whisper), Wake Word
├── memory_vault/       # ChromaDB store, nightly distiller, conversation logs
├── skills_mcp/         # MCP server registry (8 servers, activated Phase 8)
├── sandbox/            # Security executor, audit log, security policy YAML
├── prompts/            # System prompt files for all 13 agents
├── tests/              # pytest test suite (30+ tests across 4 files)
├── JARVIS_CORE.md      # Persona soul file — prepended to every agent prompt
├── .env.example        # Master config template for all 10 phases
├── requirements.txt    # All Python dependencies
└── setup.sh            # Cross-platform setup script
```
