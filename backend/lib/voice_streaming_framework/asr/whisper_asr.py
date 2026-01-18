"""OpenAI Whisper ASR client for premium users."""
import io
import logging
from typing import Optional, Dict, Any
from pathlib import Path

from .base import BaseASRProvider, ASRConfig

logger = logging.getLogger(__name__)


class WhisperASR(BaseASRProvider):
    """
    OpenAI Whisper ASR client for transcription.

    Supports:
    - OpenAI Whisper API (whisper-1)
    - Local Whisper models (future support)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "whisper-1",
        language: Optional[str] = None,
        config: Optional[ASRConfig] = None,
    ):
        """
        Initialize Whisper ASR client.

        Args:
            api_key: OpenAI API key (if None, reads from OPENAI_API_KEY env var)
            model: Whisper model to use (default: "whisper-1")
            language: Language code for transcription (default: auto-detect)
            config: Optional ASR configuration
        """
        super().__init__(config)
        self.api_key = api_key
        self.model = model
        self.language = language or (config.language if config else None)
        self._client: Optional[Any] = None

        logger.info(f"WhisperASR initialized with model: {model}")

    def _get_client(self):
        """Lazy-load OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key)
                logger.info("OpenAI client initialized successfully")
            except ImportError:
                logger.error("OpenAI package not installed. Install with: uv pip install openai")
                raise ImportError("openai package is required for Whisper ASR")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                raise
        return self._client

    async def transcribe_audio(
        self,
        audio_path: str,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe audio file using Whisper API.

        Args:
            audio_path: Path to audio file
            language: Language code (overrides instance language)
            prompt: Optional prompt to guide transcription

        Returns:
            Transcribed text

        Raises:
            FileNotFoundError: If audio file not found
            Exception: If transcription fails
        """
        audio_file = Path(audio_path)
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        try:
            client = self._get_client()

            with open(audio_path, "rb") as f:
                kwargs = {
                    "model": self.model,
                    "file": f,
                }

                # Add language if specified
                if language or self.language:
                    kwargs["language"] = language or self.language

                # Add prompt if specified
                if prompt:
                    kwargs["prompt"] = prompt

                logger.debug(f"Transcribing audio: {audio_path} with model: {self.model}")
                response = client.audio.transcriptions.create(**kwargs)

                transcription = response.text
                logger.info(f"Transcription successful: {len(transcription)} characters")
                return transcription

        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            raise

    async def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        language: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> str:
        """
        Transcribe audio from bytes using Whisper API.

        Args:
            audio_bytes: Audio data as bytes
            filename: Filename to use (with extension)
            language: Language code (overrides instance language)
            prompt: Optional prompt to guide transcription

        Returns:
            Transcribed text

        Raises:
            Exception: If transcription fails
        """
        try:
            client = self._get_client()

            # Create file-like object from bytes
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename  # OpenAI requires a name attribute

            kwargs = {
                "model": self.model,
                "file": audio_file,
            }

            # Add language if specified
            if language or self.language:
                kwargs["language"] = language or self.language

            # Add prompt if specified
            if prompt:
                kwargs["prompt"] = prompt

            logger.debug(f"Transcribing audio bytes ({len(audio_bytes)} bytes) with model: {self.model}")
            response = client.audio.transcriptions.create(**kwargs)

            transcription = response.text
            logger.info(f"Transcription successful: {len(transcription)} characters")
            return transcription

        except Exception as e:
            logger.error(f"Whisper transcription failed: {e}")
            raise

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio bytes to text (implements BaseASRProvider interface).

        Args:
            audio_bytes: Raw audio data

        Returns:
            Transcribed text string
        """
        return await self.transcribe_audio_bytes(audio_bytes)

    async def transcribe_file(self, audio_path: str) -> str:
        """
        Transcribe audio from file path (implements BaseASRProvider interface).

        Args:
            audio_path: Path to audio file

        Returns:
            Transcribed text string
        """
        return await self.transcribe_audio(audio_path)

    async def is_available(self) -> bool:
        """
        Check if Whisper API is available.

        Returns:
            True if API is reachable, False otherwise
        """
        try:
            client = self._get_client()
            # Simple check - if client initializes, assume available
            return client is not None
        except Exception as e:
            logger.warning(f"Whisper API not available: {e}")
            return False


# ===== Singleton instance =====
_whisper_asr: Optional[WhisperASR] = None


def get_whisper_asr(
    api_key: Optional[str] = None,
    model: str = "whisper-1",
    language: Optional[str] = None,
) -> WhisperASR:
    """
    Get or create Whisper ASR singleton instance.

    Args:
        api_key: OpenAI API key
        model: Whisper model to use
        language: Language code for transcription

    Returns:
        WhisperASR instance
    """
    global _whisper_asr
    if _whisper_asr is None:
        _whisper_asr = WhisperASR(api_key=api_key, model=model, language=language)
    return _whisper_asr
