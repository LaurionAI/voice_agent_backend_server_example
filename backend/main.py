"""
Minimal Voice Agent Demo Server

A lightweight demonstration of the voice streaming framework with:
- WebSocket + WebRTC voice streaming
- Simple agent with conversation state/memory
- No database, no cache - pure in-memory state
- Single agent node for processing queries

Usage:
    uvicorn main:app --host 0.0.0.0 --port 8000
"""

import asyncio
import logging
import os
from pathlib import Path
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

from datetime import time

from lib.voice_streaming_framework.server.voice_session_manager import VoiceSessionManager
from lib.voice_streaming_framework.webrtc.manager import WebRTCManager
from lib.voice_streaming_framework.tts.factory import get_tts_provider
from lib.voice_streaming_framework.tts.base import TTSConfig
from lib.voice_streaming_framework.audio.validator import AudioValidator
from app.voice_agent.hf_asr import HFSpaceASR
from app.voice_agent.simple_agent import SimpleAgent
from app.voice_agent.streaming_handler import StreamingHandler
from scheduler.daily_asr_scheduler import DailyASRScheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instances
session_manager: VoiceSessionManager = None
webrtc_manager: WebRTCManager = None
tts_provider = None
asr_processor = None
agent: SimpleAgent = None
audio_validator: AudioValidator = None
asr_scheduler: DailyASRScheduler = None
asr_scheduler_task: asyncio.Task = None

# Audio buffering state
# Maps session_id -> {"chunks": [bytes], "last_chunk_time": float}
audio_buffers: dict = {}
BUFFER_TIMEOUT = 1.5  # seconds to wait before processing buffer
MIN_CHUNKS = 1  # Process immediately (frontend sends complete segments via VAD)


def check_ffmpeg_availability():
    """Check if FFmpeg is available in PATH and log diagnostic info."""
    import subprocess
    import shutil

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
        logger.error(f"   Current PATH: {os.environ.get('PATH', 'not set')}")
        logger.error("   This will cause audio output to fail silently!")
        return False


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup global resources."""
    global session_manager, webrtc_manager, tts_provider, asr_processor, agent, audio_validator

    logger.info("🚀 Starting Voice Agent Demo Server...")

    # Log environment info for debugging
    logger.info(f"📍 Environment: {os.environ.get('ENVIRONMENT', 'development')}")
    logger.info(f"📍 Python: {os.sys.version}")
    logger.info(f"📍 Working directory: {os.getcwd()}")

    # Check FFmpeg availability (critical for audio output)
    ffmpeg_ok = check_ffmpeg_availability()
    if not ffmpeg_ok:
        logger.warning("⚠️  Audio output may not work without FFmpeg!")

    # Initialize TTS provider (Edge TTS - free, no API key needed)
    tts_config = TTSConfig(
        voice="zh-CN-XiaoxiaoNeural",  # Chinese female voice
        rate="+0%"
    )
    tts_provider = get_tts_provider("edge-tts", tts_config)
    logger.info("✅ TTS provider initialized (Edge TTS)")

    # Initialize ASR processor (HuggingFace Space - SenseVoiceSmall)
    asr_processor = HFSpaceASR(space_name="hz6666/SenseVoiceSmall")
    logger.info("✅ ASR processor initialized (HF Space - SenseVoiceSmall)")

    # Initialize audio validator with WebRTC VAD
    audio_validator = AudioValidator(
        energy_threshold=500.0,
        vad_mode=3,  # Most aggressive
        enable_webrtc_vad=True,
        speech_ratio_threshold=0.03  # 3% speech required
    )
    logger.info("✅ Audio validator initialized (WebRTC VAD mode=3)")

    # Initialize WebRTC manager
    webrtc_manager = WebRTCManager()
    logger.info("✅ WebRTC manager initialized")

    # Initialize simple agent with conversation memory (GLM-4.5-air)
    agent = SimpleAgent(model="glm-4.5-air", temperature=0.7)
    logger.info("✅ Simple agent initialized (GLM-4.5-air)")

    # Initialize session manager with callbacks
    session_manager = VoiceSessionManager(
        streaming_handler_factory=lambda session_id: StreamingHandler(
            session_id=session_id,
            tts_provider=tts_provider,
            agent=agent
        ),
        webrtc_manager_factory=lambda: webrtc_manager
    )

    # Set up callbacks for session events
    session_manager.on_session_start = handle_session_start
    session_manager.on_session_end = handle_session_end
    session_manager.on_message_received = handle_message_received
    session_manager.on_audio_received = handle_audio_received
    session_manager.on_interruption = handle_interruption
    session_manager.on_ice_servers_fetch = fetch_ice_servers

    logger.info("✅ Session manager initialized")

    # Initialize daily ASR scheduler to keep HF Space alive
    voice_sample_path = Path(__file__).parent / "scheduler" / "voice_sample" / "test_analysis_aapl_deeper.wav"
    if voice_sample_path.exists():
        asr_scheduler = DailyASRScheduler(
            audio_path=str(voice_sample_path),
            run_time=time(hour=9, minute=0)  # Run daily at 9:00 AM
        )
        asr_scheduler_task = asyncio.create_task(asr_scheduler.start())
        logger.info("✅ Daily ASR scheduler started (keeps HF Space alive)")
    else:
        logger.warning(f"⚠️  Voice sample not found at {voice_sample_path}, scheduler not started")

    logger.info("🎉 Server ready! Connect on ws://localhost:8000/ws")

    yield

    # Cleanup
    logger.info("🛑 Shutting down server...")

    # Stop ASR scheduler
    if asr_scheduler:
        asr_scheduler.stop()
    if asr_scheduler_task and not asr_scheduler_task.done():
        asr_scheduler_task.cancel()
        try:
            await asr_scheduler_task
        except asyncio.CancelledError:
            pass
    logger.info("✅ ASR scheduler stopped")

    if webrtc_manager:
        # Close all WebRTC connections
        for session_id in list(webrtc_manager.pcs.keys()):
            await webrtc_manager.close_peer_connection(session_id)
    logger.info("✅ Server shutdown complete")


app = FastAPI(
    title="Voice Agent Demo",
    description="Minimal voice streaming agent with WebRTC",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for frontend connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    from app.api import router as api_router

    app.include_router(api_router)
except ImportError:
    # In case API module is not present, continue without it.
    logger.warning("app.api module not found; API routes not included.")


# ====== EVENT HANDLERS ======

async def handle_session_start(session_id: str, user_id: str, metadata: dict):
    """Called when a new session starts."""
    logger.info(f"📞 Session started: {session_id[:8]}... (user: {user_id[:8]}...)")

    # Initialize conversation state for this session
    agent.create_session(session_id)


async def handle_session_end(session_id: str, user_id: str):
    """Called when a session ends."""
    logger.info(f"👋 Session ended: {session_id[:8]}...")

    # Clean up conversation state
    agent.cleanup_session(session_id)

    # Clean up audio buffer
    if session_id in audio_buffers:
        buffer = audio_buffers[session_id]
        # Cancel any pending processing task
        if buffer.get("processing_task") and not buffer["processing_task"].done():
            buffer["processing_task"].cancel()
        del audio_buffers[session_id]
        logger.info(f"🗑️  Cleaned up audio buffer for {session_id[:8]}...")


async def handle_message_received(session_id: str, event: str, data: dict):
    """Route incoming WebSocket messages."""
    if event == "interrupt":
        await session_manager.handle_interrupt(session_id, data)
    elif event == "webrtc_offer":
        await session_manager.handle_webrtc_offer(session_id, data)
    elif event == "webrtc_ice_candidate":
        await session_manager.handle_webrtc_ice_candidate(session_id, data)
    elif event == "audio_chunk":
        await handle_audio_received(session_id, data)
    elif event == "heartbeat":
        logger.debug(f"💓 Heartbeat from {session_id[:8]}...")
    else:
        logger.warning(f"⚠️ Unknown event: {event}")


async def handle_audio_received(session_id: str, data: dict):
    """Process incoming audio from user with buffering."""
    import base64
    import time

    try:
        # Extract audio data
        audio_data = data.get("audio")
        if not audio_data:
            logger.warning(f"No audio data in message from {session_id[:8]}...")
            return

        audio_bytes = base64.b64decode(audio_data)

        # Initialize buffer for this session if needed
        if session_id not in audio_buffers:
            audio_buffers[session_id] = {
                "chunks": [],
                "last_chunk_time": time.time(),
                "processing_task": None
            }

        buffer = audio_buffers[session_id]

        # Add chunk to buffer
        buffer["chunks"].append(audio_bytes)
        buffer["last_chunk_time"] = time.time()

        logger.info(f"🎤 Buffered audio chunk ({len(audio_bytes)} bytes), total chunks: {len(buffer['chunks'])}")

        # Cancel any existing processing task
        if buffer["processing_task"] and not buffer["processing_task"].done():
            buffer["processing_task"].cancel()

        # Schedule processing after timeout
        buffer["processing_task"] = asyncio.create_task(
            _process_audio_buffer_after_timeout(session_id)
        )

    except Exception as e:
        logger.error(f"❌ Error buffering audio: {e}")
        import traceback
        traceback.print_exc()


async def _process_audio_buffer_after_timeout(session_id: str):
    """Process accumulated audio chunks after timeout."""
    try:
        # Wait for timeout
        await asyncio.sleep(BUFFER_TIMEOUT)

        # Get buffer
        if session_id not in audio_buffers:
            return

        buffer = audio_buffers[session_id]
        chunks = buffer["chunks"]

        # Check if we have enough chunks
        if len(chunks) < MIN_CHUNKS:
            logger.info(f"🔇 Not enough chunks ({len(chunks)} < {MIN_CHUNKS}), skipping")
            buffer["chunks"] = []
            return

        logger.info(f"🎙️  Processing {len(chunks)} audio chunks...")

        # Combine all chunks into single audio buffer
        combined_audio = b''.join(chunks)

        # Clear buffer for next round
        buffer["chunks"] = []

        # Validate audio before ASR
        is_valid, validation_info = audio_validator.validate_audio(
            combined_audio,
            sample_rate=16000,  # WebM audio is 16kHz
            format="webm"
        )

        energy = validation_info.get("energy", 0.0)
        speech_ratio = validation_info.get("speech_ratio", 0.0)

        if not is_valid:
            reason = validation_info.get("reason", "unknown")
            logger.info(f"🔇 Audio validation failed: {reason} (energy={energy:.1f}, speech_ratio={speech_ratio:.2f})")
            return

        logger.info(f"✅ Audio validated: energy={energy:.1f}, speech_ratio={speech_ratio:.2f}")
        logger.info(f"🎤 Transcribing combined audio ({len(combined_audio)} bytes)...")
        transcript = await asr_processor.transcribe(combined_audio)

        if not transcript or len(transcript.strip()) < 2:
            logger.info(f"🔇 Empty/short transcript, ignoring")
            # Send explicit event so frontend knows to continue listening
            await session_manager.send_message(session_id, {
                "event": "no_speech_detected",
                "data": {
                    "message": "No speech detected in audio",
                    "session_id": session_id
                }
            })
            return

        logger.info(f"📝 Transcript: {transcript}")

        # Send transcript to frontend
        await session_manager.send_message(session_id, {
            "event": "transcript",
            "data": {
                "text": transcript,
                "session_id": session_id
            }
        })

        # Process query with agent
        logger.info(f"🤖 Processing query with agent...")
        response = await agent.process_query(session_id, transcript)

        logger.info(f"💬 Agent response: {response[:100]}...")

        # Send text response
        await session_manager.send_message(session_id, {
            "event": "agent_response",
            "data": {
                "text": response,
                "session_id": session_id
            }
        })

        # Stream TTS audio back via WebRTC
        logger.info(f"🔊 Starting TTS streaming for session {session_id[:8]}...")
        logger.info(f"   Response length: {len(response)} chars")
        streaming_handler = StreamingHandler(
            session_id=session_id,
            tts_provider=tts_provider,
            agent=agent
        )
        try:
            await session_manager.stream_tts_response(session_id, response, streaming_handler)
            logger.info(f"✅ TTS streaming completed for session {session_id[:8]}...")
        except Exception as tts_error:
            logger.error(f"❌ TTS streaming failed for session {session_id[:8]}...: {tts_error}")
            import traceback
            traceback.print_exc()

    except asyncio.CancelledError:
        # Task was cancelled because a new chunk arrived
        logger.debug(f"Processing task cancelled for {session_id[:8]}... (new chunk arrived)")
    except Exception as e:
        logger.error(f"❌ Error processing audio buffer: {e}")
        import traceback
        traceback.print_exc()


async def handle_interruption(session_id: str, data: dict):
    """Handle user interruption."""
    logger.warning(f"🛑 User interrupted session {session_id[:8]}...")
    # Agent can reset context or handle interruption
    agent.handle_interruption(session_id)


async def fetch_ice_servers(session_id: str) -> list:
    """Fetch STUN/TURN servers for WebRTC."""
    # Use free STUN servers (no TURN for this demo)
    return [
        {
            "urls": "stun:stun.l.google.com:19302"
        },
        {
            "urls": "stun:stun1.l.google.com:19302"
        }
    ]


# ====== HTTP ENDPOINTS ======

@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "service": "Voice Agent Demo",
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "websocket": "/ws",
            "health": "/health"
        }
    }


@app.get("/health")
async def health():
    """Detailed health status."""
    return {
        "status": "healthy",
        "active_sessions": session_manager.get_active_connections_count() if session_manager else 0,
        "components": {
            "tts": tts_provider is not None,
            "asr": asr_processor is not None,
            "webrtc": webrtc_manager is not None,
            "agent": agent is not None
        }
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for voice streaming."""
    session_id = None
    try:
        # Extract user ID from query params (or use anonymous)
        user_id = websocket.query_params.get("user_id", "anonymous")

        # Accept WebSocket connection
        await websocket.accept()
        logger.info(f"📞 WebSocket connection accepted")

        # Create session
        session_id = await session_manager.connect(
            websocket=websocket,
            user_id=user_id,
            session_metadata={
                "client_ip": websocket.client.host if websocket.client else "unknown"
            }
        )

        # Listen for messages
        while True:
            message = await websocket.receive_text()
            await session_manager.process_message(websocket, message)

    except WebSocketDisconnect:
        logger.info(f"🔌 WebSocket disconnected")
        if session_id:
            await session_manager.disconnect(session_id)
    except Exception as e:
        logger.error(f"❌ WebSocket error: {e}")
        if session_id:
            await session_manager.disconnect(session_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
