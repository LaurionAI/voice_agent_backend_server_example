
import asyncio
import fractions
import time
import logging
import numpy as np
from typing import Optional
from av import AudioFrame
from aiortc import MediaStreamTrack

logger = logging.getLogger("webrtc.tracks")

class TTSAudioTrack(MediaStreamTrack):
    """
    A MediaStreamTrack that consumes PCM audio chunks from a queue
    and yields them as AudioFrames for WebRTC streaming.

    Implements queue size backpressure to prevent excessive buffering.
    """
    kind = "audio"

    # OPTION 3: Queue Size Backpressure
    # Limit queue to 50 frames (1 second of audio @ 20ms per frame)
    # This prevents dumping all audio immediately and allows interruption to work
    MAX_QUEUE_SIZE = 50  # 50 frames × 20ms = 1000ms = 1 second buffer

    def __init__(self, track_id: str):
        super().__init__()
        # Note: MediaStreamTrack.id is auto-generated, we store custom ID separately
        self.track_label = track_id
        self.audio_queue = asyncio.Queue()
        self._start_time = None
        self.sample_rate = 48000  # Opus standard sample rate (not 24kHz!)

        # 20ms frame size for WebRTC/Opus at 48kHz
        # 48000 Hz * 0.020s = 960 samples
        self.samples_per_frame = 960
        self.bytes_per_sample = 2  # 16-bit
        self.bytes_per_frame = self.samples_per_frame * self.bytes_per_sample  # 1920 bytes

        self.buffer = bytearray()
        self.pts = 0

        # Backpressure tracking for checkpoints
        self._total_chunks_pushed = 0
        self._total_wait_time = 0.0
        self._backpressure_count = 0
        
    async def add_frame(self, pcm_data: bytes):
        """
        Add raw PCM data to the queue with backpressure.

        OPTION 3: Queue Size Backpressure Implementation
        - Waits if queue is full (>= MAX_QUEUE_SIZE)
        - Producer automatically throttled to match consumer's rate
        - Prevents dumping all 60s of audio in 1.3s
        """
        wait_start = None

        # BACKPRESSURE: Wait while queue is full
        while self.audio_queue.qsize() >= self.MAX_QUEUE_SIZE:
            if wait_start is None:
                wait_start = time.time()
                self._backpressure_count += 1

                # Only log first 10 backpressure events, then every 500th event to reduce noise
                if self._backpressure_count <= 10 or self._backpressure_count % 500 == 0:
                    queue_size = self.audio_queue.qsize()
                    logger.info(
                        f"🔍 CHECKPOINT 10a: BACKPRESSURE TRIGGERED - Queue full "
                        f"({queue_size}/{self.MAX_QUEUE_SIZE} frames = {queue_size * 0.02:.2f}s buffered). "
                        f"Waiting for consumer... (backpressure event #{self._backpressure_count})"
                    )

            # Wait 10ms and check again
            await asyncio.sleep(0.01)

        # Track wait time if we had to wait
        if wait_start is not None:
            wait_duration = time.time() - wait_start
            self._total_wait_time += wait_duration

            # Only log first 10 releases, then every 500th to reduce noise
            if self._backpressure_count <= 10 or self._backpressure_count % 500 == 0:
                logger.info(
                    f"🔍 CHECKPOINT 10b: BACKPRESSURE RELEASED - Waited {wait_duration:.3f}s, "
                    f"queue now has space ({self.audio_queue.qsize()}/{self.MAX_QUEUE_SIZE}). "
                    f"Total wait time: {self._total_wait_time:.2f}s"
                )

        # Add frame to queue
        await self.audio_queue.put(pcm_data)
        self._total_chunks_pushed += 1

        queue_size = self.audio_queue.qsize()

        # Log queue size periodically
        if self._total_chunks_pushed % 50 == 0:  # Every 50 chunks (1 second)
            logger.info(
                f"🔍 CHECKPOINT 10: WebRTC track - Pushed {self._total_chunks_pushed} chunks, "
                f"queue size={queue_size}/{self.MAX_QUEUE_SIZE} (~{queue_size * 0.02:.2f}s buffered), "
                f"backpressure events={self._backpressure_count}"
            )

    async def flush(self):
        """Flush all buffered audio on interruption."""
        queue_size_before = self.audio_queue.qsize()
        buffer_size_before = len(self.buffer)

        logger.warning(
            f"🔍 CHECKPOINT 11: FLUSH STARTED - Queue: {queue_size_before} frames "
            f"(~{queue_size_before * 0.02:.2f}s), Buffer: {buffer_size_before}B, "
            f"Backpressure events: {self._backpressure_count}, Total wait time: {self._total_wait_time:.2f}s"
        )

        # Clear buffer
        self.buffer.clear()

        # Drain queue
        flushed_count = 0
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
                flushed_count += 1
            except:
                break

        logger.warning(
            f"🔍 CHECKPOINT 12: FLUSH COMPLETED - Flushed {flushed_count} frames "
            f"(~{flushed_count * 0.02:.2f}s of audio), Buffer cleared: {buffer_size_before}B"
        )
        logger.info(f"🧹 Flushed {flushed_count} queued frames and buffer for track {self.track_label}")

        # CRITICAL FIX: Wake up recv() by adding sentinel value
        # After flush, recv() might be stuck waiting on queue.get()
        # Adding None signals recv() to continue (it will buffer silence internally)
        await self.audio_queue.put(None)
        logger.info(f"🔇 Added sentinel to wake up recv() after flush")

        # Reset tracking counters after flush
        self._total_chunks_pushed = 0
        self._total_wait_time = 0.0
        self._backpressure_count = 0

    def _create_audio_frame(self, pcm_data: bytes) -> AudioFrame:
        """Convert raw PCM bytes to av.AudioFrame.

        CRITICAL: Creates frame with explicit format to ensure planes are always populated.
        This prevents IndexError in aiortc.rtp.compute_audio_level_dbov when accessing frame.planes[0].
        """
        # Defensive check: Ensure we have exactly the right amount of data
        if len(pcm_data) != self.bytes_per_frame:
            logger.error(
                f"❌ _create_audio_frame called with {len(pcm_data)} bytes, "
                f"expected {self.bytes_per_frame} bytes. Padding with silence."
            )
            # Pad or truncate to correct size
            if len(pcm_data) < self.bytes_per_frame:
                pcm_data = pcm_data + b'\x00' * (self.bytes_per_frame - len(pcm_data))
            else:
                pcm_data = pcm_data[:self.bytes_per_frame]

        # Create frame with explicit format and samples to ensure planes are created
        frame = AudioFrame(format='s16', layout='mono', samples=self.samples_per_frame)
        frame.sample_rate = self.sample_rate
        frame.pts = self.pts
        frame.time_base = fractions.Fraction(1, self.sample_rate)

        # Write PCM data to frame's first plane (channel)
        # This ensures plane[0] exists and is populated, even for silence
        for plane in frame.planes:
            plane.update(pcm_data)

        # Update pts for next frame
        self.pts += frame.samples

        return frame

    async def recv(self) -> AudioFrame:
        """
        Called by aiortc to get the next frame.
        Must return an av.AudioFrame.
        """
        # Log first few frames
        if not hasattr(self, '_frame_count'):
            self._frame_count = 0
            self._last_frame_time = None
            logger.info(f"🎬 TTSAudioTrack.recv() started for {self.track_label}")

        while True:
            # Check if we have enough data in buffer
            if len(self.buffer) >= self.bytes_per_frame:
                # CRITICAL: Extract frame data BEFORE any await to prevent race condition
                # If we await before extracting, flush() could clear the buffer mid-extraction
                frame_data = self.buffer[:self.bytes_per_frame]
                self.buffer = self.buffer[self.bytes_per_frame:]

                # CRITICAL FIX: Add pacing to yield frames at correct rate (20ms intervals)
                # Without this, all frames are sent immediately causing buffer issues
                current_time = time.time()
                if self._last_frame_time is not None:
                    # Calculate how long we should wait before yielding next frame
                    # Each frame = 20ms of audio (960 samples / 48000 Hz)
                    frame_duration = self.samples_per_frame / self.sample_rate  # 0.02 seconds
                    elapsed = current_time - self._last_frame_time
                    sleep_time = frame_duration - elapsed

                    if sleep_time > 0:
                        # Wait to maintain proper frame timing
                        await asyncio.sleep(sleep_time)

                self._last_frame_time = time.time()

                self._frame_count += 1
                if self._frame_count <= 3 or self._frame_count % 50 == 0:
                    logger.info(f"📹 Frame {self._frame_count}: {len(frame_data)} bytes, pts={self.pts}")

                return self._create_audio_frame(frame_data)

            # Need more data
            try:
                # Wait for data from queue
                new_data = await self.audio_queue.get()

                # Handle end of stream or silence
                if new_data is None:
                    # If buffer has leftover, pad with silence and return it
                    if len(self.buffer) > 0:
                        padding = self.bytes_per_frame - len(self.buffer)
                        self.buffer.extend(b'\x00' * padding)
                        logger.info(f"🔇 Padding final frame with {padding} bytes of silence")
                        continue
                    else:
                        # If queue explicitly sends None, we can yield silence to keep stream alive
                        # or just wait for more real data.
                        # For continuous voice, silence is safer than closing track.
                        self.buffer.extend(b'\x00' * self.bytes_per_frame)
                        logger.debug(f"🔇 Sending silence frame to keep track alive")
                        continue

                self.buffer.extend(new_data)

            except Exception as e:
                logger.error(f"❌ Error in TTSAudioTrack.recv: {e}")
                # Return silence on error to prevent crash
                return self._create_audio_frame(b'\x00' * self.bytes_per_frame)
