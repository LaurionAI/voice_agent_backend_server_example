"""
Voice Streaming Framework
=========================

A standalone library for building real-time voice AI agents.

This framework provides a complete abstraction layer between LLM APIs
and application prompts, with streaming support for low-latency responses.

Key Features:
- Streaming LLM → TTS for low-latency voice output
- Pluggable ASR, LLM, TTS, and transport providers
- LangGraph integration for complex agent workflows
- WebRTC and WebSocket transport options

Quick Start:
    from voice_streaming_framework import (
        StreamingVoicePipeline,
        OpenAICompatibleLLM,
        LLMConfig,
        EdgeTTS,
        TTSConfig,
        HFSpaceASR,
        WebRTCTransport,
    )

    pipeline = StreamingVoicePipeline(
        asr=HFSpaceASR(space_name="your-space"),
        llm=OpenAICompatibleLLM(
            config=LLMConfig(model="gpt-4", system_prompt="You are helpful."),
            api_key="sk-..."
        ),
        tts=EdgeTTS(TTSConfig(voice="en-US-JennyNeural")),
        transport=WebRTCTransport(),
    )

    # Process audio
    await pipeline.process(session_id, audio_bytes)

Components:
- pipeline: Main orchestration (StreamingVoicePipeline)
- asr: Speech-to-text providers (HFSpaceASR, WhisperASR)
- llm: LLM providers (OpenAICompatibleLLM, LangGraphAdapter)
- tts: Text-to-speech providers (EdgeTTS, GPTSoVITS)
- transport: Audio delivery (WebRTCTransport, WebSocketTransport)
- text: Text processing (SentenceAggregator)
- audio: Audio processing (AudioConverter, AudioValidator)
- core: Core types (AudioChunk, Message, etc.)
"""

__version__ = "0.2.0"

# Core types
from .core.types import (
    AudioChunk,
    AudioFormat,
    Message,
    MessageRole,
    SessionState,
    StreamingEvent,
    StreamingEventType,
)

# Pipeline
from .pipeline import StreamingVoicePipeline, PipelineConfig

# ASR providers
from .asr import BaseASRProvider, ASRConfig, HFSpaceASR, WhisperASR

# LLM providers
from .llm import BaseLLMProvider, LLMConfig, OpenAICompatibleLLM, LangGraphAdapter

# TTS providers
from .tts import BaseTTSProvider, TTSConfig, get_tts_provider

# Transport
from .transport import BaseTransport, TransportConfig, WebRTCTransport, WebSocketTransport

# Text processing
from .text import SentenceAggregator, AggregatorConfig

# Audio processing
from .audio import AudioConverter, AudioValidator, get_converter

# Legacy exports (for backward compatibility)
from .audio import StreamingPipeline
from .server import VoiceSessionManager

__all__ = [
    # Version
    "__version__",

    # Core types
    "AudioChunk",
    "AudioFormat",
    "Message",
    "MessageRole",
    "SessionState",
    "StreamingEvent",
    "StreamingEventType",

    # Pipeline
    "StreamingVoicePipeline",
    "PipelineConfig",

    # ASR
    "BaseASRProvider",
    "ASRConfig",
    "HFSpaceASR",
    "WhisperASR",

    # LLM
    "BaseLLMProvider",
    "LLMConfig",
    "OpenAICompatibleLLM",
    "LangGraphAdapter",

    # TTS
    "BaseTTSProvider",
    "TTSConfig",
    "get_tts_provider",

    # Transport
    "BaseTransport",
    "TransportConfig",
    "WebRTCTransport",
    "WebSocketTransport",

    # Text processing
    "SentenceAggregator",
    "AggregatorConfig",

    # Audio
    "AudioConverter",
    "AudioValidator",
    "get_converter",

    # Legacy (backward compatibility)
    "StreamingPipeline",
    "VoiceSessionManager",
]
