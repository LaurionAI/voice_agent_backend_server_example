"""Generic voice session manager for WebSocket + WebRTC streaming.

This is the FRAMEWORK part - contains ZERO app-specific dependencies.
Provides core infrastructure for voice streaming sessions.
"""
import asyncio
import json
import uuid
import logging
import base64
import time
from typing import Dict, Any, Optional, Set, Callable
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect


logger = logging.getLogger(__name__)


class VoiceSessionManager:
    """
    Generic WebSocket session manager for voice streaming.

    This class handles all generic voice session infrastructure:
    - WebSocket connection lifecycle
    - WebRTC offer/answer/ICE handling
    - Audio streaming (TTS -> WebRTC)
    - Interruption handling
    - Message routing

    App-specific logic (database, cache, agent, tier checking) is provided via callbacks.
    """

    def __init__(
        self,
        streaming_handler_factory: Optional[Callable] = None,
        webrtc_manager_factory: Optional[Callable] = None
    ):
        """
        Initialize session manager.

        Args:
            streaming_handler_factory: Callable that creates streaming handler
            webrtc_manager_factory: Callable that returns WebRTC manager
        """
        # Core session state
        self.active_connections: Dict[str, WebSocket] = {}
        self.user_sessions: Dict[str, str] = {}  # user_id -> session_id
        self.session_data: Dict[str, Dict[str, Any]] = {}  # session_id -> data

        # Streaming state
        self.streaming_tasks: Dict[str, bool] = {}  # session_id -> should_stop_streaming
        self.tts_streaming_tasks: Dict[str, asyncio.Task] = {}  # session_id -> Task
        self.tts_chunk_counts: Dict[str, int] = {}  # session_id -> chunk_count
        self.ffmpeg_processes: Dict[str, Any] = {}  # session_id -> subprocess

        # Factories (injected by app)
        self.streaming_handler_factory = streaming_handler_factory
        self.webrtc_manager_factory = webrtc_manager_factory

        # Callbacks (optional, for app-specific logic)
        self.on_session_start: Optional[Callable] = None
        self.on_session_end: Optional[Callable] = None
        self.on_message_received: Optional[Callable] = None
        self.on_audio_received: Optional[Callable] = None
        self.on_interruption: Optional[Callable] = None
        self.on_ice_servers_fetch: Optional[Callable] = None  # Returns List[Dict]

        # Error throttling
        self.last_error_times: Dict[str, float] = {}
        self.error_throttle_seconds = 1.0

    def _is_valid_uuid(self, uuid_string: str) -> bool:
        """Check if string is a valid UUID."""
        try:
            uuid.UUID(uuid_string)
            return True
        except ValueError:
            return False

    def _should_log_error(self, error_key: str) -> bool:
        """Check if error should be logged (throttle to max 1 per second per type)."""
        current_time = time.time()
        last_time = self.last_error_times.get(error_key, 0)

        if current_time - last_time >= self.error_throttle_seconds:
            self.last_error_times[error_key] = current_time
            return True
        return False

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        session_metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Accept WebSocket connection and create session.

        Args:
            websocket: FastAPI WebSocket connection
            user_id: User identifier
            session_metadata: Optional metadata (e.g., subscription_tier, client_ip)

        Returns:
            session_id: Unique session identifier
        """
        try:
            # Generate proper UUID for user_id if it's not already a UUID
            if user_id == "anonymous" or not self._is_valid_uuid(user_id):
                user_id = str(uuid.uuid4())
                logger.info(f"Generated UUID for anonymous user: {user_id[:8]}...")

            # Create new session
            session_id = str(uuid.uuid4())

            # Build session data
            session_data = {
                "user_id": user_id,
                "websocket": websocket,
                "session_start": datetime.now(),
                "total_commands": 0,
                "total_interruptions": 0,
                "is_active": True,
                **(session_metadata or {})
            }

            # Store connections
            self.active_connections[session_id] = websocket
            self.user_sessions[user_id] = session_id
            self.session_data[session_id] = session_data

            logger.info(f"✅ WebSocket connected: session={session_id[:8]}..., user={user_id[:8]}...")

            # Call app callback
            if self.on_session_start:
                await self.on_session_start(session_id, user_id, session_metadata)

            # Small delay to ensure WebSocket is fully ready
            await asyncio.sleep(0.01)

            # Fetch ICE servers (TURN/STUN) via callback
            ice_servers = []
            if self.on_ice_servers_fetch:
                ice_servers = await self.on_ice_servers_fetch(session_id)

            # Store ICE servers for WebRTC offer handling
            self.session_data[session_id]["ice_servers"] = ice_servers

            # Send welcome message
            connected_message = {
                "event": "connected",
                "data": {
                    "session_id": session_id,
                    "message": "Connected to Voice Session",
                    "timestamp": datetime.now().isoformat(),
                    "ice_servers": ice_servers
                }
            }

            # Try to send welcome message with retries
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    await self.send_message(session_id, connected_message, raise_on_error=True)
                    logger.info(f"session={session_id[:8]}... | Successfully sent connected message (attempt {attempt + 1})")
                    break
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Retry sending connected message (attempt {attempt + 1}): {e}")
                        await asyncio.sleep(0.05)
                    else:
                        logger.error(f"All retries exhausted: {e}")
                        raise

            return session_id

        except Exception as e:
            logger.error(f"❌ Error connecting WebSocket: {e}")
            raise

    async def disconnect(self, session_id: str):
        """Handle WebSocket disconnection."""
        try:
            if session_id not in self.active_connections:
                return

            # Update session end time
            if session_id in self.session_data:
                self.session_data[session_id]["session_end"] = datetime.now()
                self.session_data[session_id]["is_active"] = False

            # Get user_id before cleanup
            user_id = self.session_data.get(session_id, {}).get("user_id")

            # Remove from active connections
            websocket = self.active_connections.pop(session_id)

            # Remove user session mapping
            if user_id and user_id in self.user_sessions:
                del self.user_sessions[user_id]

            # Clean up WebRTC peer connection
            if self.webrtc_manager_factory:
                webrtc = self.webrtc_manager_factory()
                await webrtc.close_peer_connection(session_id)

            # Call app callback
            if self.on_session_end:
                await self.on_session_end(session_id, user_id)

            # Clean up session data
            if session_id in self.session_data:
                del self.session_data[session_id]

            # Clean up TTS chunk count
            if session_id in self.tts_chunk_counts:
                del self.tts_chunk_counts[session_id]

            # Clean up FFmpeg process
            if session_id in self.ffmpeg_processes:
                process = self.ffmpeg_processes[session_id]
                try:
                    if process.returncode is None:
                        process.terminate()
                        logger.info(f"🛑 Terminated FFmpeg process for session {session_id}")
                except Exception as e:
                    logger.error(f"Error terminating FFmpeg: {e}")
                finally:
                    del self.ffmpeg_processes[session_id]

            logger.info(f"✅ WebSocket disconnected: {session_id[:8]}...")

        except Exception as e:
            logger.error(f"❌ Error disconnecting WebSocket: {e}")

    async def send_message(
        self,
        session_id: str,
        message: Dict[str, Any],
        raise_on_error: bool = False
    ):
        """
        Send message to specific WebSocket connection.

        Args:
            session_id: Session ID
            message: Message dict to send
            raise_on_error: If True, raise exception on send failure (for retry logic)
        """
        try:
            if session_id not in self.active_connections:
                if self._should_log_error(f"ws_not_found_{session_id}"):
                    logger.warning(f"WebSocket not found for session {session_id[:8]}...")
                if raise_on_error:
                    raise RuntimeError(f"WebSocket not found for session {session_id}")
                return

            websocket = self.active_connections[session_id]

            # Check if websocket is in correct state
            from starlette.websockets import WebSocketState
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(f"WebSocket not in CONNECTED state: {websocket.client_state.name}")
                if raise_on_error:
                    raise RuntimeError(f"WebSocket not in CONNECTED state: {websocket.client_state.name}")
                return

            # Log message being sent
            event = message.get("event", "unknown")
            logger.debug(f"session={session_id[:8]}... | Sending event: {event}")

            await websocket.send_text(json.dumps(message))

        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"

            # Check if this is an expected "already closed" error
            is_already_closed = (
                "Cannot call \"send\" once a close message has been sent" in str(e) or
                "WebSocket is not connected" in str(e)
            )

            # Only log unexpected errors
            if not is_already_closed and self._should_log_error(f"ws_send_error_{session_id}"):
                logger.error(f"session={session_id[:8]}... | Error sending message: {error_msg}")
            elif is_already_closed:
                logger.debug(f"session={session_id[:8]}... | WebSocket already closed")

            # If requested to raise, propagate the error
            if raise_on_error:
                raise

            # Otherwise, disconnect if WebSocket is actually closed
            if session_id in self.active_connections:
                websocket = self.active_connections[session_id]
                from starlette.websockets import WebSocketState
                if websocket.client_state == WebSocketState.DISCONNECTED:
                    logger.warning(f"WebSocket disconnected for session {session_id[:8]}...")
                    await self.disconnect(session_id)

    async def broadcast_message(
        self,
        message: Dict[str, Any],
        exclude: Optional[Set[str]] = None
    ):
        """Broadcast message to all active connections."""
        exclude = exclude or set()

        for session_id in list(self.active_connections.keys()):
            if session_id not in exclude:
                await self.send_message(session_id, message)

    async def handle_interrupt(self, session_id: str, data: Dict[str, Any]):
        """Handle voice interruption with immediate audio cancellation."""
        try:
            interrupt_start = time.time()

            if session_id in self.session_data:
                self.session_data[session_id]["total_interruptions"] += 1

            # Call app callback
            if self.on_interruption:
                await self.on_interruption(session_id, data)

            # 1. Set interrupt flag (stops NEW audio generation)
            self.streaming_tasks[session_id] = True
            logger.warning(f"🛑 Interrupt signal received for session {session_id[:8]}...")

            # 1a. Cancel background TTS task if running
            if session_id in self.tts_streaming_tasks:
                task = self.tts_streaming_tasks[session_id]
                if not task.done():
                    task.cancel()
                    logger.info(f"🛑 Cancelled background TTS task for {session_id[:8]}...")
                    try:
                        await asyncio.wait_for(task, timeout=0.5)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
                self.tts_streaming_tasks.pop(session_id, None)

            # 2. Kill FFmpeg process if running
            if session_id in self.ffmpeg_processes:
                process = self.ffmpeg_processes[session_id]
                try:
                    if process.returncode is None:
                        process.terminate()
                        logger.info(f"🛑 Terminated FFmpeg process for {session_id[:8]}...")
                except Exception as e:
                    logger.error(f"Error terminating FFmpeg: {e}")

            # 3. Flush WebRTC track buffer
            if self.webrtc_manager_factory:
                webrtc = self.webrtc_manager_factory()
                if session_id in webrtc.tracks:
                    try:
                        await webrtc.tracks[session_id].flush()
                        logger.info(f"🧹 Flushed WebRTC track buffer for {session_id[:8]}...")

                        # Replace track to drop sender-side buffered frames
                        await webrtc.replace_audio_track(session_id)
                        logger.info(f"🔁 Replaced WebRTC track after interrupt for {session_id[:8]}...")
                    except Exception as e:
                        logger.error(f"Error flushing WebRTC track: {e}")

            # Calculate interrupt processing time
            interrupt_time_ms = int((time.time() - interrupt_start) * 1000)

            # 4. Send interruption signal to frontend
            await self.send_message(session_id, {
                "event": "voice_interrupted",
                "data": {
                    "session_id": session_id,
                    "reason": data.get("reason", "user_interruption"),
                    "action": "flush_audio",
                    "interruption_time_ms": interrupt_time_ms,
                    "timestamp": datetime.now().isoformat()
                }
            })

            logger.warning(f"✅ Full interrupt executed for {session_id[:8]}... in {interrupt_time_ms}ms")

        except Exception as e:
            logger.error(f"❌ Error handling interrupt: {e}")

    async def handle_webrtc_offer(self, session_id: str, data: Dict[str, Any]):
        """Handle WebRTC SDP offer."""
        try:
            logger.info(f"📞 handle_webrtc_offer called for {session_id[:8]}..., data keys: {data.keys()}")
            # Extract offer - handle both {sdp, type} and {offer: {sdp, type}} structures
            offer_data = data.get("offer", data)
            sdp = offer_data.get("sdp")
            type = offer_data.get("type")

            if not sdp or not type:
                logger.error(f"❌ Invalid WebRTC offer data for {session_id[:8]}...: sdp={bool(sdp)}, type={type}, data={data}")
                return

            logger.info(f"📞 Received valid WebRTC offer for {session_id[:8]}..., SDP length: {len(sdp)}")

            # Retrieve ICE servers for this session
            ice_servers = self.session_data.get(session_id, {}).get("ice_servers", [])
            if ice_servers:
                logger.info(f"🔧 Using {len(ice_servers)} cached ICE servers")

            # Handle offer via WebRTC manager
            if not self.webrtc_manager_factory:
                logger.error("❌ No WebRTC manager factory configured")
                return

            webrtc = self.webrtc_manager_factory()
            answer = await webrtc.handle_offer(session_id, sdp, type, ice_servers=ice_servers)

            if answer:
                # Mark session as WebRTC enabled
                if session_id in self.session_data:
                    self.session_data[session_id]["webrtc_enabled"] = True

                # Send answer back
                await self.send_message(session_id, {
                    "event": "webrtc_answer",
                    "data": {
                        "sdp": answer["sdp"],
                        "type": answer["type"],
                        "session_id": session_id
                    }
                })
                logger.info(f"✅ Sent WebRTC answer for {session_id[:8]}...")
            else:
                logger.error(f"❌ Failed to generate WebRTC answer for {session_id[:8]}...")

        except Exception as e:
            logger.error(f"❌ Error handling WebRTC offer: {e}")
            import traceback
            traceback.print_exc()

    async def handle_webrtc_ice_candidate(self, session_id: str, data: Dict[str, Any]):
        """Handle WebRTC ICE candidate from client."""
        try:
            candidate = data.get("candidate")

            if not candidate:
                logger.warning(f"Empty ICE candidate for {session_id[:8]}...")
                return

            logger.info(f"📞 Received ICE candidate for {session_id[:8]}...")

            if not self.webrtc_manager_factory:
                logger.error("❌ No WebRTC manager factory configured")
                return

            webrtc = self.webrtc_manager_factory()
            await webrtc.handle_ice_candidate(session_id, data)

        except Exception as e:
            logger.error(f"❌ Error handling ICE candidate: {e}")

    async def _stream_tts_to_webrtc(self, session_id: str, text: str, streaming_handler: Any):
        """
        Stream TTS audio to WebRTC track using FFmpeg for real-time MP3->PCM conversion.

        Args:
            session_id: Session identifier
            text: Text to synthesize
            streaming_handler: Handler with stream_tts_audio method
        """
        import subprocess
        import asyncio
        import shutil

        # Use print() for guaranteed output in production
        print(f"🎙️ [TTS->WebRTC] Starting for session {session_id[:8]}...")
        print(f"   Text length: {len(text)} chars")
        logger.info(f"🎙️ [TTS->WebRTC] Starting for session {session_id[:8]}...")
        logger.info(f"   Text length: {len(text)} chars, preview: {text[:80]}...")

        if not self.webrtc_manager_factory:
            print("❌ [TTS->WebRTC] No WebRTC manager factory configured")
            logger.error("❌ No WebRTC manager factory configured")
            return

        webrtc = self.webrtc_manager_factory()

        # Check if track exists for this session
        if session_id not in webrtc.tracks:
            print(f"❌ [TTS->WebRTC] No WebRTC track found for session {session_id[:8]}...")
            print(f"   Available tracks: {list(webrtc.tracks.keys())}")
            logger.error(f"❌ No WebRTC track found for session {session_id[:8]}...")
            logger.error(f"   Available tracks: {list(webrtc.tracks.keys())}")
            return

        # Check FFmpeg availability before starting
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            print(f"❌ [TTS->WebRTC] FFmpeg not found in PATH!")
            print(f"   PATH: {subprocess.os.environ.get('PATH', 'not set')}")
            logger.error(f"❌ FFmpeg not found in PATH! Audio output will fail.")
            logger.error(f"   PATH: {subprocess.os.environ.get('PATH', 'not set')}")
            return
        print(f"   [TTS->WebRTC] FFmpeg path: {ffmpeg_path}")
        logger.info(f"   FFmpeg path: {ffmpeg_path}")

        # Start FFmpeg process for streaming conversion
        ffmpeg_cmd = [
            'ffmpeg',
            '-i', 'pipe:0',       # Input from stdin
            '-f', 's16le',        # Output format PCM 16-bit little-endian
            '-ac', '1',           # Mono
            '-ar', '48000',       # Sample rate (48kHz for Opus)
            '-acodec', 'pcm_s16le',
            'pipe:1'              # Output to stdout
        ]
        logger.info(f"   FFmpeg command: {' '.join(ffmpeg_cmd)}")

        try:
            print(f"   [TTS->WebRTC] Creating FFmpeg subprocess...")
            logger.info(f"   Creating FFmpeg subprocess...")
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            print(f"   ✅ [TTS->WebRTC] FFmpeg process created (PID: {process.pid})")
            logger.info(f"   ✅ FFmpeg process created (PID: {process.pid})")

            # Store process for interrupt cleanup
            self.ffmpeg_processes[session_id] = process

            # Shared state for tracking chunks
            mp3_chunk_count = 0
            pcm_chunk_count = 0

            async def write_input():
                """Write TTS chunks to FFmpeg stdin."""
                nonlocal mp3_chunk_count
                total_bytes = 0
                try:
                    print(f"📥 [write_input] Starting TTS stream...")
                    logger.info(f"📥 [write_input] Starting TTS stream for session {session_id[:8]}...")

                    async for chunk in streaming_handler.stream_tts_audio(text):
                        if self.streaming_tasks.get(session_id, False):
                            print(f"🛑 [write_input] Interrupted")
                            logger.warning(f"🛑 [write_input] Interrupted for session {session_id[:8]}...")
                            break

                        process.stdin.write(chunk)
                        await process.stdin.drain()
                        mp3_chunk_count += 1
                        total_bytes += len(chunk)

                        # Log first few chunks and then every 10th
                        if mp3_chunk_count <= 3:
                            print(f"📥 [write_input] MP3 chunk #{mp3_chunk_count}: {len(chunk)} bytes")
                        if mp3_chunk_count <= 3 or mp3_chunk_count % 10 == 0:
                            logger.info(f"📥 [write_input] MP3 chunk #{mp3_chunk_count}: {len(chunk)} bytes")

                    print(f"📥 [write_input] Complete: {mp3_chunk_count} chunks, {total_bytes} bytes")
                    logger.info(f"📥 [write_input] Complete: {mp3_chunk_count} MP3 chunks, {total_bytes} bytes total")
                    process.stdin.close()
                except Exception as e:
                    print(f"❌ [write_input] Error: {e}")
                    logger.error(f"❌ [write_input] Error: {e}")
                    import traceback
                    traceback.print_exc()

            async def read_output():
                """Read PCM chunks from FFmpeg stdout and push to WebRTC."""
                nonlocal pcm_chunk_count
                total_pcm_bytes = 0
                push_errors = 0
                try:
                    # Read in 1920-byte chunks (20ms at 48kHz, mono, 16-bit)
                    chunk_size = 1920
                    print(f"📤 [read_output] Starting PCM stream...")
                    logger.info(f"📤 [read_output] Starting PCM stream for session {session_id[:8]}...")

                    while True:
                        if self.streaming_tasks.get(session_id, False):
                            print(f"🛑 [read_output] Interrupted at chunk {pcm_chunk_count}")
                            logger.warning(f"🛑 [read_output] Interrupted at chunk {pcm_chunk_count}")
                            break

                        chunk = await process.stdout.read(chunk_size)
                        if not chunk:
                            print(f"📤 [read_output] EOF after {pcm_chunk_count} chunks")
                            logger.info(f"📤 [read_output] EOF reached after {pcm_chunk_count} chunks")
                            break

                        pcm_chunk_count += 1
                        total_pcm_bytes += len(chunk)

                        try:
                            await webrtc.push_audio_chunk(session_id, chunk)
                        except Exception as push_e:
                            push_errors += 1
                            if push_errors <= 3:
                                print(f"❌ [read_output] Push error #{push_errors}: {push_e}")
                                logger.error(f"❌ [read_output] Push error #{push_errors}: {push_e}")

                        # Log first few chunks and then every 50th
                        if pcm_chunk_count <= 3:
                            print(f"📤 [read_output] PCM chunk #{pcm_chunk_count} -> WebRTC")
                            logger.info(f"📤 [read_output] PCM chunk #{pcm_chunk_count}: {len(chunk)} bytes -> WebRTC")
                        elif pcm_chunk_count % 50 == 0:
                            audio_duration = pcm_chunk_count * 0.02
                            logger.info(f"📤 [read_output] Progress: chunk #{pcm_chunk_count}, duration: {audio_duration:.2f}s")

                    total_audio_duration = pcm_chunk_count * 0.02
                    print(f"📤 [read_output] Complete: {pcm_chunk_count} chunks, {total_audio_duration:.2f}s audio")
                    logger.info(f"📤 [read_output] Complete: {pcm_chunk_count} PCM chunks, {total_pcm_bytes} bytes")
                    logger.info(f"📊 [read_output] Audio duration: {total_audio_duration:.2f}s, push errors: {push_errors}")
                except Exception as e:
                    print(f"❌ [read_output] Error: {e}")
                    logger.error(f"❌ [read_output] Error: {e}")
                    import traceback
                    traceback.print_exc()

            async def log_ffmpeg_errors():
                """Log FFmpeg errors/warnings from stderr."""
                try:
                    while True:
                        line = await process.stderr.readline()
                        if not line:
                            break
                        line_text = line.decode('utf-8', errors='ignore').strip()
                        if line_text:
                            if 'error' in line_text.lower() or 'warning' in line_text.lower():
                                logger.warning(f"⚠️ FFmpeg stderr: {line_text}")
                            else:
                                logger.debug(f"ℹ️ FFmpeg info: {line_text}")
                except Exception as e:
                    logger.error(f"Error reading FFmpeg stderr: {e}")

            # Run all tasks concurrently
            await asyncio.gather(write_input(), read_output(), log_ffmpeg_errors())

            # Update TTS chunk count
            self.tts_chunk_counts[session_id] = mp3_chunk_count

            # Cleanup
            try:
                if process.returncode is None:
                    process.terminate()
                    await process.wait()
                logger.info(f"✅ FFmpeg process completed (exit code: {process.returncode})")
            except Exception as e:
                logger.error(f"Error cleaning up FFmpeg process: {e}")
            finally:
                self.ffmpeg_processes.pop(session_id, None)

        except Exception as e:
            logger.error(f"❌ Error in WebRTC TTS streaming: {e}")
            self.ffmpeg_processes.pop(session_id, None)

    async def stream_tts_response(
        self,
        session_id: str,
        text: str,
        streaming_handler: Any
    ):
        """
        Stream TTS audio back to client via WebRTC.

        Args:
            session_id: Session identifier
            text: Text to synthesize
            streaming_handler: Handler with stream_tts_audio method
        """
        # Use print() for guaranteed output in production
        print(f"🔊 [stream_tts_response] Called for session {session_id[:8]}...")
        logger.info(f"🔊 [stream_tts_response] Called for session {session_id[:8]}...")

        # Check if session exists
        session_data = self.session_data.get(session_id, {})
        if not session_data:
            print(f"❌ [stream_tts_response] Session {session_id[:8]}... not found!")
            logger.error(f"❌ [stream_tts_response] Session {session_id[:8]}... not found!")
            logger.error(f"   Active sessions: {list(self.session_data.keys())[:5]}")
            return

        # Check if WebRTC is enabled for this session
        webrtc_enabled = session_data.get("webrtc_enabled", False)
        print(f"   [stream_tts_response] webrtc_enabled={webrtc_enabled}")
        logger.info(f"   webrtc_enabled={webrtc_enabled}")
        logger.info(f"   Session data keys: {list(session_data.keys())}")

        if not webrtc_enabled:
            logger.error(f"❌ [stream_tts_response] WebRTC not enabled for session {session_id[:8]}...")
            logger.error(f"   This means WebRTC offer/answer exchange didn't complete!")
            logger.error(f"   Check if frontend is sending 'webrtc_offer' event")
            await self.send_message(session_id, {
                "event": "error",
                "data": {
                    "error_type": "webrtc_not_ready",
                    "message": "WebRTC audio channel not established",
                    "session_id": session_id
                }
            })
            return

        # Check if WebRTC manager and track are available
        if self.webrtc_manager_factory:
            webrtc = self.webrtc_manager_factory()
            track_exists = session_id in webrtc.tracks
            pc_exists = session_id in webrtc.pcs
            logger.info(f"   WebRTC track exists: {track_exists}")
            logger.info(f"   WebRTC peer connection exists: {pc_exists}")
            if pc_exists:
                pc = webrtc.pcs[session_id]
                logger.info(f"   WebRTC connection state: {pc.connectionState}")

        logger.info(f"📞 [stream_tts_response] Routing TTS to WebRTC for session {session_id[:8]}...")
        await self._stream_tts_to_webrtc(session_id, text, streaming_handler)

        # Check if WebSocket is still active before sending completion event
        if session_id in self.active_connections:
            await self.send_message(session_id, {
                "event": "streaming_complete",
                "data": {
                    "session_id": session_id,
                    "timestamp": datetime.now().isoformat()
                }
            })
            logger.info(f"✅ WebRTC TTS streaming complete for session {session_id[:8]}...")
        else:
            logger.debug(f"🔌 WebSocket already closed for session {session_id[:8]}...")

    async def process_message(self, websocket: WebSocket, message: str):
        """
        Process incoming WebSocket message.

        This is a simple router - actual message handling is done via callbacks.

        Args:
            websocket: WebSocket connection
            message: Raw message string
        """
        try:
            data = json.loads(message)
            event = data.get("event")
            # Check top-level first, then inside data for backwards compatibility
            session_id = data.get("session_id") or data.get("data", {}).get("session_id")

            if not session_id:
                logger.warning("No session_id in message")
                return

            # Check if session is still active
            if session_id not in self.active_connections:
                logger.warning(f"Session {session_id[:8]}... no longer active, ignoring message")
                return

            logger.debug(f"session={session_id[:8]}... | Received event: {event}")

            # Call app callback for message processing
            if self.on_message_received:
                await self.on_message_received(session_id, event, data.get("data", {}))
            else:
                # Default handlers for framework-level events
                if event == "interrupt":
                    await self.handle_interrupt(session_id, data.get("data", {}))
                elif event == "webrtc_offer":
                    await self.handle_webrtc_offer(session_id, data.get("data", {}))
                elif event == "webrtc_ice_candidate":
                    await self.handle_webrtc_ice_candidate(session_id, data.get("data", {}))
                elif event == "heartbeat":
                    logger.debug(f"💓 Heartbeat received from session {session_id[:8]}...")
                else:
                    logger.warning(f"⚠️ Unhandled event: {event}")

        except json.JSONDecodeError:
            logger.error("❌ Invalid JSON in WebSocket message")
        except Exception as e:
            logger.error(f"❌ Error processing WebSocket message: {e}")

    def get_active_connections_count(self) -> int:
        """Get count of active connections."""
        return len(self.active_connections)

    def get_session_info(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session information."""
        return self.session_data.get(session_id)

    def get_user_session(self, user_id: str) -> Optional[str]:
        """Get session ID for user."""
        return self.user_sessions.get(user_id)
