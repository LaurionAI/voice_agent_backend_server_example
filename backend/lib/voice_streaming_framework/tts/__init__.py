"""
TTS (Text-to-Speech) providers for voice streaming.

Available providers:
- EdgeTTS: Microsoft Edge TTS (free, no API key required)
- GPTSoVITS: GPT-SoVITS voice cloning
"""

from .base import TTSProvider, TTSConfig
from .factory import get_tts_provider
from .edge_tts_provider import EdgeTTSProvider

# Alias for consistency with other providers
BaseTTSProvider = TTSProvider
EdgeTTS = EdgeTTSProvider

__all__ = [
    # Base
    "TTSProvider",
    "BaseTTSProvider",  # Alias
    "TTSConfig",
    # Factory
    "get_tts_provider",
    # Providers
    "EdgeTTSProvider",
    "EdgeTTS",  # Alias
]
