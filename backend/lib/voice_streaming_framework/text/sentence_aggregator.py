"""
Sentence aggregator for streaming LLM to TTS.

Buffers streaming LLM tokens and yields complete sentences for TTS synthesis.
This enables low-latency voice responses by starting TTS before the LLM finishes.
"""

import re
import logging
from dataclasses import dataclass
from typing import AsyncIterator, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AggregatorConfig:
    """Configuration for sentence aggregation."""
    # Minimum characters before yielding a sentence
    min_chars: int = 15

    # Maximum characters to buffer before force-yielding
    max_wait_chars: int = 200

    # Sentence-ending punctuation (multi-language)
    sentence_endings: str = r'[.!?。！？]'

    # Secondary break points (commas, etc.) for long sentences
    soft_breaks: str = r'[,;，；：:]'

    # Whether to strip whitespace from yielded sentences
    strip_whitespace: bool = True


class SentenceAggregator:
    """
    Aggregates streaming tokens into complete sentences for TTS.

    This is essential for low-latency voice responses. Instead of waiting
    for the entire LLM response, we yield sentences as soon as they're complete,
    allowing TTS to start speaking immediately.

    Flow:
        LLM tokens → SentenceAggregator → TTS
        "I"  "think"  "."  "Therefore"  "I"  "am"  "."
                ↓                    ↓
          "I think."          "Therefore I am."
                ↓                    ↓
            TTS audio            TTS audio

    Example:
        aggregator = SentenceAggregator()

        async for sentence in aggregator.process_stream(llm_token_stream):
            async for audio in tts.synthesize_stream(sentence):
                yield audio
    """

    # Pre-compiled patterns for common edge cases
    ABBREVIATIONS = re.compile(
        r'\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|e\.g|i\.e|Inc|Ltd|Corp)\.$',
        re.IGNORECASE
    )
    DECIMAL_NUMBER = re.compile(r'\d\.$')
    URL_PATTERN = re.compile(r'https?://\S+$')

    def __init__(self, config: Optional[AggregatorConfig] = None):
        """
        Initialize sentence aggregator.

        Args:
            config: Optional aggregator configuration
        """
        self.config = config or AggregatorConfig()
        self.buffer = ""

        # Compile regex patterns
        self._sentence_endings = re.compile(
            self.config.sentence_endings + r'\s*'
        )
        self._soft_breaks = re.compile(
            self.config.soft_breaks + r'\s*'
        )

    def reset(self) -> None:
        """Reset the buffer for a new stream."""
        self.buffer = ""

    def _is_false_ending(self, text: str, match_end: int) -> bool:
        """
        Check if a sentence ending is actually a false positive.

        Handles:
        - Abbreviations: Mr., Dr., etc.
        - Decimal numbers: 3.14, $29.95
        - URLs: https://example.com

        Args:
            text: Text up to and including the potential ending
            match_end: Position of the match end

        Returns:
            True if this is a false ending that should be ignored
        """
        text_before = text[:match_end].rstrip()

        # Check for abbreviations
        if self.ABBREVIATIONS.search(text_before):
            return True

        # Check for decimal numbers
        if self.DECIMAL_NUMBER.search(text_before):
            return True

        # Check for URLs (don't break on dots in URLs)
        if self.URL_PATTERN.search(text_before):
            return True

        return False

    def _find_sentence_boundary(self) -> Optional[int]:
        """
        Find the position of a sentence boundary in the buffer.

        Returns:
            Position after the sentence boundary, or None if not found
        """
        for match in self._sentence_endings.finditer(self.buffer):
            # Skip false positives
            if self._is_false_ending(self.buffer, match.end()):
                continue

            # Check minimum length requirement
            if match.end() >= self.config.min_chars:
                return match.end()

        return None

    def _find_soft_boundary(self) -> Optional[int]:
        """
        Find a soft boundary (comma, etc.) for force-breaking long sentences.

        Only used when buffer exceeds max_wait_chars.

        Returns:
            Position after the soft boundary, or None if not found
        """
        for match in self._soft_breaks.finditer(self.buffer):
            if match.end() >= self.config.min_chars:
                return match.end()

        return None

    async def process_stream(
        self,
        token_stream: AsyncIterator[str]
    ) -> AsyncIterator[str]:
        """
        Process a stream of tokens and yield complete sentences.

        Args:
            token_stream: Async iterator of LLM tokens

        Yields:
            Complete sentences ready for TTS
        """
        self.reset()

        async for token in token_stream:
            self.buffer += token

            # Try to yield complete sentences
            while True:
                # Look for sentence boundary
                boundary = self._find_sentence_boundary()

                if boundary:
                    sentence = self.buffer[:boundary]
                    self.buffer = self.buffer[boundary:]

                    if self.config.strip_whitespace:
                        sentence = sentence.strip()

                    if sentence:
                        logger.debug(f"Yielding sentence ({len(sentence)} chars): {sentence[:50]}...")
                        yield sentence
                    continue

                # Check if we need to force-break a long sentence
                if len(self.buffer) > self.config.max_wait_chars:
                    soft_boundary = self._find_soft_boundary()

                    if soft_boundary:
                        chunk = self.buffer[:soft_boundary]
                        self.buffer = self.buffer[soft_boundary:]

                        if self.config.strip_whitespace:
                            chunk = chunk.strip()

                        if chunk:
                            logger.debug(f"Force-yielding chunk ({len(chunk)} chars): {chunk[:50]}...")
                            yield chunk
                        continue

                # No boundary found, wait for more tokens
                break

        # Yield any remaining buffer content
        if self.buffer:
            remaining = self.buffer.strip() if self.config.strip_whitespace else self.buffer
            if remaining:
                logger.debug(f"Yielding final chunk ({len(remaining)} chars): {remaining[:50]}...")
                yield remaining
            self.buffer = ""

    def add_token(self, token: str) -> List[str]:
        """
        Add a single token and return any complete sentences.

        This is a synchronous alternative to process_stream() for
        callback-based streaming APIs.

        Args:
            token: Token to add

        Returns:
            List of complete sentences (may be empty)
        """
        self.buffer += token
        sentences = []

        while True:
            boundary = self._find_sentence_boundary()

            if boundary:
                sentence = self.buffer[:boundary]
                self.buffer = self.buffer[boundary:]

                if self.config.strip_whitespace:
                    sentence = sentence.strip()

                if sentence:
                    sentences.append(sentence)
                continue

            if len(self.buffer) > self.config.max_wait_chars:
                soft_boundary = self._find_soft_boundary()

                if soft_boundary:
                    chunk = self.buffer[:soft_boundary]
                    self.buffer = self.buffer[soft_boundary:]

                    if self.config.strip_whitespace:
                        chunk = chunk.strip()

                    if chunk:
                        sentences.append(chunk)
                    continue

            break

        return sentences

    def flush(self) -> Optional[str]:
        """
        Flush and return any remaining buffer content.

        Call this when the stream ends to get the final sentence.

        Returns:
            Remaining content or None if empty
        """
        if self.buffer:
            remaining = self.buffer.strip() if self.config.strip_whitespace else self.buffer
            self.buffer = ""
            return remaining if remaining else None
        return None
