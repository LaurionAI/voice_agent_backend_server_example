"""
Simple Agent with Conversation Memory

A minimal agent implementation demonstrating:
- Conversation state management (short-term memory)
- Multi-turn dialog support
- LLM integration (GLM-4.5-air)
- No database, no cache - pure in-memory state
"""

import logging
import os
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Single message in conversation history."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class ConversationState:
    """Conversation state for a single session."""
    session_id: str
    messages: List[Message] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    last_activity: datetime = field(default_factory=datetime.now)

    def add_message(self, role: str, content: str):
        """Add a message to conversation history."""
        self.messages.append(Message(role=role, content=content))
        self.last_activity = datetime.now()

    def get_recent_messages(self, limit: int = 10) -> List[Message]:
        """Get recent messages for context."""
        return self.messages[-limit:]

    def get_conversation_context(self) -> str:
        """Get formatted conversation context for the agent."""
        if not self.messages:
            return ""

        context = "Previous conversation:\n"
        for msg in self.get_recent_messages():
            role_label = "User" if msg.role == "user" else "Assistant"
            context += f"{role_label}: {msg.content}\n"
        return context


class SimpleAgent:
    """
    Simple conversational agent with memory.

    Features:
    - Maintains conversation state per session
    - Supports multi-turn dialog
    - LLM integration (GLM-4.5-air)
    - No external dependencies (no DB, no cache)
    """

    def __init__(
        self,
        model: str = "glm-4.5-air",
        temperature: float = 0.7
    ):
        """Initialize agent with LLM and empty conversation states."""
        self.conversations: Dict[str, ConversationState] = {}

        # Initialize LLM (GLM-4.5-air)
        api_key = os.getenv("ZHIPUAI_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ZHIPUAI_API_KEY environment variable not set. "
                "Please ensure the .env file is loaded correctly."
            )

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            openai_api_base="https://open.bigmodel.cn/api/paas/v4/"
        )

        logger.info(f"🤖 SimpleAgent initialized with model: {model}")

    def create_session(self, session_id: str):
        """Create a new conversation session."""
        self.conversations[session_id] = ConversationState(session_id=session_id)
        logger.info(f"✅ Created conversation session: {session_id[:8]}...")

    def cleanup_session(self, session_id: str):
        """Clean up conversation session."""
        if session_id in self.conversations:
            msg_count = len(self.conversations[session_id].messages)
            del self.conversations[session_id]
            logger.info(f"🗑️ Cleaned up session {session_id[:8]}... ({msg_count} messages)")

    def get_conversation(self, session_id: str) -> Optional[ConversationState]:
        """Get conversation state for a session."""
        return self.conversations.get(session_id)

    async def process_query(self, session_id: str, query: str) -> str:
        """
        Process user query and generate response.

        Args:
            session_id: Session identifier
            query: User's query text

        Returns:
            Agent's response text
        """
        try:
            # Get or create conversation state
            if session_id not in self.conversations:
                self.create_session(session_id)

            conversation = self.conversations[session_id]

            # Add user message to history
            conversation.add_message("user", query)

            # Get conversation context
            context = conversation.get_conversation_context()
            message_count = len(conversation.messages)

            logger.info(f"🧠 Processing query (context: {message_count} messages)")

            # Generate response (simple rule-based for demo)
            response = await self._generate_response(query, context, conversation)

            # Add assistant response to history
            conversation.add_message("assistant", response)

            return response

        except Exception as e:
            logger.error(f"❌ Error processing query: {e}")
            return "I apologize, but I encountered an error processing your request. Please try again."

    async def _generate_response(
        self,
        query: str,
        context: str,
        conversation: ConversationState
    ) -> str:
        """
        Generate response using LLM with conversation context.

        Args:
            query: Current user query
            context: Formatted conversation history
            conversation: Conversation state object

        Returns:
            LLM-generated response
        """
        try:
            # Build messages for LLM
            messages = [
                SystemMessage(content="""You are a friendly and helpful voice assistant.
You're part of a voice streaming demo using WebRTC technology.

Key behaviors:
- Be conversational and natural (this is voice, not text chat)
- Keep responses concise (1-3 sentences typically)
- Remember the conversation history provided
- Be helpful and engaging
- If asked about yourself, mention you're a demo voice assistant

Remember: Keep it brief and natural for voice interaction!""")
            ]

            # Add conversation history
            # No limit - keep full conversation history
            for msg in conversation.messages:
                if msg.role == "user":
                    messages.append(HumanMessage(content=msg.content))
                else:
                    messages.append(AIMessage(content=msg.content))

            # Invoke LLM
            response = await self.llm.ainvoke(messages)

            return response.content.strip()

        except Exception as e:
            logger.error(f"❌ LLM generation error: {e}")
            # Fallback response
            return "I apologize, but I encountered an error. Could you please try asking that again?"

    def handle_interruption(self, session_id: str):
        """
        Handle user interruption.

        Can be used to:
        - Reset partial state
        - Clear pending operations
        - Log interruption events
        """
        logger.info(f"🛑 Handling interruption for {session_id[:8]}...")
        # For now, just log the interruption
        # In a more complex agent, you might:
        # - Cancel ongoing LLM calls
        # - Reset partial responses
        # - Clear temporary state

    def get_stats(self, session_id: str) -> dict:
        """Get statistics for a conversation session."""
        conversation = self.get_conversation(session_id)
        if not conversation:
            return {"error": "Session not found"}

        return {
            "session_id": session_id,
            "message_count": len(conversation.messages),
            "created_at": conversation.created_at.isoformat(),
            "last_activity": conversation.last_activity.isoformat(),
            "duration_seconds": (conversation.last_activity - conversation.created_at).total_seconds()
        }
