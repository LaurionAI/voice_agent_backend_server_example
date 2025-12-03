"""Audio Chunk Tracker - Delivery Acknowledgment and Missing Chunk Detection

Tracks sent vs acknowledged chunks to detect packet loss and delivery issues.
Provides visibility into chunk delivery reliability.

Architecture:
- Backend tracks chunks sent to frontend
- Frontend sends ACK messages for received chunks
- System detects missing/unacknowledged chunks
- Metrics for delivery rate and reliability
"""
import asyncio
import time
import logging
from typing import Dict, Set, Optional, List
from dataclasses import dataclass, field
from collections import defaultdict


logger = logging.getLogger("audio.chunk_tracker")


@dataclass
class ChunkDeliveryMetrics:
    """Metrics for chunk delivery monitoring."""
    total_sent: int = 0
    total_acknowledged: int = 0
    total_missing: int = 0
    delivery_rate_percent: float = 100.0
    avg_ack_latency_ms: float = 0.0
    max_ack_latency_ms: float = 0.0
    oldest_unacked_age_ms: float = 0.0


@dataclass
class ChunkInfo:
    """Information about a sent chunk."""
    chunk_index: int
    sent_time: float
    size_bytes: int
    acked: bool = False
    ack_time: Optional[float] = None

    def get_age_ms(self) -> float:
        """Get age of chunk in milliseconds."""
        return (time.time() - self.sent_time) * 1000

    def get_ack_latency_ms(self) -> Optional[float]:
        """Get acknowledgment latency in milliseconds."""
        if self.ack_time is None:
            return None
        return (self.ack_time - self.sent_time) * 1000


class ChunkTracker:
    """
    Tracks audio chunk delivery and acknowledgments for a single session.

    Monitors:
    - Chunks sent to frontend
    - Chunks acknowledged by frontend
    - Missing/unacknowledged chunks
    - Delivery latency and reliability metrics

    Args:
        session_id: Session identifier
        ack_timeout: Time before considering chunk missing (seconds). Default 5.0.
        max_tracked_chunks: Maximum chunks to track (prevent memory leak). Default 1000.
    """

    def __init__(
        self,
        session_id: str,
        ack_timeout: float = 5.0,
        max_tracked_chunks: int = 1000
    ):
        self.session_id = session_id
        self.ack_timeout = ack_timeout
        self.max_tracked_chunks = max_tracked_chunks

        # Chunk tracking
        self.sent_chunks: Dict[int, ChunkInfo] = {}
        self.lock = asyncio.Lock()

        # Metrics
        self.total_sent = 0
        self.total_acked = 0
        self.total_missing = 0

        # Latency tracking
        self.ack_latencies: List[float] = []
        self.max_ack_latency = 0.0

    async def mark_sent(
        self,
        chunk_index: int,
        chunk_size: int
    ):
        """
        Mark chunk as sent to frontend.

        Args:
            chunk_index: Sequential chunk number
            chunk_size: Size of chunk in bytes
        """
        async with self.lock:
            # Enforce max tracked chunks (sliding window)
            if len(self.sent_chunks) >= self.max_tracked_chunks:
                # Remove oldest unacked chunk
                oldest_index = min(
                    (idx for idx, info in self.sent_chunks.items() if not info.acked),
                    default=None
                )
                if oldest_index is not None:
                    del self.sent_chunks[oldest_index]
                    self.total_missing += 1
                    logger.warning(
                        f"⚠️ Evicted old unacked chunk #{oldest_index} | "
                        f"session={self.session_id[:8]}..."
                    )

            self.sent_chunks[chunk_index] = ChunkInfo(
                chunk_index=chunk_index,
                sent_time=time.time(),
                size_bytes=chunk_size
            )
            self.total_sent += 1

            logger.debug(
                f"📤 Sent chunk #{chunk_index} | "
                f"size={chunk_size}B | "
                f"session={self.session_id[:8]}..."
            )

    async def mark_acknowledged(
        self,
        chunk_index: int
    ) -> bool:
        """
        Mark chunk as acknowledged by frontend.

        Args:
            chunk_index: Sequential chunk number

        Returns:
            True if chunk was tracked and acked, False if unknown chunk
        """
        async with self.lock:
            if chunk_index not in self.sent_chunks:
                logger.warning(
                    f"⚠️ ACK for unknown chunk #{chunk_index} | "
                    f"session={self.session_id[:8]}..."
                )
                return False

            chunk_info = self.sent_chunks[chunk_index]

            if chunk_info.acked:
                logger.debug(
                    f"🔄 Duplicate ACK for chunk #{chunk_index} | "
                    f"session={self.session_id[:8]}..."
                )
                return True

            # Mark as acknowledged
            chunk_info.acked = True
            chunk_info.ack_time = time.time()
            self.total_acked += 1

            # Track latency
            latency_ms = chunk_info.get_ack_latency_ms()
            if latency_ms is not None:
                self.ack_latencies.append(latency_ms)
                self.max_ack_latency = max(self.max_ack_latency, latency_ms)

                # Keep only recent latencies (last 100)
                if len(self.ack_latencies) > 100:
                    self.ack_latencies.pop(0)

            logger.debug(
                f"✅ ACK chunk #{chunk_index} | "
                f"latency={latency_ms:.1f}ms | "
                f"session={self.session_id[:8]}..."
            )

            return True

    def get_missing_chunks(self) -> List[int]:
        """
        Get list of chunk indices that are missing (sent but not acked).

        Only includes chunks older than ack_timeout.

        Returns:
            List of missing chunk indices
        """
        current_time = time.time()
        missing = []

        for chunk_index, chunk_info in self.sent_chunks.items():
            if not chunk_info.acked:
                age_seconds = current_time - chunk_info.sent_time
                if age_seconds > self.ack_timeout:
                    missing.append(chunk_index)

        return sorted(missing)

    def get_unacked_chunks(self) -> List[int]:
        """
        Get list of all unacknowledged chunk indices (regardless of age).

        Returns:
            List of unacked chunk indices
        """
        return sorted([
            idx for idx, info in self.sent_chunks.items()
            if not info.acked
        ])

    def get_delivery_rate(self) -> float:
        """
        Calculate chunk delivery rate as percentage.

        Returns:
            Delivery rate (0-100%)
        """
        if self.total_sent == 0:
            return 100.0

        return (self.total_acked / self.total_sent) * 100

    def get_avg_ack_latency(self) -> float:
        """
        Get average acknowledgment latency in milliseconds.

        Returns:
            Average latency or 0.0 if no data
        """
        if not self.ack_latencies:
            return 0.0

        return sum(self.ack_latencies) / len(self.ack_latencies)

    def get_oldest_unacked_age(self) -> float:
        """
        Get age of oldest unacknowledged chunk in milliseconds.

        Returns:
            Age in milliseconds or 0.0 if all acked
        """
        unacked = [
            info for info in self.sent_chunks.values()
            if not info.acked
        ]

        if not unacked:
            return 0.0

        oldest = min(unacked, key=lambda x: x.sent_time)
        return oldest.get_age_ms()

    def get_metrics(self) -> ChunkDeliveryMetrics:
        """Get chunk delivery metrics snapshot."""
        missing = self.get_missing_chunks()

        return ChunkDeliveryMetrics(
            total_sent=self.total_sent,
            total_acknowledged=self.total_acked,
            total_missing=len(missing),
            delivery_rate_percent=round(self.get_delivery_rate(), 2),
            avg_ack_latency_ms=round(self.get_avg_ack_latency(), 2),
            max_ack_latency_ms=round(self.max_ack_latency, 2),
            oldest_unacked_age_ms=round(self.get_oldest_unacked_age(), 2)
        )

    async def cleanup_old_chunks(self):
        """Remove old acknowledged chunks to prevent memory growth."""
        async with self.lock:
            # Remove chunks acked > 60 seconds ago
            cutoff_time = time.time() - 60

            to_remove = [
                idx for idx, info in self.sent_chunks.items()
                if info.acked and info.ack_time is not None and info.ack_time < cutoff_time
            ]

            for idx in to_remove:
                del self.sent_chunks[idx]

            if to_remove:
                logger.debug(
                    f"🧹 Cleaned up {len(to_remove)} old chunks | "
                    f"session={self.session_id[:8]}..."
                )


class ChunkTrackerManager:
    """
    Manages chunk trackers for all active sessions.

    Provides:
    - Per-session chunk tracking
    - Centralized metrics collection
    - Automatic cleanup on session end
    """

    def __init__(
        self,
        default_ack_timeout: float = 5.0,
        enable_metrics: bool = True
    ):
        self.default_ack_timeout = default_ack_timeout
        self.enable_metrics = enable_metrics

        # Per-session trackers
        self.trackers: Dict[str, ChunkTracker] = {}
        self.lock = asyncio.Lock()

    async def get_tracker(self, session_id: str) -> ChunkTracker:
        """Get or create chunk tracker for session."""
        async with self.lock:
            if session_id not in self.trackers:
                self.trackers[session_id] = ChunkTracker(
                    session_id=session_id,
                    ack_timeout=self.default_ack_timeout
                )
                logger.info(
                    f"📊 Created chunk tracker for session {session_id[:8]}..."
                )

            return self.trackers[session_id]

    async def remove_tracker(self, session_id: str):
        """Remove tracker for session."""
        async with self.lock:
            if session_id in self.trackers:
                tracker = self.trackers[session_id]
                metrics = tracker.get_metrics()

                logger.info(
                    f"📊 Final metrics for session {session_id[:8]}... | "
                    f"Sent: {metrics.total_sent} | "
                    f"Acked: {metrics.total_acknowledged} | "
                    f"Missing: {metrics.total_missing} | "
                    f"Delivery rate: {metrics.delivery_rate_percent}%"
                )

                del self.trackers[session_id]

    def get_all_metrics(self) -> Dict[str, ChunkDeliveryMetrics]:
        """Get metrics for all active sessions."""
        return {
            session_id: tracker.get_metrics()
            for session_id, tracker in self.trackers.items()
        }

    async def report_missing_chunks(self):
        """Log report of missing chunks across all sessions."""
        for session_id, tracker in self.trackers.items():
            missing = tracker.get_missing_chunks()
            if missing:
                logger.warning(
                    f"📉 Missing chunks for session {session_id[:8]}... | "
                    f"Count: {len(missing)} | "
                    f"Indices: {missing[:10]}{'...' if len(missing) > 10 else ''}"
                )


# Global tracker manager instance
_tracker_manager: Optional[ChunkTrackerManager] = None


def get_tracker_manager() -> ChunkTrackerManager:
    """Get global chunk tracker manager instance."""
    global _tracker_manager
    if _tracker_manager is None:
        _tracker_manager = ChunkTrackerManager()
    return _tracker_manager
