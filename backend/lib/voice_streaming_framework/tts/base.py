"""Base TTS provider interface."""

from abc import ABC, abstractmethod
from typing import AsyncIterator, Optional
from dataclasses import dataclass


@dataclass
class TTSConfig:
    """Configuration for TTS provider."""
    voice: str = "en-US-AriaNeural"  # Voice identifier (provider-specific)
    rate: str = "+0%"  # Speech rate adjustment
    chunk_size: int = 4096  # Output chunk size in bytes
    language: Optional[str] = "en"  # Language code

    # Provider-specific settings
    provider_settings: dict = None

    def __post_init__(self):
        if self.provider_settings is None:
            self.provider_settings = {}


class TTSProvider(ABC):
    """
    Base class for TTS providers.

    All providers must implement stream_audio() which yields MP3 chunks.
    This ensures compatibility with the FFmpeg pipeline (MP3 → PCM 48kHz).
    """

    def __init__(self, config: Optional[TTSConfig] = None):
        """
        Initialize TTS provider.

        Args:
            config: TTS configuration. If None, uses defaults.
        """
        self.config = config or TTSConfig()

    @abstractmethod
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
        pass

    @abstractmethod
    async def synthesize_full(self, text: str) -> bytes:
        """
        Synthesize complete audio file.

        Args:
            text: Text to convert to speech

        Returns:
            Complete MP3 audio bytes

        Raises:
            RuntimeError: If TTS generation fails
        """
        pass

    @abstractmethod
    def get_available_voices(self) -> list[dict]:
        """
        Get list of available voices for this provider.

        Returns:
            List of voice dicts with keys: id, name, language, gender
        """
        pass

    def update_config(self, **kwargs):
        """
        Update TTS configuration.

        Args:
            **kwargs: Configuration parameters to update
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
