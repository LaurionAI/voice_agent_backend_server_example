"""
Base class for ASR (Automatic Speech Recognition) providers.

All ASR providers must implement this interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ASRConfig:
    """Configuration for ASR providers."""
    language: Optional[str] = None  # ISO language code (e.g., "en", "zh")
    sample_rate: int = 16000  # Expected sample rate in Hz
    encoding: str = "wav"  # Audio encoding format


class BaseASRProvider(ABC):
    """
    Abstract base class for ASR providers.

    All ASR implementations (Whisper, HF Space, local models) must inherit
    from this class and implement the required methods.

    Example:
        class MyASR(BaseASRProvider):
            async def transcribe(self, audio_bytes: bytes) -> str:
                # Implementation here
                pass
    """

    def __init__(self, config: Optional[ASRConfig] = None):
        """
        Initialize ASR provider.

        Args:
            config: Optional ASR configuration
        """
        self.config = config or ASRConfig()

    @abstractmethod
    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Transcribe audio bytes to text.

        This is the primary method for ASR. Implementations should handle
        the audio format conversion internally if needed.

        Args:
            audio_bytes: Raw audio data (format depends on config.encoding)

        Returns:
            Transcribed text string

        Raises:
            Exception: If transcription fails
        """
        pass

    async def transcribe_file(self, audio_path: str) -> str:
        """
        Transcribe audio from a file path.

        Default implementation reads the file and calls transcribe().
        Override this method if your provider has native file support.

        Args:
            audio_path: Path to audio file

        Returns:
            Transcribed text string
        """
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()
        return await self.transcribe(audio_bytes)

    @abstractmethod
    async def is_available(self) -> bool:
        """
        Check if the ASR provider is available and ready.

        Returns:
            True if provider is ready to transcribe, False otherwise
        """
        pass

    def get_name(self) -> str:
        """
        Get the provider name.

        Returns:
            Human-readable provider name
        """
        return self.__class__.__name__
