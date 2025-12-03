"""
Streaming Handler for TTS Audio

Handles streaming TTS audio generation and delivery.
"""

import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class StreamingHandler:
    """
    Handler for streaming TTS audio to WebRTC.

    This class coordinates between:
    - TTS provider (Edge TTS, etc.)
    - Session manager (for WebRTC streaming)
    - Agent (for context)
    """

    def __init__(self, session_id: str, tts_provider, agent):
        """
        Initialize streaming handler.

        Args:
            session_id: Session identifier
            tts_provider: TTS provider instance
            agent: Agent instance (for context)
        """
        self.session_id = session_id
        self.tts_provider = tts_provider
        self.agent = agent

    async def stream_tts_audio(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream TTS audio chunks for given text.

        Args:
            text: Text to synthesize

        Yields:
            Audio chunks (MP3 format from Edge TTS)
        """
        try:
            logger.info(f"🎵 Streaming TTS for session {self.session_id[:8]}... ({len(text)} chars)")

            chunk_count = 0
            async for audio_chunk in self.tts_provider.stream_audio(text):
                chunk_count += 1
                yield audio_chunk

            logger.info(f"✅ Streamed {chunk_count} TTS chunks for session {self.session_id[:8]}...")

        except Exception as e:
            logger.error(f"❌ Error streaming TTS audio: {e}")
            raise
