"""Edge-TTS provider implementation."""

import logging
from typing import AsyncIterator, Optional
from .base import TTSProvider, TTSConfig

logger = logging.getLogger(__name__)

try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    EDGE_TTS_AVAILABLE = False
    logger.warning("edge-tts not installed. Run: uv pip install edge-tts")


class EdgeTTSProvider(TTSProvider):
    """
    Edge-TTS provider using Microsoft Edge's TTS service.

    Free, no API key required, high-quality neural voices.
    Output: MP3 format (compatible with FFmpeg pipeline).
    """

    def __init__(self, config: Optional[TTSConfig] = None):
        super().__init__(config)

        if not EDGE_TTS_AVAILABLE:
            raise RuntimeError(
                "edge-tts not installed. Install with: uv pip install edge-tts"
            )

    async def stream_audio(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream TTS audio as MP3 chunks.

        Args:
            text: Text to convert to speech

        Yields:
            MP3 audio chunks (bytes)

        Raises:
            RuntimeError: If TTS generation fails
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to TTS, skipping")
            return

        try:
            logger.debug(
                f"🔊 Starting Edge-TTS for text (length: {len(text)}): {text[:50]}..."
            )

            # Create communicate object
            communicate = edge_tts.Communicate(
                text,
                self.config.voice,
                rate=self.config.rate
            )

            buffer = bytearray()
            chunk_count = 0

            # Stream MP3 chunks from Edge-TTS
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    buffer.extend(chunk["data"])

                    # Yield chunks of specified size
                    while len(buffer) >= self.config.chunk_size:
                        yield bytes(buffer[:self.config.chunk_size])
                        chunk_count += 1
                        buffer = buffer[self.config.chunk_size:]

            # Yield remaining data
            if buffer:
                yield bytes(buffer)
                chunk_count += 1

            logger.info(f"✅ Edge-TTS completed: {chunk_count} MP3 chunks generated")

        except Exception as e:
            error_msg = str(e)

            # Provide helpful error messages
            if "No audio was received" in error_msg:
                logger.warning(f"⚠️ Edge-TTS: No audio received")
                logger.info(f"   Text: {text[:100]}")
                logger.info(f"   Voice: {self.config.voice}")
                logger.info(f"   Possible causes:")
                logger.info(f"   1. Network connectivity issues")
                logger.info(f"   2. Microsoft service temporarily unavailable")
                logger.info(f"   3. Invalid voice name")
            elif "SSL" in error_msg or "certificate" in error_msg.lower():
                logger.warning(f"⚠️ Edge-TTS SSL error: {error_msg}")
                logger.info(f"   Solutions:")
                logger.info(f"   1. Update certifi: uv pip install --upgrade certifi")
                logger.info(f"   2. Update edge-tts: uv pip install --upgrade edge-tts")
            else:
                logger.error(f"❌ Edge-TTS error: {e}")

            raise RuntimeError(f"Edge-TTS failed: {error_msg}")

    async def synthesize_full(self, text: str) -> bytes:
        """
        Synthesize complete audio file.

        Args:
            text: Text to convert to speech

        Returns:
            Complete MP3 audio bytes
        """
        chunks = []
        async for chunk in self.stream_audio(text):
            chunks.append(chunk)

        return b''.join(chunks)

    def get_available_voices(self) -> list[dict]:
        """
        Get list of available Edge-TTS voices.

        Returns:
            List of voice dicts with keys: id, name, language, gender

        Note: This is a cached list. Run edge-tts --list-voices for full list.
        """
        # Common voices for quick reference
        # Full list: https://speech.microsoft.com/portal/voicegallery
        return [
            # US English
            {
                "id": "en-US-AriaNeural",
                "name": "Aria (Female, US)",
                "language": "en-US",
                "gender": "Female"
            },
            {
                "id": "en-US-GuyNeural",
                "name": "Guy (Male, US)",
                "language": "en-US",
                "gender": "Male"
            },
            {
                "id": "en-US-JennyNeural",
                "name": "Jenny (Female, US)",
                "language": "en-US",
                "gender": "Female"
            },
            # UK English
            {
                "id": "en-GB-SoniaNeural",
                "name": "Sonia (Female, UK)",
                "language": "en-GB",
                "gender": "Female"
            },
            {
                "id": "en-GB-RyanNeural",
                "name": "Ryan (Male, UK)",
                "language": "en-GB",
                "gender": "Male"
            },
            # Spanish
            {
                "id": "es-ES-ElviraNeural",
                "name": "Elvira (Female, Spain)",
                "language": "es-ES",
                "gender": "Female"
            },
            # French
            {
                "id": "fr-FR-DeniseNeural",
                "name": "Denise (Female, France)",
                "language": "fr-FR",
                "gender": "Female"
            },
            # German
            {
                "id": "de-DE-KatjaNeural",
                "name": "Katja (Female, Germany)",
                "language": "de-DE",
                "gender": "Female"
            },
            # Chinese
            {
                "id": "zh-CN-XiaoxiaoNeural",
                "name": "Xiaoxiao (Female, China)",
                "language": "zh-CN",
                "gender": "Female"
            },
        ]
