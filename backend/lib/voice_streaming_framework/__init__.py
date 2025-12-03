"""Voice Streaming Framework - Generic Infrastructure for Voice Applications

This package contains all generic voice streaming infrastructure that can be
reused across different applications. It has ZERO dependencies on app-specific
logic (database, cache, LangGraph agent, etc.).

**Restructuring Note**:
Moved from `backend/app/framework/` → `backend/lib/voice_streaming_framework/`
to establish clear separation between reusable framework (lib/) and application logic (app/).

Design Philosophy:
- Framework is completely generic and reusable
- Application logic lives in `backend/app/voice_agent/`
- Uses dependency injection (callbacks) for app integration
- No direct imports from app/ - framework is self-contained

Components:
- webrtc: WebRTC audio streaming and track management
- asr: Speech-to-text providers (pluggable)
- tts: Text-to-speech providers (pluggable)
- audio: Audio processing pipeline
- server: Session management with callback-based integration

Usage:
    from backend.lib.voice_streaming_framework import StreamingPipeline, VoiceSessionManager
"""

__version__ = "0.1.0"

# Export main components
from .audio import StreamingPipeline
from .server import VoiceSessionManager

__all__ = [
    "StreamingPipeline",
    "VoiceSessionManager",
]
