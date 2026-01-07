#!/bin/bash

# Run all E2E tests for voice agent backend
# Usage: ./run_tests.sh [options]
#
# Options:
#   --fast    Skip test audio generation
#   --cov     Run with coverage report
#   --debug   Enable debug logging

set -e

cd "$(dirname "$0")/../../.."

echo "🧪 Voice Agent E2E Test Suite"
echo "=============================="
echo ""

# Parse arguments
SKIP_AUDIO=false
WITH_COVERAGE=false
DEBUG_MODE=false

for arg in "$@"; do
    case $arg in
        --fast)
            SKIP_AUDIO=true
            ;;
        --cov)
            WITH_COVERAGE=true
            ;;
        --debug)
            DEBUG_MODE=true
            ;;
        *)
            echo "Unknown option: $arg"
            exit 1
            ;;
    esac
done

# Generate test audio if needed
if [ "$SKIP_AUDIO" = false ]; then
    echo "🎤 Step 1: Generating test audio files..."
    uv run python backend/tests/e2e/generate_test_audio.py
    echo ""
else
    echo "⏩ Skipping audio generation (--fast mode)"
    echo ""
fi

# Run tests
echo "🧪 Step 2: Running E2E tests..."
echo ""

PYTEST_ARGS="backend/tests/e2e/ -v -s"

if [ "$WITH_COVERAGE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS --cov=backend --cov-report=html --cov-report=term"
fi

if [ "$DEBUG_MODE" = true ]; then
    PYTEST_ARGS="$PYTEST_ARGS --log-cli-level=DEBUG"
fi

uv run pytest $PYTEST_ARGS

echo ""
echo "✅ All E2E tests completed!"

if [ "$WITH_COVERAGE" = true ]; then
    echo ""
    echo "📊 Coverage report generated: htmlcov/index.html"
fi
