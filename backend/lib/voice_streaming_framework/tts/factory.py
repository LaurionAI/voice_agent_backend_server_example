"""TTS provider factory."""

import logging
from typing import Optional
from .base import TTSProvider, TTSConfig
from .edge_tts_provider import EdgeTTSProvider

logger = logging.getLogger(__name__)


def get_tts_provider(
    provider_name: str = "edge-tts",
    config: Optional[TTSConfig] = None
) -> TTSProvider:
    """
    Get TTS provider instance.

    Args:
        provider_name: Name of provider ("edge-tts", "gptsovits", "openai")
        config: TTS configuration. If None, uses defaults.

    Returns:
        Initialized TTS provider

    Raises:
        ValueError: If provider_name is unknown
        RuntimeError: If provider initialization fails

    Examples:
        # Use Edge-TTS (default)
        tts = get_tts_provider()

        # Use Edge-TTS with custom voice
        config = TTSConfig(voice="en-GB-SoniaNeural", rate="+10%")
        tts = get_tts_provider("edge-tts", config)

        # Use GPT-SoVITS
        config = TTSConfig(
            provider_settings={
                "api_endpoint": "http://localhost:9880",
                "reference_audio": "path/to/voice.wav",
                "reference_text": "Hello, this is my voice."
            }
        )
        tts = get_tts_provider("gptsovits", config)
    """
    provider_name = provider_name.lower()

    if provider_name == "edge-tts" or provider_name == "edge":
        return EdgeTTSProvider(config)

    elif provider_name == "gptsovits" or provider_name == "gpt-sovits":
        from .gptsovits_provider import GPTSoVITSProvider
        return GPTSoVITSProvider(config)

    elif provider_name == "openai" or provider_name == "openai-tts":
        # Future: OpenAI TTS provider
        raise NotImplementedError(
            "OpenAI TTS provider not yet implemented. "
            "Use 'edge-tts' or 'gptsovits' for now."
        )

    else:
        raise ValueError(
            f"Unknown TTS provider: {provider_name}. "
            f"Available: edge-tts, gptsovits"
        )
