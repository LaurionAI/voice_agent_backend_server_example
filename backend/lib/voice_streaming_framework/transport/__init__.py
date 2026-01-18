"""
Audio transport layers for voice streaming.

Available transports:
- WebRTCTransport: Low-latency WebRTC with Opus codec
- WebSocketTransport: Simple WebSocket with base64-encoded audio
"""

from .base import BaseTransport, TransportConfig
from .webrtc import WebRTCTransport
from .websocket import WebSocketTransport

__all__ = [
    # Base
    "BaseTransport",
    "TransportConfig",
    # Implementations
    "WebRTCTransport",
    "WebSocketTransport",
]
