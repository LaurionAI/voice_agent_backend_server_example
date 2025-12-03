"""Audio Chunk Queue - Buffering and Backpressure Management

Inspired by LiveKit's AudioByteStream and queue management patterns:
- Fixed-size queue with configurable capacity
- Blocking behavior when queue is full (backpressure)
- Parallel processing support per session
- Queue health monitoring and metrics

References:
- LiveKit AudioSource: 1000ms default buffer, blocking capture_frame
- LiveKit max queue: 100 frames in output queue
- LiveKit AudioByteStream: Fixed-size frame chunking
"""
import asyncio
import time
import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from collections import deque


logger = logging.getLogger("audio.chunk_queue")


@dataclass
class QueueMetrics:
    """Metrics for queue health monitoring."""
    total_enqueued: int = 0
    total_dequeued: int = 0
    total_dropped: int = 0
    backpressure_events: int = 0
    current_size: int = 0
    max_size_reached: int = 0
    avg_latency_ms: float = 0.0


class AudioChunkQueue:
    """
    Fixed-size audio chunk queue with backpressure management.

    Inspired by LiveKit's queue architecture:
    - Default capacity: 100 frames
    - Blocking behavior when full
    - Per-session queue isolation
    - Health monitoring and metrics

    Args:
        max_size: Maximum queue capacity (frames). Default 100.
        max_wait_time: Maximum time to wait when queue is full (seconds). Default 2.0.
        enable_metrics: Track detailed queue metrics. Default True.
    """

    def __init__(
        self,
        max_size: int = 100,
        max_wait_time: float = 2.0,
        enable_metrics: bool = True
    ):
        self.max_size = max_size
        self.max_wait_time = max_wait_time
        self.enable_metrics = enable_metrics

        # Queue storage: chunk_index -> (chunk_data, enqueue_time)
        self.queue: deque = deque(maxlen=max_size)
        self.queue_lock = asyncio.Lock()

        # Metrics
        self.metrics = QueueMetrics()

        # Backpressure signaling
        self.space_available = asyncio.Event()
        self.space_available.set()  # Initially has space

    async def put(
        self,
        chunk_index: int,
        chunk_data: bytes,
        timeout: Optional[float] = None
    ) -> bool:
        """
        Add chunk to queue with backpressure handling.

        Blocks if queue is full, implementing backpressure

        Args:
            chunk_index: Sequential chunk number
            chunk_data: Audio chunk bytes
            timeout: Override max wait time (optional)

        Returns:
            True if enqueued, False if dropped due to timeout
        """
        wait_time = timeout if timeout is not None else self.max_wait_time
        enqueue_time = time.time()

        async with self.queue_lock:
            # Check if queue has space
            if len(self.queue) >= self.max_size:
                # Queue full - apply backpressure
                self.space_available.clear()

                if self.enable_metrics:
                    self.metrics.backpressure_events += 1

                logger.warning(
                    f"🔴 Queue FULL ({len(self.queue)}/{self.max_size}) | "
                    f"Chunk #{chunk_index} waiting for space | "
                    f"Backpressure event #{self.metrics.backpressure_events}"
                )

        # Wait for space (outside lock to allow dequeue)
        try:
            await asyncio.wait_for(
                self.space_available.wait(),
                timeout=wait_time
            )
        except asyncio.TimeoutError:
            # Timeout - drop chunk
            logger.error(
                f"❌ Queue timeout ({wait_time:.1f}s) | "
                f"Dropping chunk #{chunk_index} | "
                f"Queue size: {len(self.queue)}/{self.max_size}"
            )

            if self.enable_metrics:
                self.metrics.total_dropped += 1

            return False

        # Space available - enqueue chunk
        async with self.queue_lock:
            self.queue.append((chunk_index, chunk_data, enqueue_time))

            if self.enable_metrics:
                self.metrics.total_enqueued += 1
                self.metrics.current_size = len(self.queue)
                self.metrics.max_size_reached = max(
                    self.metrics.max_size_reached,
                    len(self.queue)
                )

            logger.debug(
                f"✅ Enqueued chunk #{chunk_index} | "
                f"Queue: {len(self.queue)}/{self.max_size} | "
                f"Wait: {(time.time() - enqueue_time)*1000:.0f}ms"
            )

            return True

    async def get(self) -> Optional[Tuple[int, bytes, float]]:
        """
        Get next chunk from queue.

        Returns:
            Tuple of (chunk_index, chunk_data, latency_ms) or None if empty
        """
        async with self.queue_lock:
            if not self.queue:
                return None

            chunk_index, chunk_data, enqueue_time = self.queue.popleft()
            dequeue_time = time.time()
            latency_ms = (dequeue_time - enqueue_time) * 1000

            if self.enable_metrics:
                self.metrics.total_dequeued += 1
                self.metrics.current_size = len(self.queue)

                # Update average latency (exponential moving average)
                alpha = 0.3  # Smoothing factor
                self.metrics.avg_latency_ms = (
                    alpha * latency_ms +
                    (1 - alpha) * self.metrics.avg_latency_ms
                )

            # Signal space available if queue was full
            if len(self.queue) < self.max_size:
                self.space_available.set()

            logger.debug(
                f"📤 Dequeued chunk #{chunk_index} | "
                f"Latency: {latency_ms:.1f}ms | "
                f"Queue: {len(self.queue)}/{self.max_size}"
            )

            return chunk_index, chunk_data, latency_ms

    def qsize(self) -> int:
        """Get current queue size (thread-safe)."""
        return len(self.queue)

    def is_full(self) -> bool:
        """Check if queue is at capacity."""
        return len(self.queue) >= self.max_size

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return len(self.queue) == 0

    async def clear(self):
        """Clear all queued chunks."""
        async with self.queue_lock:
            dropped = len(self.queue)
            self.queue.clear()
            self.space_available.set()

            if self.enable_metrics:
                self.metrics.total_dropped += dropped

            logger.info(f"🧹 Cleared queue | Dropped {dropped} chunks")

    def get_metrics(self) -> QueueMetrics:
        """Get queue metrics snapshot."""
        return QueueMetrics(
            total_enqueued=self.metrics.total_enqueued,
            total_dequeued=self.metrics.total_dequeued,
            total_dropped=self.metrics.total_dropped,
            backpressure_events=self.metrics.backpressure_events,
            current_size=len(self.queue),
            max_size_reached=self.metrics.max_size_reached,
            avg_latency_ms=self.metrics.avg_latency_ms
        )

    def get_health_status(self) -> Dict[str, any]:
        """
        Get queue health status for monitoring.

        Returns dict with health indicators:
        - status: "healthy" | "warning" | "critical"
        - utilization: Queue fill percentage
        - backpressure: Number of backpressure events
        - drop_rate: Percentage of dropped chunks
        - avg_latency_ms: Average chunk latency
        """
        metrics = self.get_metrics()
        utilization = (metrics.current_size / self.max_size) * 100

        # Calculate drop rate
        total_attempts = metrics.total_enqueued + metrics.total_dropped
        drop_rate = (
            (metrics.total_dropped / total_attempts * 100)
            if total_attempts > 0 else 0
        )

        # Determine health status
        if utilization > 90 or drop_rate > 10:
            status = "critical"
        elif utilization > 70 or drop_rate > 5:
            status = "warning"
        else:
            status = "healthy"

        return {
            "status": status,
            "utilization_percent": round(utilization, 1),
            "queue_size": f"{metrics.current_size}/{self.max_size}",
            "backpressure_events": metrics.backpressure_events,
            "drop_rate_percent": round(drop_rate, 1),
            "avg_latency_ms": round(metrics.avg_latency_ms, 1),
            "total_enqueued": metrics.total_enqueued,
            "total_dequeued": metrics.total_dequeued,
            "total_dropped": metrics.total_dropped,
        }


class AudioChunkQueueManager:
    """
    Manages per-session audio chunk queues.

    Provides isolated queues per session for independent buffering.
    """

    def __init__(
        self,
        default_queue_size: int = 100,
        enable_metrics: bool = True
    ):
        self.default_queue_size = default_queue_size
        self.enable_metrics = enable_metrics

        # Per-session queues
        self.queues: Dict[str, AudioChunkQueue] = {}
        self.lock = asyncio.Lock()

    async def get_queue(self, session_id: str) -> AudioChunkQueue:
        """Get or create queue for session."""
        async with self.lock:
            if session_id not in self.queues:
                self.queues[session_id] = AudioChunkQueue(
                    max_size=self.default_queue_size,
                    enable_metrics=self.enable_metrics
                )
                logger.info(
                    f"📦 Created queue for session {session_id[:8]}... | "
                    f"Max size: {self.default_queue_size}"
                )

            return self.queues[session_id]

    async def remove_queue(self, session_id: str):
        """Remove and clean up queue for session."""
        async with self.lock:
            if session_id in self.queues:
                queue = self.queues[session_id]
                await queue.clear()
                del self.queues[session_id]

                logger.info(f"🗑️ Removed queue for session {session_id[:8]}...")

    def get_all_health_statuses(self) -> Dict[str, Dict]:
        """Get health status for all active queues."""
        return {
            session_id: queue.get_health_status()
            for session_id, queue in self.queues.items()
        }


# Global queue manager instance
_queue_manager: Optional[AudioChunkQueueManager] = None


def get_queue_manager() -> AudioChunkQueueManager:
    """Get global queue manager instance."""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = AudioChunkQueueManager()
    return _queue_manager
