"""
Base class for LLM (Large Language Model) providers.

All LLM providers must implement this interface for use in the voice pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Dict, List, Optional, Any

from ..core.types import Message, MessageRole


@dataclass
class LLMConfig:
    """Configuration for LLM providers."""
    model: str
    system_prompt: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    presence_penalty: float = 0.0
    frequency_penalty: float = 0.0
    stop: Optional[List[str]] = None
    extra_params: Dict[str, Any] = field(default_factory=dict)


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.

    All LLM implementations must inherit from this class and implement
    the required methods. The provider manages conversation state per session.

    Example:
        class MyLLM(BaseLLMProvider):
            async def generate(self, session_id: str, user_message: str) -> str:
                # Implementation here
                pass

            async def stream(self, session_id: str, user_message: str) -> AsyncIterator[str]:
                # Implementation here
                yield "token"
    """

    def __init__(self, config: LLMConfig):
        """
        Initialize LLM provider.

        Args:
            config: LLM configuration
        """
        self.config = config
        self._conversations: Dict[str, List[Message]] = {}

    def create_session(self, session_id: str) -> None:
        """
        Initialize conversation for a session.

        Creates an empty conversation history. If a system prompt is configured,
        it will be added as the first message.

        Args:
            session_id: Unique session identifier
        """
        self._conversations[session_id] = []
        if self.config.system_prompt:
            self._conversations[session_id].append(
                Message.system(self.config.system_prompt)
            )

    def cleanup_session(self, session_id: str) -> None:
        """
        Clean up conversation history for a session.

        Args:
            session_id: Session to clean up
        """
        self._conversations.pop(session_id, None)

    def get_conversation(self, session_id: str) -> List[Message]:
        """
        Get conversation history for a session.

        Args:
            session_id: Session identifier

        Returns:
            List of messages in the conversation
        """
        return self._conversations.get(session_id, [])

    def add_user_message(self, session_id: str, content: str) -> None:
        """
        Add a user message to the conversation.

        Args:
            session_id: Session identifier
            content: User message content
        """
        if session_id not in self._conversations:
            self.create_session(session_id)
        self._conversations[session_id].append(Message.user(content))

    def add_assistant_message(self, session_id: str, content: str) -> None:
        """
        Add an assistant message to the conversation.

        Args:
            session_id: Session identifier
            content: Assistant message content
        """
        if session_id not in self._conversations:
            self.create_session(session_id)
        self._conversations[session_id].append(Message.assistant(content))

    def clear_history(self, session_id: str) -> None:
        """
        Clear conversation history but keep system prompt.

        Args:
            session_id: Session identifier
        """
        if session_id in self._conversations:
            system_msgs = [
                m for m in self._conversations[session_id]
                if m.role == MessageRole.SYSTEM
            ]
            self._conversations[session_id] = system_msgs

    def get_messages_for_api(self, session_id: str) -> List[Dict[str, str]]:
        """
        Get messages in OpenAI-compatible format for API calls.

        Args:
            session_id: Session identifier

        Returns:
            List of message dicts with 'role' and 'content' keys
        """
        messages = self.get_conversation(session_id)
        return [m.to_dict() for m in messages]

    @abstractmethod
    async def generate(self, session_id: str, user_message: str) -> str:
        """
        Generate a complete response (non-streaming).

        This method adds the user message to history, generates a response,
        adds the response to history, and returns the response.

        Args:
            session_id: Session identifier
            user_message: User's input message

        Returns:
            Complete response string

        Raises:
            Exception: If generation fails
        """
        pass

    @abstractmethod
    async def stream(self, session_id: str, user_message: str) -> AsyncIterator[str]:
        """
        Generate a response with token streaming.

        This method adds the user message to history, streams the response
        token by token, adds the complete response to history when done,
        and yields each token.

        Args:
            session_id: Session identifier
            user_message: User's input message

        Yields:
            Response tokens as they are generated

        Raises:
            Exception: If generation fails
        """
        pass

    def get_name(self) -> str:
        """
        Get the provider name.

        Returns:
            Human-readable provider name
        """
        return self.__class__.__name__

    def handle_interruption(self, session_id: str) -> None:
        """
        Handle user interruption during generation.

        Override this method to implement custom interruption logic.
        Default implementation does nothing.

        Args:
            session_id: Session that was interrupted
        """
        pass
