"""
Base class for audio transport layers.

Transport layers handle the delivery of audio data between server and client.
Different transports (WebRTC, WebSocket) have different trade-offs.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, AsyncIterator, Callable, Dict, Optional

from ..core.types import AudioChunk


@dataclass
class TransportConfig:
    """Configuration for transport layers."""
    # Audio settings
    sample_rate: int = 48000  # Opus standard
    channels: int = 1
    frame_duration_ms: int = 20  # 20ms frames

    # Buffer settings
    max_buffer_frames: int = 50  # ~1 second at 20ms/frame

    # ICE servers for WebRTC (ignored by other transports)
    ice_servers: Optional[list] = None


class BaseTransport(ABC):
    """
    Abstract base class for audio transports.

    Transports handle the real-time delivery of audio between server and client.
    They abstract away the underlying protocol (WebRTC, WebSocket, etc.).

    Example:
        class MyTransport(BaseTransport):
            async def connect(self, session_id: str, websocket: Any) -> None:
                # Set up connection
                pass

            async def send_audio(self, session_id: str, chunk: AudioChunk) -> None:
                # Send audio to client
                pass
    """

    def __init__(self, config: Optional[TransportConfig] = None):
        """
        Initialize transport.

        Args:
            config: Optional transport configuration
        """
        self.config = config or TransportConfig()
        self._sessions: Dict[str, Any] = {}

    @abstractmethod
    async def connect(
        self,
        session_id: str,
        websocket: Any,
        on_audio_received: Optional[Callable[[str, bytes], None]] = None,
    ) -> None:
        """
        Establish connection for a session.

        Args:
            session_id: Unique session identifier
            websocket: WebSocket connection from the web framework
            on_audio_received: Callback when audio is received from client
        """
        pass

    @abstractmethod
    async def disconnect(self, session_id: str) -> None:
        """
        Close connection for a session.

        Args:
            session_id: Session to disconnect
        """
        pass

    @abstractmethod
    async def send_audio(self, session_id: str, chunk: AudioChunk) -> None:
        """
        Send audio chunk to client.

        Args:
            session_id: Target session
            chunk: Audio data to send
        """
        pass

    async def send_audio_stream(
        self,
        session_id: str,
        audio_stream: AsyncIterator[bytes]
    ) -> None:
        """
        Send a stream of audio chunks.

        Default implementation sends each chunk sequentially.
        Override for optimized streaming.

        Args:
            session_id: Target session
            audio_stream: Async iterator of audio bytes
        """
        sequence = 0
        async for audio_bytes in audio_stream:
            chunk = AudioChunk(
                data=audio_bytes,
                sequence=sequence
            )
            await self.send_audio(session_id, chunk)
            sequence += 1

    @abstractmethod
    async def is_connected(self, session_id: str) -> bool:
        """
        Check if session is connected.

        Args:
            session_id: Session to check

        Returns:
            True if connected, False otherwise
        """
        pass

    async def flush(self, session_id: str) -> None:
        """
        Flush any buffered audio for a session.

        Override if the transport buffers audio.

        Args:
            session_id: Session to flush
        """
        pass

    def get_name(self) -> str:
        """
        Get transport name.

        Returns:
            Human-readable transport name
        """
        return self.__class__.__name__
