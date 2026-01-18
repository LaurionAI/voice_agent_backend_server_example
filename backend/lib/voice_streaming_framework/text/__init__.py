"""
Text processing utilities for voice streaming.

Provides tools for processing streaming text, particularly for
converting LLM token streams into sentence streams for TTS.
"""

from .sentence_aggregator import SentenceAggregator, AggregatorConfig

__all__ = [
    "SentenceAggregator",
    "AggregatorConfig",
]
