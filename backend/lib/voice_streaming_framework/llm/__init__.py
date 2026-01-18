"""
LLM (Large Language Model) providers for voice streaming.

Available providers:
- OpenAICompatibleLLM: Works with OpenAI, ZhipuAI, DeepSeek, Groq, etc.
- LangGraphAdapter: Wraps any LangGraph agent for voice streaming
"""

from .base import BaseLLMProvider, LLMConfig
from .openai_compatible import OpenAICompatibleLLM
from .langgraph_adapter import LangGraphAdapter

__all__ = [
    # Base
    "BaseLLMProvider",
    "LLMConfig",
    # Providers
    "OpenAICompatibleLLM",
    "LangGraphAdapter",
]
