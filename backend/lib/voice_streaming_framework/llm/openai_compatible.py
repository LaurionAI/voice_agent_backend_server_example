"""
OpenAI-compatible LLM provider.

Works with any OpenAI-compatible API:
- OpenAI (GPT-4, GPT-3.5)
- ZhipuAI (GLM-4)
- DeepSeek
- Groq
- Together AI
- Local LLMs with OpenAI-compatible endpoints (Ollama, vLLM, etc.)
"""

import logging
from typing import AsyncIterator, Optional

from .base import BaseLLMProvider, LLMConfig

logger = logging.getLogger(__name__)


class OpenAICompatibleLLM(BaseLLMProvider):
    """
    LLM provider for OpenAI-compatible APIs.

    Supports streaming and non-streaming generation with automatic
    conversation history management.

    Example:
        # OpenAI
        llm = OpenAICompatibleLLM(
            config=LLMConfig(model="gpt-4", system_prompt="You are helpful."),
            api_key="sk-..."
        )

        # ZhipuAI
        llm = OpenAICompatibleLLM(
            config=LLMConfig(model="glm-4", system_prompt="You are helpful."),
            api_key="...",
            base_url="https://open.bigmodel.cn/api/paas/v4/"
        )

        # Local Ollama
        llm = OpenAICompatibleLLM(
            config=LLMConfig(model="llama2"),
            base_url="http://localhost:11434/v1"
        )
    """

    def __init__(
        self,
        config: LLMConfig,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize OpenAI-compatible LLM provider.

        Args:
            config: LLM configuration
            api_key: API key (if None, reads from OPENAI_API_KEY env var)
            base_url: Base URL for API (if None, uses OpenAI default)
        """
        super().__init__(config)
        self.api_key = api_key
        self.base_url = base_url
        self._client = None
        self._async_client = None

    def _get_client(self):
        """Get or create sync OpenAI client."""
        if self._client is None:
            try:
                from openai import OpenAI
                kwargs = {}
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = OpenAI(**kwargs)
                logger.info(f"OpenAI client initialized (base_url={self.base_url})")
            except ImportError:
                raise ImportError(
                    "openai package is required. Install with: pip install openai"
                )
        return self._client

    def _get_async_client(self):
        """Get or create async OpenAI client."""
        if self._async_client is None:
            try:
                from openai import AsyncOpenAI
                kwargs = {}
                if self.api_key:
                    kwargs["api_key"] = self.api_key
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._async_client = AsyncOpenAI(**kwargs)
                logger.info(f"AsyncOpenAI client initialized (base_url={self.base_url})")
            except ImportError:
                raise ImportError(
                    "openai package is required. Install with: pip install openai"
                )
        return self._async_client

    def _build_request_kwargs(self) -> dict:
        """Build kwargs for API request from config."""
        kwargs = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        if self.config.top_p != 1.0:
            kwargs["top_p"] = self.config.top_p

        if self.config.presence_penalty != 0.0:
            kwargs["presence_penalty"] = self.config.presence_penalty

        if self.config.frequency_penalty != 0.0:
            kwargs["frequency_penalty"] = self.config.frequency_penalty

        if self.config.stop:
            kwargs["stop"] = self.config.stop

        # Add any extra params
        kwargs.update(self.config.extra_params)

        return kwargs

    async def generate(self, session_id: str, user_message: str) -> str:
        """
        Generate a complete response (non-streaming).

        Args:
            session_id: Session identifier
            user_message: User's input message

        Returns:
            Complete response string
        """
        # Add user message to history
        self.add_user_message(session_id, user_message)

        try:
            client = self._get_async_client()
            messages = self.get_messages_for_api(session_id)

            kwargs = self._build_request_kwargs()
            kwargs["messages"] = messages

            logger.debug(f"Generating response for session {session_id[:8]}...")
            response = await client.chat.completions.create(**kwargs)

            assistant_message = response.choices[0].message.content or ""

            # Add assistant message to history
            self.add_assistant_message(session_id, assistant_message)

            logger.info(f"Generated {len(assistant_message)} chars for session {session_id[:8]}")
            return assistant_message

        except Exception as e:
            logger.error(f"Generation failed for session {session_id[:8]}: {e}")
            raise

    async def stream(self, session_id: str, user_message: str) -> AsyncIterator[str]:
        """
        Generate a response with token streaming.

        Args:
            session_id: Session identifier
            user_message: User's input message

        Yields:
            Response tokens as they are generated
        """
        # Add user message to history
        self.add_user_message(session_id, user_message)

        full_response = ""

        try:
            client = self._get_async_client()
            messages = self.get_messages_for_api(session_id)

            kwargs = self._build_request_kwargs()
            kwargs["messages"] = messages
            kwargs["stream"] = True

            logger.debug(f"Streaming response for session {session_id[:8]}...")

            async for chunk in await client.chat.completions.create(**kwargs):
                if chunk.choices and chunk.choices[0].delta.content:
                    token = chunk.choices[0].delta.content
                    full_response += token
                    yield token

            # Add complete assistant message to history
            self.add_assistant_message(session_id, full_response)

            logger.info(f"Streamed {len(full_response)} chars for session {session_id[:8]}")

        except Exception as e:
            logger.error(f"Streaming failed for session {session_id[:8]}: {e}")
            # Still save partial response if any
            if full_response:
                self.add_assistant_message(session_id, full_response)
            raise
