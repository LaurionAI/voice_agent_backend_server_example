"""
ASR (Automatic Speech Recognition) providers.

Available providers:
- HFSpaceASR: HuggingFace Space-based ASR (SenseVoice)
- WhisperASR: OpenAI Whisper API
"""

from .base import BaseASRProvider, ASRConfig
from .hf_space import HFSpaceASR, get_hf_space_asr
from .whisper_asr import WhisperASR, get_whisper_asr

__all__ = [
    # Base
    "BaseASRProvider",
    "ASRConfig",
    # Providers
    "HFSpaceASR",
    "WhisperASR",
    # Factories
    "get_hf_space_asr",
    "get_whisper_asr",
]
