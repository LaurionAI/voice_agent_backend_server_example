"""Mock ASR processor for demo purposes.

In production, replace with:
- OpenAI Whisper API (voice_streaming_framework.asr.whisper_asr.WhisperASR)
- HuggingFace Spaces (voice_streaming_framework.asr.hf_space.HFSpaceASR)
- Local Whisper model
"""

import logging

logger = logging.getLogger(__name__)


class MockASR:
    """
    Mock ASR for demonstration purposes.

    Returns a placeholder transcript. Replace with real ASR in production.
    """

    def __init__(self):
        logger.info("MockASR initialized (returns placeholder transcripts)")
        logger.warning("⚠️  Using MockASR - replace with real ASR for production!")

    async def transcribe(self, audio_bytes: bytes) -> str:
        """
        Mock transcription that returns a placeholder.

        Args:
            audio_bytes: Audio data (ignored in mock)

        Returns:
            Placeholder transcript
        """
        # In a real implementation, this would transcribe the audio
        logger.info(f"📝 MockASR: Received {len(audio_bytes)} bytes of audio")
        return "[Audio transcription would appear here - integrate real ASR]"

    async def transcribe_audio(self, audio_path: str, **kwargs) -> str:
        """Alternative interface for file-based transcription."""
        return await self.transcribe(b"")
