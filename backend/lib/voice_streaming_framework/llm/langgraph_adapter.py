"""
LangGraph adapter for voice streaming.

Wraps any LangGraph agent to work with the voice streaming pipeline.
Handles streaming token extraction from LangGraph's event system.
"""

import logging
from typing import AsyncIterator, Optional, Any

from .base import BaseLLMProvider, LLMConfig

logger = logging.getLogger(__name__)


class LangGraphAdapter(BaseLLMProvider):
    """
    Adapter that wraps a LangGraph agent for voice streaming.

    Extracts streaming tokens from LangGraph's astream_events() API
    to enable real-time TTS synthesis.

    Example:
        from langgraph.graph import StateGraph
        from voice_streaming_framework.llm import LangGraphAdapter

        # Define your LangGraph
        graph = StateGraph(...)
        graph.add_node(...)
        compiled_graph = graph.compile()

        # Wrap for voice streaming
        llm = LangGraphAdapter(graph=compiled_graph)

        # Use in pipeline
        pipeline = StreamingVoicePipeline(llm=llm, ...)

    Note:
        The graph must have a messages key in its state that follows
        the LangChain message format (HumanMessage, AIMessage, etc.)
    """

    def __init__(
        self,
        graph: Any,
        config: Optional[LLMConfig] = None,
        input_key: str = "messages",
        thread_id_from_session: bool = True,
    ):
        """
        Initialize LangGraph adapter.

        Args:
            graph: Compiled LangGraph (from StateGraph.compile())
            config: Optional LLM config (system prompt managed by graph)
            input_key: Key in graph state for messages (default: "messages")
            thread_id_from_session: Use session_id as thread_id for persistence
        """
        # LangGraph manages its own config, so we use minimal config
        super().__init__(config or LLMConfig(model="langgraph"))
        self.graph = graph
        self.input_key = input_key
        self.thread_id_from_session = thread_id_from_session

        # Check for required LangChain imports
        try:
            from langchain_core.messages import HumanMessage, AIMessage
            self._HumanMessage = HumanMessage
            self._AIMessage = AIMessage
        except ImportError:
            raise ImportError(
                "langchain-core is required for LangGraph adapter. "
                "Install with: pip install langchain-core langgraph"
            )

    def _get_config(self, session_id: str) -> dict:
        """Get LangGraph config with thread_id for persistence."""
        config = {}
        if self.thread_id_from_session:
            config["configurable"] = {"thread_id": session_id}
        return config

    async def generate(self, session_id: str, user_message: str) -> str:
        """
        Generate a complete response using LangGraph (non-streaming).

        Args:
            session_id: Session identifier (used as thread_id)
            user_message: User's input message

        Returns:
            Complete response string
        """
        try:
            config = self._get_config(session_id)

            # Invoke the graph
            result = await self.graph.ainvoke(
                {self.input_key: [self._HumanMessage(content=user_message)]},
                config=config
            )

            # Extract the last AI message
            messages = result.get(self.input_key, [])
            for msg in reversed(messages):
                if hasattr(msg, "content") and isinstance(msg, self._AIMessage):
                    return msg.content

            # Fallback: return last message content
            if messages and hasattr(messages[-1], "content"):
                return messages[-1].content

            logger.warning(f"No response found in LangGraph output for {session_id[:8]}")
            return ""

        except Exception as e:
            logger.error(f"LangGraph generation failed for {session_id[:8]}: {e}")
            raise

    async def stream(self, session_id: str, user_message: str) -> AsyncIterator[str]:
        """
        Stream tokens from LangGraph using astream_events.

        Extracts tokens from on_chat_model_stream events to enable
        real-time TTS synthesis.

        Args:
            session_id: Session identifier (used as thread_id)
            user_message: User's input message

        Yields:
            Response tokens as they are generated
        """
        try:
            config = self._get_config(session_id)

            logger.debug(f"Streaming LangGraph response for {session_id[:8]}...")

            async for event in self.graph.astream_events(
                {self.input_key: [self._HumanMessage(content=user_message)]},
                config=config,
                version="v2"
            ):
                # Extract tokens from chat model streaming events
                if event["event"] == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield chunk.content

        except Exception as e:
            logger.error(f"LangGraph streaming failed for {session_id[:8]}: {e}")
            raise

    def create_session(self, session_id: str) -> None:
        """
        Initialize session for LangGraph.

        Note: LangGraph manages its own conversation state via thread_id,
        so this is a no-op unless using local conversation tracking.
        """
        # LangGraph uses checkpointers for state management
        # We don't maintain local conversation state
        pass

    def cleanup_session(self, session_id: str) -> None:
        """
        Clean up session.

        Note: LangGraph state is managed by its checkpointer.
        To clear state, you would need to clear the checkpointer.
        """
        pass

    async def is_available(self) -> bool:
        """Check if LangGraph is available."""
        return self.graph is not None
