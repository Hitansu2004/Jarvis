#!/bin/bash
# =============================================================================
# J.A.R.V.I.S. v5.0 — Cross-Platform Setup Script
# Author: Hitansu Parichha | Nisum Technologies
# =============================================================================

set -e

echo ""
echo "============================================================"
echo "  J.A.R.V.I.S. v5.0 — Setup Script"
echo "  Just A Rather Very Intelligent System"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Detect OS
# ---------------------------------------------------------------------------
OS="unknown"
if [[ "$OSTYPE" == "darwin"* ]]; then
    OS="macos"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Check for WSL
    if grep -qi microsoft /proc/version 2>/dev/null; then
        OS="wsl"
    else
        OS="linux"
    fi
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    OS="windows"
fi

echo "✓ Detected OS: $OS"

# ---------------------------------------------------------------------------
# Step 2: Check Python version (requires 3.11+)
# ---------------------------------------------------------------------------
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    if command -v python &> /dev/null; then
        PYTHON_CMD="python"
    else
        echo "✗ Python not found. Please install Python 3.11+."
        exit 1
    fi
fi

PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.major)")
PYTHON_MINOR=$($PYTHON_CMD -c "import sys; print(sys.version_info.minor)")

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 11 ]); then
    echo "✗ Python 3.11+ required. Found: $PYTHON_VERSION"
    echo "  Install from: https://python.org/downloads"
    exit 1
fi
echo "✓ Python version: $PYTHON_VERSION"

# ---------------------------------------------------------------------------
# Step 3: Create virtual environment
# ---------------------------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "→ Creating Python virtual environment at .venv/ ..."
    $PYTHON_CMD -m venv .venv
    echo "✓ Virtual environment created."
else
    echo "✓ Virtual environment already exists."
fi

# Activate virtual environment
if [ "$OS" = "windows" ]; then
    source .venv/Scripts/activate
else
    source .venv/bin/activate
fi
echo "✓ Virtual environment activated."

# ---------------------------------------------------------------------------
# Step 4: Install requirements
# ---------------------------------------------------------------------------
echo ""
echo "→ Installing Python dependencies from requirements.txt ..."
echo "  (This may take a few minutes on first run)"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo "✓ Python dependencies installed."

# ---------------------------------------------------------------------------
# Step 5: Copy .env.example to .env (if .env doesn't exist)
# ---------------------------------------------------------------------------
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "✓ .env created from .env.example — please fill in your values."
else
    echo "✓ .env already exists — skipping."
fi

# ---------------------------------------------------------------------------
# Step 6: Create required directories
# ---------------------------------------------------------------------------
echo ""
echo "→ Creating required directories ..."
mkdir -p memory_vault/logs
mkdir -p memory_vault/chroma_db
mkdir -p sandbox
mkdir -p prompts
mkdir -p voice_engine
mkdir -p models
echo "✓ Directories created."

# ---------------------------------------------------------------------------
# Step 7: Create sandbox/audit.log if it doesn't exist
# ---------------------------------------------------------------------------
if [ ! -f "sandbox/audit.log" ]; then
    touch sandbox/audit.log
    echo "✓ sandbox/audit.log created."
else
    echo "✓ sandbox/audit.log already exists."
fi

# ---------------------------------------------------------------------------
# Step 8: Check Ollama
# ---------------------------------------------------------------------------
echo ""
echo "→ Checking Ollama installation ..."

OLLAMA_RUNNING=false
if command -v ollama &> /dev/null; then
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        OLLAMA_RUNNING=true
        echo "✓ Ollama is installed and running."
    else
        echo "⚠ Ollama is installed but not running."
        echo "  Start with: ollama serve"
    fi
else
    echo "⚠ Ollama not found. Install from: https://ollama.com/download"
    if [ "$OS" = "macos" ]; then
        echo "  macOS: brew install ollama"
    elif [ "$OS" = "linux" ] || [ "$OS" = "wsl" ]; then
        echo "  Linux: curl -fsSL https://ollama.com/install.sh | sh"
    fi
fi

# ---------------------------------------------------------------------------
# Step 9: Pull Ollama models (if Ollama is running)
# ---------------------------------------------------------------------------
if [ "$OLLAMA_RUNNING" = true ]; then
    echo ""
    echo "→ Pulling JARVIS core models (this will download ~44 GB total)..."
    echo "  This is a one-time download. Each model is cached locally."
    echo ""
    echo "  Pulling gemma4:e4b (~10 GB — Always-on backbone) ..."
    ollama pull gemma4:e4b | tail -1
    echo "  Pulling gemma4:26b (~18 GB — Code + Vision specialist) ..."
    ollama pull gemma4:26b | tail -1
    echo "  Pulling qwen3.5:27b-q4_K_M (~16 GB — Manager/Planner) ..."
    ollama pull qwen3.5:27b-q4_K_M | tail -1
    echo "✓ All core models pulled."
fi

# ---------------------------------------------------------------------------
# Step 10: Check Node.js (Phase 8 MCP)
# ---------------------------------------------------------------------------
echo ""
echo "→ Checking Node.js installation (required for Phase 8 MCP) ..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d'.' -f1 | tr -d 'v')
    if [ "$NODE_MAJOR" -ge 18 ]; then
        echo "✓ Node.js $NODE_VERSION — OK for Phase 8 MCP."
    else
        echo "⚠ Node.js $NODE_VERSION found but Phase 8 requires Node.js 18+."
        echo "  Upgrade from: https://nodejs.org"
    fi
else
    echo "⚠ Node.js not found. Required for Phase 8 MCP servers."
    echo "  Install from: https://nodejs.org (LTS recommended)"
fi

# ---------------------------------------------------------------------------
# Step 11: Run pytest
# ---------------------------------------------------------------------------
echo ""
echo "→ Running Phase 1 test suite ..."
if python -m pytest tests/ -v --tb=short 2>&1; then
    echo ""
    echo "✓ All Phase 1 tests passed!"
else
    echo ""
    echo "⚠ Some tests failed. Review output above."
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  SETUP COMPLETE"
echo "============================================================"
echo ""
echo "  Boot command:"
echo "  uvicorn core_engine.gateway:app --reload"
echo ""
echo "  API Endpoints:"
echo "  GET  http://localhost:8000/health"
echo "  GET  http://localhost:8000/status"
echo "  GET  http://localhost:8000/agents"
echo "  POST http://localhost:8000/chat"
echo "  POST http://localhost:8000/mode"
echo ""
echo "  Next: Phase 2 — Enterprise Security & Safe Execution"
echo ""
echo "  \"J.A.R.V.I.S. v5.0 standing by, Sir.\""
echo ""
