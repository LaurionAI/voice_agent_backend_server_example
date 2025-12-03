"""Generic streaming pipeline for voice processing (framework - no app dependencies).

This is the FRAMEWORK part extracted from streaming_handler.py.
It contains only generic voice processing logic with NO app-specific dependencies.

What this does:
- ASR (Speech-to-Text) processing
- TTS (Text-to-Speech) streaming
- Audio buffering and validation

What this does NOT do (app-specific):
- Subscription tier checking → Use callbacks
- Settings retrieval → Use constructor injection
- Custom logging → Use standard logging or callbacks
"""

import asyncio
import logging
from typing import AsyncGenerator, Optional, Dict, Any, Callable

logger = logging.getLogger(__name__)

try:
    from funasr import AutoModel
    FUNASR_AVAILABLE = True
except ImportError:
    FUNASR_AVAILABLE = False
    AutoModel = None


class StreamingPipeline:
    """
    Generic streaming pipeline for voice processing.

    This class handles the core voice streaming logic WITHOUT any app-specific
    dependencies. App-specific logic is provided via callbacks or constructor params.

    Pattern:
        # Framework provides generic pipeline
        pipeline = StreamingPipeline(asr_provider, tts_provider)

        # App provides specific configuration
        pipeline.set_tier_checker(lambda user_id: cache.get_tier(user_id))

    Usage:
        # In your app
        from lib.voice_streaming_framework.audio import StreamingPipeline

        pipeline = StreamingPipeline(
            asr_provider=whisper_asr,
            tts_provider=edge_tts,
            audio_validator=validator
        )

        # Stream TTS
        async for chunk in pipeline.stream_tts("Hello world"):
            # Send chunk to WebRTC
            pass
    """

    def __init__(
        self,
        asr_provider=None,
        tts_provider=None,
        audio_validator=None,
        sensevoice_model_path: Optional[str] = None
    ):
        """
        Initialize streaming pipeline.

        Args:
            asr_provider: ASR provider instance (WhisperASR, HFSpaceASR, etc.)
            tts_provider: TTS provider instance (EdgeTTS, GPTSoVITS, etc.)
            audio_validator: Audio validator instance (optional)
            sensevoice_model_path: Path to SenseVoice model (optional)
        """
        # Core components (injected by app)
        self.asr_provider = asr_provider
        self.tts_provider = tts_provider
        self.audio_validator = audio_validator

        # Audio buffers (generic)
        self.audio_buffers: Dict[str, bytes] = {}
        self.transcription_cache: Dict[str, str] = {}

        # SenseVoice model (optional)
        self.sensevoice_model = None
        self._model_loaded = False
        self.sensevoice_model_path = sensevoice_model_path

        # Callbacks (optional, for app-specific logic)
        self.on_asr_start: Optional[Callable] = None
        self.on_asr_complete: Optional[Callable] = None
        self.on_tts_start: Optional[Callable] = None
        self.on_tts_complete: Optional[Callable] = None

    async def load_sensevoice_model(self, model_path: Optional[str] = None) -> bool:
        """
        Load SenseVoice model for ASR.

        Args:
            model_path: Path to model (uses self.sensevoice_model_path if None)

        Returns:
            True if loaded successfully, False otherwise
        """
        if not FUNASR_AVAILABLE:
            logger.warning("⚠️ FunASR not available")
            return False

        model_path = model_path or self.sensevoice_model_path
        if not model_path:
            logger.warning("⚠️ No SenseVoice model path provided")
            return False

        try:
            logger.debug(f"🔄 Loading SenseVoice model: {model_path}")
            self.sensevoice_model = AutoModel(
                model=model_path,
                trust_remote_code=True
            )
            self._model_loaded = True
            logger.info("✅ SenseVoice model loaded successfully")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load SenseVoice model: {e}")
            return False

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        session_id: str
    ) -> Optional[str]:
        """
        Transcribe audio using configured ASR provider.

        Args:
            audio_bytes: Audio data
            session_id: Session ID (for caching)

        Returns:
            Transcribed text or None if failed
        """
        if not self.asr_provider:
            logger.error("❌ No ASR provider configured")
            return None

        try:
            # Callback: ASR start
            if self.on_asr_start:
                await self.on_asr_start(session_id, len(audio_bytes))

            # Transcribe
            text = await self.asr_provider.transcribe_audio_bytes(
                audio_bytes,
                filename="audio.wav"
            )

            # Cache result
            self.transcription_cache[session_id] = text

            # Callback: ASR complete
            if self.on_asr_complete:
                await self.on_asr_complete(session_id, text)

            logger.info(f"✅ Transcription: {text}")
            return text

        except Exception as e:
            logger.error(f"❌ ASR transcription failed: {e}")
            return None

    async def stream_tts(
        self,
        text: str,
        voice: Optional[str] = None,
        rate: Optional[str] = None,
        chunk_size: Optional[int] = None
    ) -> AsyncGenerator[bytes, None]:
        """
        Stream TTS audio chunks.

        Args:
            text: Text to synthesize
            voice: Optional voice override
            rate: Optional rate override
            chunk_size: Optional chunk size override

        Yields:
            Audio chunks (MP3 format)
        """
        if not self.tts_provider:
            logger.error("❌ No TTS provider configured")
            return

        if not text or not text.strip():
            logger.warning("⚠️ Empty text provided to TTS")
            return

        try:
            # Callback: TTS start
            if self.on_tts_start:
                await self.on_tts_start(text)

            # Update provider config if overrides provided
            if voice:
                self.tts_provider.update_config(voice=voice)
            if rate:
                self.tts_provider.update_config(rate=rate)
            if chunk_size:
                self.tts_provider.update_config(chunk_size=chunk_size)

            # Stream audio
            async for chunk in self.tts_provider.stream_audio(text):
                yield chunk

            # Callback: TTS complete
            if self.on_tts_complete:
                await self.on_tts_complete(text)

        except Exception as e:
            logger.error(f"❌ TTS streaming error: {e}")
            raise

    def validate_audio(
        self,
        audio_bytes: bytes,
        session_id: str
    ) -> bool:
        """
        Validate audio quality (optional).

        Args:
            audio_bytes: Audio data
            session_id: Session ID

        Returns:
            True if audio is valid, False otherwise
        """
        if not self.audio_validator:
            return True  # No validator, assume valid

        try:
            is_valid = self.audio_validator.validate(audio_bytes)
            if not is_valid:
                logger.warning(f"⚠️ Audio validation failed for session {session_id}")
            return is_valid
        except Exception as e:
            logger.error(f"❌ Audio validation error: {e}")
            return False  # Fail safe

    def clear_buffers(self, session_id: str) -> None:
        """Clear buffers for a session."""
        if session_id in self.audio_buffers:
            del self.audio_buffers[session_id]
        if session_id in self.transcription_cache:
            del self.transcription_cache[session_id]
