# Voice Agent Backend Server Makefile
# Using uv for Python package management

.PHONY: help install run-server stop-servers

# Default target
help:
	@echo "Voice Agent Backend Server - Available Commands:"
	@echo ""
	@echo "Installation:"
	@echo "  install              Install production dependencies (lightweight, for Render)"
	@echo ""
	@echo "Server:"
	@echo "  run-server           Start FastAPI development server (with local ASR model)"
	@echo ""
	@echo "Utilities:"
	@echo "  stop-servers         Stop all running backend servers"

# Install dependencies (creates .venv automatically)
install:
	@echo "Installing dependencies with uv..."
	@uv sync
	@echo "✅ Dependencies installed in .venv"
	@echo "✅ Ready to run! Use: make run-server"

# Run backend server (automatically uses .venv from uv)
run-server:
	@echo "Starting backend server..."
	@echo "🎙️  Voice Agent Backend Server"
	@echo "📍 Location: backend/"
	@echo "🔗 WebSocket: ws://localhost:8000/ws"
	@echo "📖 Health: http://localhost:8000/health"
	@echo ""
	@cd backend && uv run uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Stop all running servers
stop-servers:
	@echo "🛑 Stopping all running servers..."
	@lsof -ti :8000 | xargs kill -9 2>/dev/null || echo "No backend server on port 8000"
	@pkill -f "uvicorn" 2>/dev/null || echo "No uvicorn processes"
	@echo "✅ All servers stopped"
