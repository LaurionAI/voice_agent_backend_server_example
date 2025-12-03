"""GPT-SoVITS provider implementation (placeholder for future)."""

import logging
from typing import AsyncIterator, Optional
from .base import TTSProvider, TTSConfig

logger = logging.getLogger(__name__)


class GPTSoVITSProvider(TTSProvider):
    """
    GPT-SoVITS provider for custom voice cloning.

    Requires:
    - GPT-SoVITS server running locally or remotely
    - Reference audio for voice cloning
    - Custom model training (optional)

    Setup:
    1. Clone GPT-SoVITS: https://github.com/RVC-Boss/GPT-SoVITS
    2. Train model or use pretrained
    3. Start API server
    4. Configure endpoint in TTSConfig.provider_settings

    Output: MP3 format (compatible with FFmpeg pipeline).
    """

    def __init__(self, config: Optional[TTSConfig] = None):
        super().__init__(config)

        # Get GPT-SoVITS configuration
        self.api_endpoint = self.config.provider_settings.get(
            "api_endpoint", "http://localhost:9880"
        )
        self.reference_audio = self.config.provider_settings.get(
            "reference_audio", None
        )
        self.reference_text = self.config.provider_settings.get(
            "reference_text", None
        )

        if not self.reference_audio or not self.reference_text:
            raise ValueError(
                "GPT-SoVITS requires reference_audio and reference_text "
                "in config.provider_settings"
            )

        logger.info(f"🎙️ GPT-SoVITS provider initialized (endpoint: {self.api_endpoint})")

    async def stream_audio(self, text: str) -> AsyncIterator[bytes]:
        """
        Stream TTS audio as MP3 chunks.

        Args:
            text: Text to convert to speech

        Yields:
            MP3 audio chunks (bytes)

        Raises:
            RuntimeError: If TTS generation fails or service unavailable
        """
        if not text or not text.strip():
            logger.warning("Empty text provided to TTS, skipping")
            return

        try:
            import aiohttp

            logger.debug(f"🔊 GPT-SoVITS TTS for: {text[:50]}...")

            # Prepare request
            request_data = {
                "text": text,
                "text_language": self.config.language or "en",
                "refer_wav_path": self.reference_audio,
                "prompt_text": self.reference_text,
                "prompt_language": self.config.language or "en",
                # Request MP3 output
                "format": "mp3",
            }

            # Send request to GPT-SoVITS API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_endpoint}/tts",
                    json=request_data,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(
                            f"GPT-SoVITS API error {response.status}: {error_text}"
                        )

                    # Stream response in chunks
                    chunk_count = 0
                    async for chunk in response.content.iter_chunked(self.config.chunk_size):
                        yield chunk
                        chunk_count += 1

                    logger.info(f"✅ GPT-SoVITS completed: {chunk_count} MP3 chunks")

        except ImportError:
            raise RuntimeError(
                "aiohttp not installed. Run: uv pip install aiohttp"
            )
        except aiohttp.ClientConnectorError:
            raise RuntimeError(
                f"Cannot connect to GPT-SoVITS server at {self.api_endpoint}. "
                "Is the server running?"
            )
        except Exception as e:
            logger.error(f"❌ GPT-SoVITS error: {e}")
            raise RuntimeError(f"GPT-SoVITS failed: {str(e)}")

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
        Get list of available GPT-SoVITS voices.

        Returns:
            List of voice dicts (custom voices based on trained models)
        """
        # GPT-SoVITS voices are custom-trained
        # Return configured voice
        return [
            {
                "id": "custom",
                "name": "Custom Cloned Voice",
                "language": self.config.language or "en",
                "gender": "Custom",
                "reference_audio": self.reference_audio,
            }
        ]
