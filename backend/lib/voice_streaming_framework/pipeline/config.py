"""
Configuration for the streaming voice pipeline.
"""

from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class PipelineConfig:
    """
    Configuration for StreamingVoicePipeline.

    This config controls the overall behavior of the voice pipeline,
    including audio validation, sentence aggregation, and interruption handling.
    """
    # Audio validation
    validate_audio: bool = True
    min_audio_energy: float = 500.0  # Minimum RMS energy
    min_speech_ratio: float = 0.03  # Minimum VAD speech ratio

    # Sentence aggregation for streaming
    sentence_min_chars: int = 15
    sentence_max_wait_chars: int = 200

    # Interruption handling
    enable_interruption: bool = True
    interruption_threshold_ms: float = 500.0  # Min time before allowing interrupt

    # Audio buffering
    audio_buffer_timeout: float = 1.5  # Seconds to wait for more audio

    # Logging
    debug_logging: bool = False
