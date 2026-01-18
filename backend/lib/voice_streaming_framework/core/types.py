"""
Core types and data structures for the voice streaming framework.

These types are used across all components to ensure consistent interfaces.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime


class AudioFormat(Enum):
    """Supported audio formats."""
    PCM = "pcm"          # Raw PCM (16-bit, mono)
    WAV = "wav"          # WAV container
    MP3 = "mp3"          # MP3 compressed
    WEBM = "webm"        # WebM container (Opus)
    OGG = "ogg"          # Ogg Vorbis/Opus
    OPUS = "opus"        # Raw Opus


@dataclass
class AudioChunk:
    """
    A chunk of audio data with metadata.

    Used throughout the pipeline for consistent audio handling.
    """
    data: bytes
    format: AudioFormat = AudioFormat.PCM
    sample_rate: int = 16000
    channels: int = 1
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    sequence: int = 0
    is_final: bool = False  # Last chunk in a stream

    @property
    def duration_ms(self) -> float:
        """Estimate duration in milliseconds (for PCM only)."""
        if self.format == AudioFormat.PCM:
            # 16-bit = 2 bytes per sample
            samples = len(self.data) / 2 / self.channels
            return (samples / self.sample_rate) * 1000
        return 0.0


class MessageRole(Enum):
    """Role of a message in conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    """
    A message in a conversation.

    Compatible with OpenAI-style message format.
    """
    role: MessageRole
    content: str
    name: Optional[str] = None  # For tool messages
    tool_call_id: Optional[str] = None  # For tool responses
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to OpenAI-compatible dict format."""
        d = {"role": self.role.value, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def system(cls, content: str) -> "Message":
        """Create a system message."""
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        """Create a user message."""
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> "Message":
        """Create an assistant message."""
        return cls(role=MessageRole.ASSISTANT, content=content)


class StreamingEventType(Enum):
    """Types of events during voice streaming."""
    # ASR events
    ASR_START = "asr_start"
    ASR_PARTIAL = "asr_partial"  # Partial transcript
    ASR_COMPLETE = "asr_complete"
    ASR_ERROR = "asr_error"

    # LLM events
    LLM_START = "llm_start"
    LLM_TOKEN = "llm_token"  # Single token
    LLM_SENTENCE = "llm_sentence"  # Complete sentence (for TTS)
    LLM_COMPLETE = "llm_complete"
    LLM_ERROR = "llm_error"

    # TTS events
    TTS_START = "tts_start"
    TTS_AUDIO = "tts_audio"  # Audio chunk ready
    TTS_COMPLETE = "tts_complete"
    TTS_ERROR = "tts_error"

    # Session events
    SESSION_START = "session_start"
    SESSION_END = "session_end"
    INTERRUPT = "interrupt"
    ERROR = "error"


@dataclass
class StreamingEvent:
    """
    An event emitted during voice streaming.

    Used for monitoring, logging, and callbacks.
    """
    type: StreamingEventType
    session_id: str
    data: Any = None
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    error: Optional[str] = None


@dataclass
class SessionState:
    """
    State of a voice session.

    Tracks conversation history and session metadata.
    """
    session_id: str
    user_id: str
    messages: list = field(default_factory=list)  # List[Message]
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=lambda: datetime.now().timestamp())
    is_active: bool = True

    # Runtime state
    is_speaking: bool = False  # TTS currently playing
    is_listening: bool = False  # ASR currently processing
    pending_interrupt: bool = False

    def add_message(self, message: Message) -> None:
        """Add a message to conversation history."""
        self.messages.append(message)

    def get_messages_as_dicts(self) -> list:
        """Get messages in OpenAI-compatible format."""
        return [m.to_dict() for m in self.messages]

    def clear_history(self) -> None:
        """Clear conversation history (keep system message if present)."""
        system_msgs = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        self.messages = system_msgs
