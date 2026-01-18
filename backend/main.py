"""
Voice Agent Demo Server (v2 - Using StreamingVoicePipeline)

A voice streaming agent using the new pipeline architecture:
- Streaming LLM → TTS for low-latency responses
- SentenceAggregator for real-time text chunking
- WebSocket + WebRTC voice streaming
- Interruption handling

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import base64
import json
import logging
import os
import time
import uuid
from pathlib import Path
from datetime import time as dt_time
from typing import Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    _project_root = Path(__file__).parent
    env_path = _project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
        print(f"✅ Loaded environment from {env_path}")
    else:
        print(f"⚠️  No .env file found at {env_path}")
except ImportError:
    print("⚠️  python-dotenv not installed")

# Import new pipeline components
from lib.voice_streaming_framework import (
    OpenAICompatibleLLM,
    LLMConfig,
    SentenceAggregator,
    AggregatorConfig,
    AudioConverter,
    get_converter,
)
from lib.voice_streaming_framework.asr import HFSpaceASR
from lib.voice_streaming_framework.tts import get_tts_provider, TTSConfig
from lib.voice_streaming_framework.audio import AudioValidator
from lib.voice_streaming_framework.webrtc.manager import WebRTCManager

# Scheduler for keeping HF Space alive
from scheduler.daily_asr_scheduler import DailyASRScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

SYSTEM_PROMPT = """你是一个有帮助的语音助手。保持回复简洁自然，适合语音输出。
用户用什么语言提问，你就用什么语言回答。"""

# Audio settings
BUFFER_TIMEOUT = 1.5  # seconds to wait before processing audio buffer
MIN_AUDIO_ENERGY = 500.0
MIN_SPEECH_RATIO = 0.03

# ============================================================================
# GLOBAL STATE
# ============================================================================

# Core components
llm_provider: OpenAICompatibleLLM = None
asr_provider: HFSpaceASR = None
tts_provider = None
audio_validator: AudioValidator = None
webrtc_manager: WebRTCManager = None
sentence_aggregator: SentenceAggregator = None
audio_converter: AudioConverter = None

# Session state
sessions: Dict[str, Dict[str, Any]] = {}  # session_id -> session data
audio_buffers: Dict[str, Dict] = {}  # session_id -> audio buffer
active_tasks: Dict[str, asyncio.Task] = {}  # session_id -> processing task

# Scheduler
asr_scheduler: DailyASRScheduler = None
asr_scheduler_task: asyncio.Task = None


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def check_ffmpeg_availability():
    """Check if FFmpeg is available in PATH."""
    import shutil
    import subprocess

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        logger.info(f"✅ FFmpeg found at: {ffmpeg_path}")
        try:
            result = subprocess.run(
                ["ffmpeg", "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            version_line = result.stdout.split('\n')[0] if result.stdout else "unknown"
            logger.info(f"   FFmpeg version: {version_line}")
            return True
        except Exception as e:
            logger.error(f"❌ FFmpeg version check failed: {e}")
            return False
    else:
        logger.error("❌ FFmpeg NOT found in PATH!")
        return False


def _custom_exception_handler(loop, context):
    """Suppress non-critical ICE/STUN errors."""
    exception = context.get("exception")
    if exception:
        exception_str = str(type(exception).__name__)
        exception_msg = str(exception)
        if "TransactionFailed" in exception_str or "STUN transaction failed" in exception_msg:
            logger.debug(f"ICE candidate failed (non-critical): {exception}")
            return
    loop.default_exception_handler(context)


async def fetch_ice_servers(session_id: str) -> list:
    """Fetch STUN/TURN servers for WebRTC."""
    import aiohttp

    ice_servers = [
        {"urls": "stun:stun.l.google.com:19302"},
        {"urls": "stun:stun1.l.google.com:19302"},
    ]

    metered_api_key = os.environ.get("METERED_API_KEY")
    metered_url = os.environ.get("METERED_URL")

    if metered_api_key and metered_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{metered_url}?apiKey={metered_api_key}",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        turn_servers = await response.json()
                        ice_servers.extend(turn_servers)
                        logger.info(f"🔧 Got {len(turn_servers)} TURN servers from Metered.ca")
                    else:
                        ice_servers.extend(_get_openrelay_servers())
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch TURN credentials: {e}")
            ice_servers.extend(_get_openrelay_servers())
    else:
        ice_servers.extend(_get_openrelay_servers())

    return ice_servers


def _get_openrelay_servers() -> list:
    """Get OpenRelay free TURN servers as fallback."""
    return [
        {"urls": "turn:openrelay.metered.ca:80", "username": "openrelayproject", "credential": "openrelayproject"},
        {"urls": "turn:openrelay.metered.ca:443", "username": "openrelayproject", "credential": "openrelayproject"},
        {"urls": "turn:openrelay.metered.ca:443?transport=tcp", "username": "openrelayproject", "credential": "openrelayproject"}
    ]


# ============================================================================
# LIFESPAN (STARTUP/SHUTDOWN)
# ============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup global resources."""
    global llm_provider, asr_provider, tts_provider, audio_validator
    global webrtc_manager, sentence_aggregator, audio_converter
    global asr_scheduler, asr_scheduler_task

    # Initialize scheduler variables to None to avoid UnboundLocalError
    asr_scheduler = None
    asr_scheduler_task = None

    # Set custom exception handler
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(_custom_exception_handler)

    logger.info("🚀 Starting Voice Agent Demo Server (v2 - Pipeline)...")
    logger.info(f"📍 Environment: {os.environ.get('ENVIRONMENT', 'development')}")

    # Check FFmpeg
    if not check_ffmpeg_availability():
        logger.warning("⚠️  Audio output may not work without FFmpeg!")

    # Initialize LLM provider (OpenAI-compatible: ZhipuAI)
    zhipuai_api_key = os.environ.get("ZHIPUAI_API_KEY")
    if zhipuai_api_key:
        llm_provider = OpenAICompatibleLLM(
            config=LLMConfig(
                model="glm-4-flash",
                system_prompt=SYSTEM_PROMPT,
                temperature=0.7,
                max_tokens=1024,
            ),
            api_key=zhipuai_api_key,
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )
        logger.info("✅ LLM provider initialized (ZhipuAI GLM-4-flash)")
    else:
        logger.error("❌ ZHIPUAI_API_KEY not set! LLM will not work.")

    # Initialize ASR provider
    asr_provider = HFSpaceASR(space_name="hz6666/SenseVoiceSmall")
    logger.info("✅ ASR provider initialized (HF Space - SenseVoiceSmall)")

    # Initialize TTS provider
    tts_provider = get_tts_provider("edge-tts", TTSConfig(
        voice="zh-CN-XiaoxiaoNeural",
        rate="+0%"
    ))
    logger.info("✅ TTS provider initialized (Edge TTS)")

    # Initialize audio validator
    audio_validator = AudioValidator(
        energy_threshold=MIN_AUDIO_ENERGY,
        vad_mode=3,
        enable_webrtc_vad=True,
        speech_ratio_threshold=MIN_SPEECH_RATIO
    )
    logger.info("✅ Audio validator initialized")

    # Initialize WebRTC manager
    webrtc_manager = WebRTCManager()
    logger.info("✅ WebRTC manager initialized")

    # Initialize sentence aggregator (for streaming LLM → TTS)
    sentence_aggregator = SentenceAggregator(AggregatorConfig(
        min_chars=15,
        max_wait_chars=200,
    ))
    logger.info("✅ Sentence aggregator initialized")

    # Initialize audio converter
    audio_converter = get_converter()
    logger.info(f"✅ Audio converter initialized (FFmpeg available: {audio_converter.is_available()})")

    # Initialize ASR scheduler
    voice_sample_path = Path(__file__).parent / "scheduler" / "voice_sample" / "test_analysis_aapl_deeper.wav"
    if voice_sample_path.exists():
        asr_scheduler = DailyASRScheduler(
            audio_path=str(voice_sample_path),
            run_time=dt_time(hour=9, minute=0)
        )
        asr_scheduler_task = asyncio.create_task(asr_scheduler.start())
        logger.info("✅ Daily ASR scheduler started")

    logger.info("🎉 Server ready! Connect on ws://localhost:8000/ws")

    yield

    # Cleanup
    logger.info("🛑 Shutting down server...")

    # Cancel all active tasks
    for session_id, task in list(active_tasks.items()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Stop scheduler
    if asr_scheduler:
        asr_scheduler.stop()
    if asr_scheduler_task:
        asr_scheduler_task.cancel()

    # Close WebRTC connections
    if webrtc_manager:
        for session_id in list(webrtc_manager.pcs.keys()):
            await webrtc_manager.close_peer_connection(session_id)

    logger.info("✅ Server shutdown complete")


# ============================================================================
# FASTAPI APP
# ============================================================================

app = FastAPI(
    title="Voice Agent Demo (v2)",
    description="Voice streaming with StreamingVoicePipeline",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# SESSION MANAGEMENT
# ============================================================================

async def create_session(websocket: WebSocket, user_id: str) -> str:
    """Create a new voice session."""
    session_id = str(uuid.uuid4())

    sessions[session_id] = {
        "user_id": user_id,
        "websocket": websocket,
        "is_active": True,
        "is_speaking": False,
        "created_at": time.time(),
    }

    audio_buffers[session_id] = {
        "chunks": [],
        "last_chunk_time": time.time(),
        "processing_task": None,
    }

    # Initialize LLM session
    if llm_provider:
        llm_provider.create_session(session_id)

    logger.info(f"📞 Session created: {session_id[:8]}...")
    return session_id


async def cleanup_session(session_id: str):
    """Clean up a voice session."""
    # Cancel active task
    if session_id in active_tasks:
        active_tasks[session_id].cancel()
        del active_tasks[session_id]

    # Clean up audio buffer
    if session_id in audio_buffers:
        buffer = audio_buffers[session_id]
        if buffer.get("processing_task"):
            buffer["processing_task"].cancel()
        del audio_buffers[session_id]

    # Clean up LLM session
    if llm_provider:
        llm_provider.cleanup_session(session_id)

    # Clean up WebRTC
    if webrtc_manager and session_id in webrtc_manager.pcs:
        await webrtc_manager.close_peer_connection(session_id)

    # Remove session
    sessions.pop(session_id, None)

    logger.info(f"👋 Session cleaned up: {session_id[:8]}...")


async def send_message(session_id: str, message: dict):
    """Send a message to a session."""
    session = sessions.get(session_id)
    if session and session.get("websocket"):
        try:
            await session["websocket"].send_text(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")


# ============================================================================
# AUDIO PROCESSING (NEW PIPELINE)
# ============================================================================

async def process_audio(session_id: str, audio_bytes: bytes):
    """
    Process audio through the pipeline: ASR → LLM (streaming) → TTS → WebRTC

    This uses:
    - SentenceAggregator for streaming LLM tokens into sentences
    - FFmpeg for MP3 → PCM conversion
    - WebRTC for low-latency audio delivery
    """
    try:
        # 1. Validate audio
        is_valid, info = audio_validator.validate_audio(
            audio_bytes, sample_rate=16000, format="webm"
        )
        if not is_valid:
            logger.info(f"🔇 Audio validation failed: {info.get('reason')}")
            return

        logger.info(f"✅ Audio validated (energy={info.get('energy', 0):.1f})")

        # 2. ASR: Audio → Text
        logger.info(f"🎤 Transcribing audio ({len(audio_bytes)} bytes)...")
        transcript = await asr_provider.transcribe(audio_bytes)

        if not transcript or len(transcript.strip()) < 2:
            logger.info("🔇 Empty transcript, ignoring")
            await send_message(session_id, {
                "event": "no_speech_detected",
                "data": {"message": "No speech detected"}
            })
            return

        logger.info(f"📝 Transcript: {transcript}")

        # Send transcript to frontend
        await send_message(session_id, {
            "event": "transcript",
            "data": {"text": transcript, "session_id": session_id}
        })

        # 3. LLM (streaming) → Sentence Aggregator → TTS → WebRTC
        await stream_response(session_id, transcript)

    except asyncio.CancelledError:
        logger.info(f"Processing cancelled for {session_id[:8]}")
        raise
    except Exception as e:
        logger.error(f"❌ Error processing audio: {e}")
        import traceback
        traceback.print_exc()


async def stream_response(session_id: str, user_message: str):
    """
    Stream LLM response through TTS to WebRTC.

    Key: Uses SentenceAggregator to start TTS before LLM finishes!
    """
    if not llm_provider:
        logger.error("LLM provider not initialized")
        return

    session = sessions.get(session_id)
    if not session:
        return

    session["is_speaking"] = True
    full_response = ""

    try:
        logger.info(f"🤖 Streaming LLM response for: {user_message[:50]}...")

        # Stream LLM tokens → aggregate into sentences → TTS each sentence
        sentence_aggregator.reset()

        async for token in llm_provider.stream(session_id, user_message):
            # Check for interruption
            if not session.get("is_speaking", True):
                logger.info("🛑 Response interrupted")
                break

            # Aggregate tokens into sentences
            sentences = sentence_aggregator.add_token(token)

            # TTS and stream each complete sentence immediately
            for sentence in sentences:
                full_response += sentence + " "
                logger.info(f"📢 Sentence ready: {sentence[:50]}...")

                # Send sentence event to frontend
                await send_message(session_id, {
                    "event": "llm_sentence",
                    "data": {"text": sentence}
                })

                # Stream TTS audio for this sentence
                await stream_tts_to_webrtc(session_id, sentence)

        # Flush remaining text
        remaining = sentence_aggregator.flush()
        if remaining and session.get("is_speaking", True):
            full_response += remaining
            logger.info(f"📢 Final chunk: {remaining[:50]}...")
            await send_message(session_id, {
                "event": "llm_sentence",
                "data": {"text": remaining}
            })
            await stream_tts_to_webrtc(session_id, remaining)

        # Send complete response
        full_response = full_response.strip()
        await send_message(session_id, {
            "event": "agent_response",
            "data": {"text": full_response, "session_id": session_id}
        })

        # Send streaming_complete to signal frontend to restart VAD
        await send_message(session_id, {
            "event": "streaming_complete",
            "data": {"session_id": session_id}
        })

        logger.info(f"✅ Response complete: {len(full_response)} chars")

    except asyncio.CancelledError:
        logger.info(f"Response cancelled for {session_id[:8]}")
        raise
    except Exception as e:
        logger.error(f"❌ Error streaming response: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session["is_speaking"] = False


async def stream_tts_to_webrtc(session_id: str, text: str):
    """
    Convert text to speech and stream to WebRTC.

    Uses FFmpeg for MP3 → PCM conversion (48kHz for Opus).
    """
    if session_id not in webrtc_manager.tracks:
        logger.warning(f"No WebRTC track for {session_id[:8]}")
        return

    session = sessions.get(session_id)
    if not session or not session.get("is_speaking", True):
        return

    try:
        # Get TTS audio stream (MP3 chunks)
        tts_stream = tts_provider.stream_audio(text)

        # Convert MP3 → PCM using FFmpeg and push to WebRTC
        async for pcm_chunk in audio_converter.mp3_to_pcm_stream(tts_stream):
            # Check for interruption
            if not session.get("is_speaking", True):
                break

            # Push PCM to WebRTC track
            await webrtc_manager.push_audio_chunk(session_id, pcm_chunk)

    except Exception as e:
        logger.error(f"❌ TTS streaming error: {e}")


# ============================================================================
# INTERRUPTION HANDLING
# ============================================================================

async def handle_interrupt(session_id: str):
    """Handle user interruption - stop current response immediately."""
    logger.warning(f"🛑 Interrupt received for {session_id[:8]}...")

    session = sessions.get(session_id)
    if session:
        session["is_speaking"] = False

    # Cancel active processing task
    if session_id in active_tasks:
        active_tasks[session_id].cancel()
        del active_tasks[session_id]

    # Flush WebRTC track
    if webrtc_manager and session_id in webrtc_manager.tracks:
        try:
            await webrtc_manager.tracks[session_id].flush()
            await webrtc_manager.replace_audio_track(session_id)
            logger.info(f"🧹 Flushed WebRTC track for {session_id[:8]}")
        except Exception as e:
            logger.error(f"Error flushing track: {e}")

    # Notify frontend
    await send_message(session_id, {
        "event": "voice_interrupted",
        "data": {"session_id": session_id, "action": "flush_audio"}
    })


# ============================================================================
# WEBSOCKET MESSAGE HANDLING
# ============================================================================

async def handle_audio_chunk(session_id: str, data: dict):
    """Handle incoming audio chunk with buffering."""
    audio_data = data.get("audio")
    if not audio_data:
        return

    audio_bytes = base64.b64decode(audio_data)

    if session_id not in audio_buffers:
        return

    buffer = audio_buffers[session_id]
    buffer["chunks"].append(audio_bytes)
    buffer["last_chunk_time"] = time.time()

    logger.debug(f"🎤 Buffered chunk ({len(audio_bytes)} bytes), total: {len(buffer['chunks'])}")

    # Cancel existing processing task
    if buffer["processing_task"] and not buffer["processing_task"].done():
        buffer["processing_task"].cancel()

    # Schedule processing after timeout
    buffer["processing_task"] = asyncio.create_task(
        _process_buffer_after_timeout(session_id)
    )


async def _process_buffer_after_timeout(session_id: str):
    """Process audio buffer after timeout."""
    try:
        await asyncio.sleep(BUFFER_TIMEOUT)

        if session_id not in audio_buffers:
            return

        buffer = audio_buffers[session_id]
        chunks = buffer["chunks"]

        if not chunks:
            return

        logger.info(f"🎙️ Processing {len(chunks)} audio chunks...")

        # Combine chunks
        combined_audio = b''.join(chunks)
        buffer["chunks"] = []

        # Process through pipeline
        task = asyncio.create_task(process_audio(session_id, combined_audio))
        active_tasks[session_id] = task
        await task

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"❌ Error processing buffer: {e}")


async def handle_webrtc_offer(session_id: str, data: dict):
    """Handle WebRTC SDP offer."""
    offer_data = data.get("offer", data)
    sdp = offer_data.get("sdp")
    type_ = offer_data.get("type")

    if not sdp:
        logger.error("No SDP in offer")
        return

    # Get ICE servers
    ice_servers = await fetch_ice_servers(session_id)

    # Create answer
    answer = await webrtc_manager.handle_offer(session_id, sdp, type_, ice_servers=ice_servers)

    if answer:
        await send_message(session_id, {
            "event": "webrtc_answer",
            "data": {"sdp": answer["sdp"], "type": answer["type"], "session_id": session_id}
        })
        logger.info(f"✅ Sent WebRTC answer for {session_id[:8]}")


async def handle_webrtc_ice_candidate(session_id: str, data: dict):
    """Handle WebRTC ICE candidate."""
    candidate = data.get("candidate")
    if candidate:
        await webrtc_manager.handle_ice_candidate(session_id, data)


# ============================================================================
# HTTP ENDPOINTS
# ============================================================================

@app.get("/")
async def root():
    return {
        "service": "Voice Agent Demo (v2)",
        "status": "running",
        "version": "2.0.0",
        "pipeline": "StreamingVoicePipeline"
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "active_sessions": len(sessions),
        "components": {
            "llm": llm_provider is not None,
            "asr": asr_provider is not None,
            "tts": tts_provider is not None,
            "webrtc": webrtc_manager is not None,
            "ffmpeg": audio_converter.is_available() if audio_converter else False,
        }
    }


@app.get("/live")
async def live():
    """Health check endpoint for Render deployment."""
    return {"status": "alive"}


@app.get("/debug/audio")
async def debug_audio():
    """Debug endpoint for audio pipeline."""
    webrtc_info = {}
    if webrtc_manager:
        webrtc_info = {
            "active_connections": len(webrtc_manager.pcs),
            "active_tracks": len(webrtc_manager.tracks),
            "connection_states": {
                sid[:8]: pc.connectionState
                for sid, pc in webrtc_manager.pcs.items()
            }
        }

    return {
        "ffmpeg": {
            "available": audio_converter.is_available() if audio_converter else False,
            "version": audio_converter.get_version() if audio_converter else None,
        },
        "webrtc": webrtc_info,
        "sessions": {sid[:8]: {"is_speaking": s.get("is_speaking")} for sid, s in sessions.items()},
    }


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for voice streaming."""
    session_id = None

    try:
        user_id = websocket.query_params.get("user_id", "anonymous")
        await websocket.accept()
        logger.info("📞 WebSocket connection accepted")

        # Create session
        session_id = await create_session(websocket, user_id)

        # Fetch ICE servers and send welcome
        # NOTE: Frontend expects "connected" event (not "session_started")
        ice_servers = await fetch_ice_servers(session_id)
        await send_message(session_id, {
            "event": "connected",
            "data": {
                "session_id": session_id,
                "message": "Connected to Voice Session",
                "ice_servers": ice_servers,
            }
        })

        # Message loop
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            event = data.get("event")

            if event == "audio_chunk":
                await handle_audio_chunk(session_id, data.get("data", data))
            elif event == "interrupt":
                await handle_interrupt(session_id)
            elif event == "webrtc_offer":
                await handle_webrtc_offer(session_id, data.get("data", data))
            elif event == "webrtc_ice_candidate":
                await handle_webrtc_ice_candidate(session_id, data.get("data", data))
            elif event == "heartbeat":
                pass
            else:
                logger.warning(f"Unknown event: {event}")

    except WebSocketDisconnect:
        logger.info("🔌 WebSocket disconnected")
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
    finally:
        if session_id:
            await cleanup_session(session_id)


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
