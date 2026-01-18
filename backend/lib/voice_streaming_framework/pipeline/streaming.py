"""
Streaming voice pipeline orchestrator.

This is the main entry point for the voice streaming framework.
It orchestrates ASR → LLM → TTS with streaming support for low latency.
"""

import asyncio
import logging
import uuid
from typing import Any, AsyncIterator, Callable, Dict, Optional

from .config import PipelineConfig
from ..asr.base import BaseASRProvider
from ..llm.base import BaseLLMProvider
from ..tts.base import TTSProvider as BaseTTSProvider
from ..text.sentence_aggregator import SentenceAggregator, AggregatorConfig
from ..transport.base import BaseTransport
from ..audio.converter import AudioConverter, get_converter
from ..audio.validator import AudioValidator
from ..core.types import AudioChunk, AudioFormat, StreamingEvent, StreamingEventType

logger = logging.getLogger(__name__)


class StreamingVoicePipeline:
    """
    Complete streaming voice pipeline: ASR → LLM (streaming) → TTS (streaming) → Audio

    This pipeline enables low-latency voice responses by:
    1. Starting TTS as soon as the first sentence is ready (not waiting for full LLM response)
    2. Streaming audio to the client as it's generated
    3. Supporting interruption to cancel in-progress responses

    Example:
        pipeline = StreamingVoicePipeline(
            asr=HFSpaceASR(space_name="hz6666/SenseVoiceSmall"),
            llm=OpenAICompatibleLLM(
                config=LLMConfig(model="gpt-4", system_prompt="You are helpful."),
                api_key="sk-..."
            ),
            tts=EdgeTTS(TTSConfig(voice="en-US-JennyNeural")),
            transport=WebRTCTransport(),
        )

        # Process incoming audio
        await pipeline.process(session_id, audio_bytes)
    """

    def __init__(
        self,
        asr: BaseASRProvider,
        llm: BaseLLMProvider,
        tts: BaseTTSProvider,
        transport: BaseTransport,
        config: Optional[PipelineConfig] = None,
        # Event callbacks
        on_transcript: Optional[Callable[[str, str], Any]] = None,
        on_llm_start: Optional[Callable[[str], Any]] = None,
        on_llm_sentence: Optional[Callable[[str, str], Any]] = None,
        on_response_complete: Optional[Callable[[str, str], Any]] = None,
        on_error: Optional[Callable[[str, Exception], Any]] = None,
    ):
        """
        Initialize streaming voice pipeline.

        Args:
            asr: ASR provider for speech-to-text
            llm: LLM provider for response generation
            tts: TTS provider for text-to-speech
            transport: Transport for audio delivery
            config: Optional pipeline configuration
            on_transcript: Callback(session_id, transcript) when ASR completes
            on_llm_start: Callback(session_id) when LLM starts generating
            on_llm_sentence: Callback(session_id, sentence) for each sentence
            on_response_complete: Callback(session_id, full_response) when done
            on_error: Callback(session_id, error) on errors
        """
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.transport = transport
        self.config = config or PipelineConfig()

        # Callbacks
        self.on_transcript = on_transcript
        self.on_llm_start = on_llm_start
        self.on_llm_sentence = on_llm_sentence
        self.on_response_complete = on_response_complete
        self.on_error = on_error

        # Sentence aggregator for streaming
        self._aggregator = SentenceAggregator(AggregatorConfig(
            min_chars=self.config.sentence_min_chars,
            max_wait_chars=self.config.sentence_max_wait_chars,
        ))

        # Audio converter for TTS output
        self._converter = get_converter()

        # Audio validator
        self._validator = AudioValidator(
            energy_threshold=self.config.min_audio_energy,
            speech_ratio_threshold=self.config.min_speech_ratio,
        ) if self.config.validate_audio else None

        # Session state
        self._sessions: Dict[str, Dict] = {}
        self._active_tasks: Dict[str, asyncio.Task] = {}

    async def create_session(self, session_id: str, user_id: str = "anonymous") -> str:
        """
        Create a new voice session.

        Args:
            session_id: Unique session identifier (or None to generate)
            user_id: User identifier

        Returns:
            Session ID
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        self._sessions[session_id] = {
            "user_id": user_id,
            "is_active": True,
            "is_speaking": False,
        }

        # Initialize LLM session
        self.llm.create_session(session_id)

        logger.info(f"Created voice session: {session_id[:8]}")
        return session_id

    async def cleanup_session(self, session_id: str) -> None:
        """
        Clean up a voice session.

        Args:
            session_id: Session to clean up
        """
        # Cancel any active task
        if session_id in self._active_tasks:
            self._active_tasks[session_id].cancel()
            try:
                await self._active_tasks[session_id]
            except asyncio.CancelledError:
                pass
            del self._active_tasks[session_id]

        # Clean up LLM session
        self.llm.cleanup_session(session_id)

        # Remove session state
        self._sessions.pop(session_id, None)

        logger.info(f"Cleaned up voice session: {session_id[:8]}")

    async def process(self, session_id: str, audio_bytes: bytes) -> None:
        """
        Process audio input through the full pipeline.

        Flow:
        1. Validate audio (optional)
        2. ASR: audio → text
        3. LLM: text → streaming response
        4. Sentence aggregation: tokens → sentences
        5. TTS: sentences → audio
        6. Transport: audio → client

        Args:
            session_id: Session identifier
            audio_bytes: Raw audio data from user
        """
        try:
            # 1. Validate audio (optional)
            if self._validator:
                is_valid, info = self._validator.validate_audio(
                    audio_bytes, sample_rate=16000, format="webm"
                )
                if not is_valid:
                    logger.debug(f"Audio validation failed: {info.get('reason')}")
                    return

            # 2. ASR
            logger.debug(f"Starting ASR for session {session_id[:8]}")
            transcript = await self.asr.transcribe(audio_bytes)

            if not transcript or not transcript.strip():
                logger.debug(f"Empty transcript for session {session_id[:8]}")
                return

            logger.info(f"Transcript [{session_id[:8]}]: {transcript}")

            # Call transcript callback
            if self.on_transcript:
                await self._call_callback(self.on_transcript, session_id, transcript)

            # 3-6. Stream LLM → TTS → Transport
            await self._stream_response(session_id, transcript)

        except asyncio.CancelledError:
            logger.info(f"Processing cancelled for session {session_id[:8]}")
            raise
        except Exception as e:
            logger.error(f"Pipeline error for session {session_id[:8]}: {e}")
            if self.on_error:
                await self._call_callback(self.on_error, session_id, e)
            raise

    async def _stream_response(self, session_id: str, user_message: str) -> None:
        """
        Stream LLM response through TTS to transport.

        This is the core streaming logic that enables low-latency responses.
        """
        # Mark session as speaking
        if session_id in self._sessions:
            self._sessions[session_id]["is_speaking"] = True

        full_response = ""

        try:
            # Notify LLM start
            if self.on_llm_start:
                await self._call_callback(self.on_llm_start, session_id)

            # Stream LLM tokens → aggregate into sentences → TTS → transport
            async for sentence in self._aggregator.process_stream(
                self.llm.stream(session_id, user_message)
            ):
                full_response += sentence + " "

                logger.debug(f"Sentence [{session_id[:8]}]: {sentence[:50]}...")

                # Notify sentence callback
                if self.on_llm_sentence:
                    await self._call_callback(self.on_llm_sentence, session_id, sentence)

                # Stream TTS audio for this sentence
                await self._stream_tts_sentence(session_id, sentence)

            # Notify completion
            full_response = full_response.strip()
            if self.on_response_complete:
                await self._call_callback(self.on_response_complete, session_id, full_response)

            logger.info(f"Response complete [{session_id[:8]}]: {len(full_response)} chars")

        finally:
            # Mark session as not speaking
            if session_id in self._sessions:
                self._sessions[session_id]["is_speaking"] = False

    async def _stream_tts_sentence(self, session_id: str, sentence: str) -> None:
        """
        Convert a sentence to speech and stream to transport.

        Handles TTS output format conversion (MP3 → PCM) if needed.
        """
        try:
            # Get TTS audio stream
            tts_stream = self.tts.stream_audio(sentence)

            # Check if we need format conversion (TTS outputs MP3, WebRTC needs PCM)
            if hasattr(self.tts, 'output_format') and self.tts.output_format == "mp3":
                # Convert MP3 → PCM using FFmpeg
                async for pcm_chunk in self._converter.mp3_to_pcm_stream(tts_stream):
                    chunk = AudioChunk(
                        data=pcm_chunk,
                        format=AudioFormat.PCM,
                        sample_rate=48000,
                    )
                    await self.transport.send_audio(session_id, chunk)
            else:
                # Direct streaming (TTS outputs PCM)
                async for audio_data in tts_stream:
                    chunk = AudioChunk(
                        data=audio_data,
                        format=AudioFormat.PCM,
                        sample_rate=48000,
                    )
                    await self.transport.send_audio(session_id, chunk)

        except Exception as e:
            logger.error(f"TTS streaming error for {session_id[:8]}: {e}")
            raise

    async def interrupt(self, session_id: str) -> None:
        """
        Interrupt the current response generation.

        Cancels LLM generation and flushes audio buffers.

        Args:
            session_id: Session to interrupt
        """
        logger.info(f"Interrupting session {session_id[:8]}")

        # Cancel active task
        if session_id in self._active_tasks:
            self._active_tasks[session_id].cancel()

        # Flush transport buffer
        await self.transport.flush(session_id)

        # Notify LLM of interruption
        self.llm.handle_interruption(session_id)

        # Mark as not speaking
        if session_id in self._sessions:
            self._sessions[session_id]["is_speaking"] = False

    def is_speaking(self, session_id: str) -> bool:
        """Check if a session is currently speaking."""
        return self._sessions.get(session_id, {}).get("is_speaking", False)

    async def _call_callback(self, callback: Callable, *args) -> None:
        """Call a callback, handling both sync and async callbacks."""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"Callback error: {e}")
