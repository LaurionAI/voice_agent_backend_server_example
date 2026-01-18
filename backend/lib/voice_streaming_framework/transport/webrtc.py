"""
WebRTC transport for low-latency audio streaming.

Uses aiortc for WebRTC peer connections with Opus audio codec.
Provides the lowest latency audio delivery for voice applications.
"""

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from .base import BaseTransport, TransportConfig
from ..core.types import AudioChunk, AudioFormat
from ..webrtc.manager import WebRTCManager

logger = logging.getLogger(__name__)


class WebRTCTransport(BaseTransport):
    """
    WebRTC-based audio transport.

    Features:
    - Ultra-low latency (< 100ms)
    - Opus codec (48kHz, mono)
    - ICE/STUN/TURN support for NAT traversal
    - Automatic connection recovery

    Requires:
    - WebRTC offer/answer negotiation via WebSocket signaling
    - ICE candidate exchange
    - FFmpeg for MP3→PCM conversion (if TTS outputs MP3)

    Example:
        transport = WebRTCTransport()

        # In WebSocket handler:
        await transport.connect(session_id, websocket)

        # Handle WebRTC signaling
        await transport.handle_offer(session_id, offer_sdp)
        await transport.handle_ice_candidate(session_id, candidate)

        # Send audio
        await transport.send_audio(session_id, audio_chunk)
    """

    def __init__(
        self,
        config: Optional[TransportConfig] = None,
        ice_servers_callback: Optional[Callable[[str], list]] = None,
    ):
        """
        Initialize WebRTC transport.

        Args:
            config: Optional transport configuration
            ice_servers_callback: Async callback to fetch ICE servers for a session
        """
        super().__init__(config)
        self._manager = WebRTCManager()
        self._ice_servers_callback = ice_servers_callback
        self._websockets: Dict[str, Any] = {}

    @property
    def manager(self) -> WebRTCManager:
        """Access the underlying WebRTC manager."""
        return self._manager

    async def connect(
        self,
        session_id: str,
        websocket: Any,
        on_audio_received: Optional[Callable[[str, bytes], None]] = None,
    ) -> None:
        """
        Register a session for WebRTC.

        Note: Actual WebRTC connection is established via handle_offer().
        This method just stores the WebSocket for signaling.

        Args:
            session_id: Session identifier
            websocket: WebSocket for signaling
            on_audio_received: Callback for received audio (not used in WebRTC)
        """
        self._websockets[session_id] = websocket
        self._sessions[session_id] = {"connected": False}
        logger.info(f"WebRTC transport registered for session {session_id[:8]}")

    async def disconnect(self, session_id: str) -> None:
        """
        Close WebRTC connection for a session.

        Args:
            session_id: Session to disconnect
        """
        await self._manager.close_peer_connection(session_id)
        self._websockets.pop(session_id, None)
        self._sessions.pop(session_id, None)
        logger.info(f"WebRTC transport disconnected for session {session_id[:8]}")

    async def handle_offer(
        self,
        session_id: str,
        sdp: str,
        type: str = "offer",
    ) -> Optional[Dict]:
        """
        Handle WebRTC offer and return answer.

        Args:
            session_id: Session identifier
            sdp: SDP offer from client
            type: SDP type (usually "offer")

        Returns:
            Dict with SDP answer, or None on error
        """
        # Get ICE servers if callback provided
        ice_servers = None
        if self._ice_servers_callback:
            try:
                ice_servers = await self._ice_servers_callback(session_id)
            except Exception as e:
                logger.warning(f"Failed to fetch ICE servers: {e}")

        # Use config ICE servers as fallback
        if not ice_servers and self.config.ice_servers:
            ice_servers = self.config.ice_servers

        answer = await self._manager.handle_offer(
            session_id, sdp, type, ice_servers=ice_servers
        )

        if answer:
            self._sessions[session_id] = {"connected": True}

        return answer

    async def handle_ice_candidate(
        self,
        session_id: str,
        candidate: Dict,
    ) -> None:
        """
        Handle ICE candidate from client.

        Args:
            session_id: Session identifier
            candidate: ICE candidate data
        """
        await self._manager.handle_ice_candidate(session_id, candidate)

    async def send_audio(self, session_id: str, chunk: AudioChunk) -> None:
        """
        Send audio chunk via WebRTC.

        Note: WebRTC expects PCM audio at 48kHz. If the chunk is in a
        different format, it should be converted before calling this.

        Args:
            session_id: Target session
            chunk: Audio data (should be PCM)
        """
        if chunk.format != AudioFormat.PCM:
            logger.warning(
                f"WebRTC expects PCM audio, got {chunk.format}. "
                "Convert audio before sending."
            )

        await self._manager.push_audio_chunk(session_id, chunk.data)

    async def is_connected(self, session_id: str) -> bool:
        """
        Check if WebRTC connection is established.

        Args:
            session_id: Session to check

        Returns:
            True if connected, False otherwise
        """
        if session_id not in self._manager.pcs:
            return False

        pc = self._manager.pcs[session_id]
        return pc.connectionState == "connected"

    async def wait_for_connection(
        self,
        session_id: str,
        timeout: float = 10.0
    ) -> bool:
        """
        Wait for WebRTC connection to be established.

        Args:
            session_id: Session to wait for
            timeout: Maximum wait time in seconds

        Returns:
            True if connected within timeout, False otherwise
        """
        return await self._manager.wait_for_track_ready(session_id, timeout)

    async def flush(self, session_id: str) -> None:
        """
        Flush audio buffer and replace track.

        Used when handling interruptions.

        Args:
            session_id: Session to flush
        """
        if session_id in self._manager.tracks:
            track = self._manager.tracks[session_id]
            await track.flush()

        # Replace track for clean state
        await self._manager.replace_audio_track(session_id)

    async def replace_track(self, session_id: str) -> None:
        """
        Replace the audio track with a fresh one.

        Useful after interruptions to ensure clean audio state.

        Args:
            session_id: Session to replace track for
        """
        await self._manager.replace_audio_track(session_id)
