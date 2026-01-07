#!/bin/bash

# Monitor server logs for audio streaming flow
# Usage: ./monitor_audio_flow.sh [session_id_prefix]
#
# This script helps diagnose "no audio output" issues by monitoring
# server logs for critical audio streaming checkpoints.

SESSION_PREFIX=${1:-""}

echo "🔍 Monitoring Audio Streaming Flow"
echo "=================================="
echo ""

if [ -z "$SESSION_PREFIX" ]; then
    echo "Monitoring ALL sessions (no filter)"
    echo "Tip: Pass session ID prefix to filter: ./monitor_audio_flow.sh abc123"
else
    echo "Filtering for session: ${SESSION_PREFIX}..."
fi

echo ""
echo "📋 Watching for these checkpoints:"
echo "   1. WebRTC Setup (webrtc_enabled=True)"
echo "   2. TTS Streaming Start (Routing TTS to WebRTC)"
echo "   3. FFmpeg Process (Starting FFmpeg)"
echo "   4. MP3 Chunks (Edge-TTS completed)"
echo "   5. PCM Chunks (PCM chunk #)"
echo "   6. WebRTC Track (CHECKPOINT 10)"
echo "   7. Completion (streaming_complete)"
echo ""
echo "Press Ctrl+C to stop"
echo "=================================="
echo ""

# Function to colorize output
colorize() {
    local color=$1
    local text=$2

    case $color in
        red)    echo -e "\033[0;31m${text}\033[0m" ;;
        green)  echo -e "\033[0;32m${text}\033[0m" ;;
        yellow) echo -e "\033[0;33m${text}\033[0m" ;;
        blue)   echo -e "\033[0;34m${text}\033[0m" ;;
        *)      echo "$text" ;;
    esac
}

# Monitor logs
tail -f /tmp/voice_agent.log 2>/dev/null | while read -r line; do
    # Skip if filtering and line doesn't match session
    if [ -n "$SESSION_PREFIX" ] && [[ ! "$line" =~ $SESSION_PREFIX ]]; then
        continue
    fi

    # Checkpoint 1: WebRTC Setup
    if [[ "$line" =~ "webrtc_enabled=True" ]]; then
        colorize green "✅ [1] WebRTC Setup: $line"

    elif [[ "$line" =~ "webrtc_enabled=False" ]]; then
        colorize red "❌ [1] WebRTC NOT enabled: $line"

    # Checkpoint 2: TTS Streaming Start
    elif [[ "$line" =~ "Routing TTS to WebRTC" ]]; then
        colorize green "✅ [2] TTS Streaming Started: $line"

    # Checkpoint 3: FFmpeg Process
    elif [[ "$line" =~ "Starting FFmpeg input stream" ]]; then
        colorize green "✅ [3] FFmpeg Process Started: $line"

    # Checkpoint 4: MP3 Chunks
    elif [[ "$line" =~ "Edge-TTS completed" ]]; then
        colorize green "✅ [4] TTS Audio Generated: $line"

    # Checkpoint 5: PCM Chunks
    elif [[ "$line" =~ "PCM chunk #" ]]; then
        colorize blue "📤 [5] PCM Chunk Sent: $line"

    # Checkpoint 6: WebRTC Track Push
    elif [[ "$line" =~ "CHECKPOINT 10" ]]; then
        colorize blue "🔍 [6] WebRTC Track Push: $line"

    # Checkpoint 7: Streaming Complete
    elif [[ "$line" =~ "streaming_complete" ]] || [[ "$line" =~ "WebRTC TTS streaming complete" ]]; then
        colorize green "✅ [7] Streaming Complete: $line"

    # Errors
    elif [[ "$line" =~ "webrtc_not_ready" ]]; then
        colorize red "❌ ERROR: WebRTC Not Ready: $line"

    elif [[ "$line" =~ "ERROR" ]] && [[ "$line" =~ "WebRTC" || "$line" =~ "TTS" || "$line" =~ "FFmpeg" ]]; then
        colorize red "❌ ERROR: $line"

    # Other relevant logs
    elif [[ "$line" =~ "session=" ]]; then
        colorize yellow "ℹ️  $line"
    fi
done

# If tail failed (log file doesn't exist), show instructions
if [ $? -ne 0 ]; then
    echo ""
    colorize yellow "⚠️  Log file not found at /tmp/voice_agent.log"
    echo ""
    echo "To enable logging to file, run the server with:"
    echo "  uvicorn main:app --log-config logging.yaml"
    echo ""
    echo "Or create a simple logging config:"
    echo "  export VOICE_AGENT_LOG_FILE=/tmp/voice_agent.log"
    echo "  uvicorn main:app 2>&1 | tee /tmp/voice_agent.log"
    echo ""
    echo "Or just monitor stdout:"
    echo "  tail -f <(uvicorn main:app)"
fi
