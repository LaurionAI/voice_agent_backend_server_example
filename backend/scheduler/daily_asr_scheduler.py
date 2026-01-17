"""
Daily ASR Scheduler.

Sends an audio sample to the HuggingFace ASR API every day.
"""

import asyncio
import logging
import os
from datetime import datetime, time
from pathlib import Path

from lib.voice_streaming_framework.asr.hf_space import HFSpaceASR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DailyASRScheduler:
    """Scheduler that sends audio to HF ASR API daily."""

    def __init__(
        self,
        audio_path: str,
        run_time: time = time(hour=9, minute=0),
        space_name: str = "hz6666/SenseVoiceSmall",
        hf_token: str | None = None
    ):
        """
        Initialize the daily ASR scheduler.

        Args:
            audio_path: Path to the audio file to transcribe
            run_time: Time of day to run (default: 9:00 AM)
            space_name: HuggingFace Space name
            hf_token: Optional HuggingFace token
        """
        self.audio_path = Path(audio_path)
        self.run_time = run_time
        self.asr = HFSpaceASR(space_name=space_name, hf_token=hf_token)
        self._running = False

        if not self.audio_path.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

    async def _transcribe(self) -> str:
        """Run transcription on the audio sample."""
        logger.info(f"Starting transcription of: {self.audio_path}")
        try:
            result = await self.asr.transcribe_audio(str(self.audio_path))
            logger.info(f"Transcription result: {result}")
            return result
        except Exception as e:
            logger.error(f"Transcription failed: {e}")
            raise

    def _seconds_until_next_run(self) -> float:
        """Calculate seconds until next scheduled run."""
        now = datetime.now()
        target = datetime.combine(now.date(), self.run_time)

        if now.time() >= self.run_time:
            # Already passed today, schedule for tomorrow
            target = datetime.combine(
                now.date().replace(day=now.day + 1),
                self.run_time
            )

        delta = target - now
        return delta.total_seconds()

    async def run_once(self) -> str:
        """Run the transcription once immediately."""
        return await self._transcribe()

    async def start(self):
        """Start the daily scheduler."""
        self._running = True
        logger.info(
            f"Scheduler started. Will run daily at {self.run_time.strftime('%H:%M')}"
        )

        while self._running:
            wait_seconds = self._seconds_until_next_run()
            logger.info(
                f"Next run in {wait_seconds / 3600:.1f} hours "
                f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
            )

            await asyncio.sleep(wait_seconds)

            if self._running:
                try:
                    await self._transcribe()
                except Exception as e:
                    logger.error(f"Scheduled transcription failed: {e}")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped")


async def main():
    """Example usage."""
    import argparse

    parser = argparse.ArgumentParser(description="Daily ASR Scheduler")
    parser.add_argument("audio_path", help="Path to audio file")
    parser.add_argument(
        "--hour", type=int, default=9, help="Hour to run (0-23)"
    )
    parser.add_argument(
        "--minute", type=int, default=0, help="Minute to run (0-59)"
    )
    parser.add_argument(
        "--run-now", action="store_true", help="Run once immediately and exit"
    )
    args = parser.parse_args()

    scheduler = DailyASRScheduler(
        audio_path=args.audio_path,
        run_time=time(hour=args.hour, minute=args.minute)
    )

    if args.run_now:
        result = await scheduler.run_once()
        print(f"Transcription: {result}")
    else:
        try:
            await scheduler.start()
        except KeyboardInterrupt:
            scheduler.stop()


if __name__ == "__main__":
    asyncio.run(main())
