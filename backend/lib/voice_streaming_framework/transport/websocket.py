"""
WebSocket transport for audio streaming.

A simpler alternative to WebRTC that uses base64-encoded audio over WebSocket.
Higher latency than WebRTC but easier to deploy and debug.
"""

import asyncio
import base64
import json
import logging
from typing import Any, Callable, Dict, Optional

from .base import BaseTransport, TransportConfig
from ..core.types import AudioChunk, AudioFormat

logger = logging.getLogger(__name__)


class WebSocketTransport(BaseTransport):
    """
    WebSocket-based audio transport.

    Sends audio as base64-encoded data over WebSocket messages.
    Simpler than WebRTC but with higher latency.

    Message format (server → client):
        {
            "event": "audio",
            "data": {
                "audio": "<base64 encoded audio>",
                "format": "pcm",
                "sample_rate": 16000,
                "sequence": 0,
                "is_final": false
            }
        }

    Message format (client → server):
        {
            "event": "audio_chunk",
            "audio": "<base64 encoded audio>"
        }

    Example:
        transport = WebSocketTransport()

        # In WebSocket handler:
        await transport.connect(session_id, websocket, on_audio_received)

        # Send audio
        await transport.send_audio(session_id, audio_chunk)
    """

    def __init__(self, config: Optional[TransportConfig] = None):
        """
        Initialize WebSocket transport.

        Args:
            config: Optional transport configuration
        """
        super().__init__(config)
        self._websockets: Dict[str, Any] = {}
        self._audio_callbacks: Dict[str, Callable] = {}

    async def connect(
        self,
        session_id: str,
        websocket: Any,
        on_audio_received: Optional[Callable[[str, bytes], None]] = None,
    ) -> None:
        """
        Register a session for WebSocket audio transport.

        Args:
            session_id: Session identifier
            websocket: WebSocket connection
            on_audio_received: Callback when audio is received from client
        """
        self._websockets[session_id] = websocket
        self._sessions[session_id] = {"connected": True}

        if on_audio_received:
            self._audio_callbacks[session_id] = on_audio_received

        logger.info(f"WebSocket transport connected for session {session_id[:8]}")

    async def disconnect(self, session_id: str) -> None:
        """
        Close WebSocket connection for a session.

        Args:
            session_id: Session to disconnect
        """
        self._websockets.pop(session_id, None)
        self._sessions.pop(session_id, None)
        self._audio_callbacks.pop(session_id, None)
        logger.info(f"WebSocket transport disconnected for session {session_id[:8]}")

    async def send_audio(self, session_id: str, chunk: AudioChunk) -> None:
        """
        Send audio chunk over WebSocket.

        Args:
            session_id: Target session
            chunk: Audio data to send
        """
        websocket = self._websockets.get(session_id)
        if not websocket:
            logger.warning(f"No WebSocket for session {session_id[:8]}")
            return

        try:
            message = {
                "event": "audio",
                "data": {
                    "audio": base64.b64encode(chunk.data).decode("utf-8"),
                    "format": chunk.format.value,
                    "sample_rate": chunk.sample_rate,
                    "channels": chunk.channels,
                    "sequence": chunk.sequence,
                    "is_final": chunk.is_final,
                }
            }
            await websocket.send_text(json.dumps(message))

        except Exception as e:
            logger.error(f"Failed to send audio to {session_id[:8]}: {e}")

    async def send_message(self, session_id: str, message: Dict) -> None:
        """
        Send a JSON message over WebSocket.

        Args:
            session_id: Target session
            message: Message dict to send
        """
        websocket = self._websockets.get(session_id)
        if not websocket:
            return

        try:
            await websocket.send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message to {session_id[:8]}: {e}")

    async def handle_message(self, session_id: str, message: str) -> None:
        """
        Handle incoming WebSocket message.

        Extracts audio data and calls the audio callback if registered.

        Args:
            session_id: Source session
            message: Raw message string
        """
        try:
            data = json.loads(message)
            event = data.get("event")

            if event == "audio_chunk":
                audio_b64 = data.get("audio")
                if audio_b64 and session_id in self._audio_callbacks:
                    audio_bytes = base64.b64decode(audio_b64)
                    await self._audio_callbacks[session_id](session_id, audio_bytes)

        except Exception as e:
            logger.error(f"Failed to handle message from {session_id[:8]}: {e}")

    async def is_connected(self, session_id: str) -> bool:
        """
        Check if WebSocket is connected.

        Args:
            session_id: Session to check

        Returns:
            True if connected, False otherwise
        """
        websocket = self._websockets.get(session_id)
        if not websocket:
            return False

        # Check WebSocket state (framework-specific)
        try:
            # For Starlette/FastAPI
            from starlette.websockets import WebSocketState
            return websocket.client_state == WebSocketState.CONNECTED
        except ImportError:
            # Fallback: assume connected if websocket exists
            return True

    async def flush(self, session_id: str) -> None:
        """
        Flush is a no-op for WebSocket transport.

        WebSocket sends messages immediately without buffering.
        """
        pass
