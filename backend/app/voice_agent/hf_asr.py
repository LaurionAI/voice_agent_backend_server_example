"""
HuggingFace Space ASR for simple_backend.

Uses the SenseVoiceSmall model deployed on HuggingFace Spaces.
"""

import asyncio
import os
import tempfile
import logging
from typing import Optional

try:
    from gradio_client import Client, handle_file
    GRADIO_CLIENT_AVAILABLE = True
except ImportError:
    GRADIO_CLIENT_AVAILABLE = False
    Client = None  # Type stub for type hints

logger = logging.getLogger(__name__)


class HFSpaceASR:
    """HuggingFace Space ASR client."""

    def __init__(
        self,
        space_name: str = "hz6666/SenseVoiceSmall",
        hf_token: Optional[str] = None
    ):
        """
        Initialize HF Space ASR client.

        Args:
            space_name: HuggingFace Space name (user/space)
            hf_token: Optional HuggingFace token for private spaces
        """
        if not GRADIO_CLIENT_AVAILABLE:
            raise ImportError(
                "gradio_client not installed. "
                "Install with: uv sync"
            )

        self.space_name = space_name
        self.hf_token = hf_token or os.getenv("HF_TOKEN")
        self._client = None
        logger.info(f"HFSpaceASR initialized with space: {space_name}")

    def _get_client(self):
        """Get or create Gradio client."""
        if self._client is None:
            self._client = Client(
                self.space_name,
                token=self.hf_token
            )
            logger.info(f"✅ Connected to HF Space: {self.space_name}")

        return self._client

    async def transcribe(self, audio_bytes: bytes, **kwargs) -> str:
        """
        Transcribe audio from bytes.

        Args:
            audio_bytes: Audio data as bytes

        Returns:
            Transcription text
        """
        # Create temp file
        with tempfile.NamedTemporaryFile(
            suffix=".webm",
            delete=False
        ) as tmp_file:
            tmp_file.write(audio_bytes)
            tmp_path = tmp_file.name

        try:
            # Get client
            client = self._get_client()

            # Run prediction in executor to avoid blocking
            loop = asyncio.get_event_loop()
            transcription = await loop.run_in_executor(
                None,
                lambda: client.predict(
                    handle_file(tmp_path),
                    api_name="/predict"
                )
            )

            # Clean SenseVoice output format
            result = str(transcription)

            # Remove language tags, emotion tags, etc.
            # Format: <|en|><|NEUTRAL|><|Speech|><|woitn|>actual text
            if "<|woitn|>" in result:
                result = result.split("<|woitn|>", 1)[1].strip()
            elif "|>" in result:
                # Fallback: remove all tags
                parts = result.split("|>")
                result = parts[-1].strip() if parts else result

            logger.info(f"📝 Transcribed: {result}")
            return result

        except Exception as e:
            logger.error(f"❌ HF Space ASR error: {e}")
            raise
        finally:
            # Cleanup temp file
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
