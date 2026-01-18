"""
Audio format converter using FFmpeg.

Handles conversion between audio formats (MP3 → PCM) for WebRTC streaming.
TTS providers often output MP3, but WebRTC requires PCM for Opus encoding.
"""

import asyncio
import logging
import shutil
import subprocess
from dataclasses import dataclass
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


@dataclass
class ConverterConfig:
    """Configuration for audio converter."""
    # Output format settings
    output_sample_rate: int = 48000  # Opus standard
    output_channels: int = 1  # Mono
    output_format: str = "s16le"  # Signed 16-bit little-endian PCM

    # FFmpeg settings
    ffmpeg_path: Optional[str] = None  # Auto-detect if None
    buffer_size: int = 4096  # Read buffer size


class AudioConverter:
    """
    Converts audio formats using FFmpeg subprocess.

    Primary use case: Converting TTS output (MP3) to PCM for WebRTC.

    Example:
        converter = AudioConverter()

        # Convert MP3 stream to PCM
        async for pcm_chunk in converter.mp3_to_pcm_stream(mp3_stream):
            await webrtc.send_audio(session_id, pcm_chunk)
    """

    def __init__(self, config: Optional[ConverterConfig] = None):
        """
        Initialize audio converter.

        Args:
            config: Optional converter configuration
        """
        self.config = config or ConverterConfig()
        self._ffmpeg_path = self._find_ffmpeg()

    def _find_ffmpeg(self) -> Optional[str]:
        """Find FFmpeg executable path."""
        if self.config.ffmpeg_path:
            return self.config.ffmpeg_path

        path = shutil.which("ffmpeg")
        if path:
            logger.info(f"Found FFmpeg at: {path}")
        else:
            logger.warning("FFmpeg not found in PATH. Audio conversion will fail.")
        return path

    def is_available(self) -> bool:
        """Check if FFmpeg is available."""
        return self._ffmpeg_path is not None

    def get_version(self) -> Optional[str]:
        """Get FFmpeg version string."""
        if not self._ffmpeg_path:
            return None

        try:
            result = subprocess.run(
                [self._ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.stdout:
                return result.stdout.split('\n')[0]
        except Exception as e:
            logger.error(f"Failed to get FFmpeg version: {e}")
        return None

    async def mp3_to_pcm_stream(
        self,
        mp3_stream: AsyncIterator[bytes],
        chunk_callback: Optional[callable] = None,
    ) -> AsyncIterator[bytes]:
        """
        Convert streaming MP3 to PCM using FFmpeg subprocess.

        Args:
            mp3_stream: Async iterator of MP3 chunks
            chunk_callback: Optional callback called for each PCM chunk

        Yields:
            PCM audio chunks (signed 16-bit LE, mono, 48kHz)
        """
        if not self._ffmpeg_path:
            raise RuntimeError("FFmpeg not available. Install FFmpeg to enable audio conversion.")

        # FFmpeg command for MP3 → PCM conversion
        cmd = [
            self._ffmpeg_path,
            "-i", "pipe:0",  # Input from stdin
            "-f", self.config.output_format,  # Output format
            "-ar", str(self.config.output_sample_rate),  # Sample rate
            "-ac", str(self.config.output_channels),  # Channels
            "-loglevel", "error",  # Suppress verbose output
            "pipe:1"  # Output to stdout
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        logger.debug(f"Started FFmpeg process for MP3→PCM conversion (PID: {process.pid})")

        async def feed_input():
            """Feed MP3 data to FFmpeg stdin."""
            try:
                async for mp3_chunk in mp3_stream:
                    if process.stdin:
                        process.stdin.write(mp3_chunk)
                        await process.stdin.drain()
                if process.stdin:
                    process.stdin.close()
                    await process.stdin.wait_closed()
            except Exception as e:
                logger.error(f"Error feeding MP3 to FFmpeg: {e}")
                if process.stdin:
                    process.stdin.close()

        # Start feeding input in background
        input_task = asyncio.create_task(feed_input())

        try:
            # Read PCM output
            while True:
                pcm_chunk = await process.stdout.read(self.config.buffer_size)
                if not pcm_chunk:
                    break

                if chunk_callback:
                    chunk_callback(pcm_chunk)

                yield pcm_chunk

        except Exception as e:
            logger.error(f"Error reading PCM from FFmpeg: {e}")
            raise

        finally:
            # Clean up
            input_task.cancel()
            try:
                await input_task
            except asyncio.CancelledError:
                pass

            if process.returncode is None:
                process.kill()
                await process.wait()

            logger.debug(f"FFmpeg process completed (return code: {process.returncode})")

    async def convert_mp3_to_pcm(self, mp3_data: bytes) -> bytes:
        """
        Convert complete MP3 data to PCM.

        Args:
            mp3_data: Complete MP3 audio data

        Returns:
            PCM audio data
        """
        if not self._ffmpeg_path:
            raise RuntimeError("FFmpeg not available")

        cmd = [
            self._ffmpeg_path,
            "-i", "pipe:0",
            "-f", self.config.output_format,
            "-ar", str(self.config.output_sample_rate),
            "-ac", str(self.config.output_channels),
            "-loglevel", "error",
            "pipe:1"
        ]

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate(mp3_data)

        if process.returncode != 0:
            error_msg = stderr.decode() if stderr else "Unknown error"
            raise RuntimeError(f"FFmpeg conversion failed: {error_msg}")

        return stdout


# Global converter instance
_converter: Optional[AudioConverter] = None


def get_converter(config: Optional[ConverterConfig] = None) -> AudioConverter:
    """
    Get or create global audio converter instance.

    Args:
        config: Optional converter configuration

    Returns:
        AudioConverter instance
    """
    global _converter
    if _converter is None:
        _converter = AudioConverter(config)
    return _converter
