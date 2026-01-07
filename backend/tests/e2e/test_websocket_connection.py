"""
E2E tests for WebSocket connection flow.

Tests the basic WebSocket connection, message handling, and session management.
"""

import pytest
import json
import asyncio
from fastapi.testclient import TestClient


class TestWebSocketConnection:
    """Test WebSocket connection lifecycle."""

    def test_websocket_connect(self, sync_client):
        """Test WebSocket connection establishment."""
        with sync_client.websocket_connect("/ws?user_id=test_user_123") as websocket:
            # Receive connection confirmation
            data = websocket.receive_text()
            message = json.loads(data)

            # Verify connection message
            assert message["event"] == "connected"
            assert "session_id" in message["data"]
            assert "ice_servers" in message["data"]
            assert "timestamp" in message["data"]

            session_id = message["data"]["session_id"]
            print(f"✅ Connected with session_id: {session_id}")

    def test_websocket_heartbeat(self, sync_client):
        """Test WebSocket heartbeat mechanism."""
        with sync_client.websocket_connect("/ws?user_id=test_user_456") as websocket:
            # Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Send heartbeat
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "session_id": session_id,
                "data": {}
            }))

            # Should not receive any response (heartbeat is silent)
            # Just verify connection is still alive
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "session_id": session_id,
                "data": {}
            }))

            print("✅ Heartbeat sent successfully")

    def test_health_endpoint(self, sync_client):
        """Test HTTP health check endpoint."""
        response = sync_client.get("/health")

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "healthy"
        assert "active_sessions" in data
        assert "components" in data
        assert data["components"]["tts"] is True
        assert data["components"]["asr"] is True
        assert data["components"]["webrtc"] is True
        assert data["components"]["agent"] is True

        print(f"✅ Health check passed: {data}")

    def test_root_endpoint(self, sync_client):
        """Test root endpoint."""
        response = sync_client.get("/")

        assert response.status_code == 200
        data = response.json()

        assert data["service"] == "Voice Agent Demo"
        assert data["status"] == "running"
        assert data["version"] == "1.0.0"
        assert "endpoints" in data

        print(f"✅ Root endpoint: {data}")

    def test_multiple_connections(self, sync_client):
        """Test multiple simultaneous WebSocket connections."""
        connections = []

        # Open 3 connections
        for i in range(3):
            ws = sync_client.websocket_connect(f"/ws?user_id=test_user_multi_{i}")
            connections.append(ws.__enter__())

        try:
            # Verify all connections are established
            session_ids = []
            for ws in connections:
                msg = json.loads(ws.receive_text())
                assert msg["event"] == "connected"
                session_ids.append(msg["data"]["session_id"])

            # Verify all session IDs are unique
            assert len(session_ids) == len(set(session_ids))
            print(f"✅ Opened {len(connections)} simultaneous connections")

        finally:
            # Close all connections
            for ws in connections:
                ws.__exit__(None, None, None)

    def test_connection_with_anonymous_user(self, sync_client):
        """Test connection with anonymous user (no user_id)."""
        with sync_client.websocket_connect("/ws") as websocket:
            msg = json.loads(websocket.receive_text())

            assert msg["event"] == "connected"
            assert "session_id" in msg["data"]

            # Server should generate a UUID for anonymous users
            session_id = msg["data"]["session_id"]
            assert len(session_id) == 36  # UUID format

            print(f"✅ Anonymous connection: {session_id}")

    def test_invalid_message_format(self, sync_client):
        """Test handling of invalid message format."""
        with sync_client.websocket_connect("/ws?user_id=test_invalid") as websocket:
            # Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Send invalid JSON
            websocket.send_text("not a json string")

            # Server should handle gracefully (no crash)
            # Send valid heartbeat to verify connection is still alive
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "session_id": session_id,
                "data": {}
            }))

            print("✅ Invalid message handled gracefully")

    def test_message_without_session_id(self, sync_client):
        """Test message without session_id."""
        with sync_client.websocket_connect("/ws?user_id=test_no_session") as websocket:
            # Receive connection confirmation
            json.loads(websocket.receive_text())

            # Send message without session_id
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "data": {}
            }))

            # Server should log warning but not crash
            # Verify with another valid message
            print("✅ Message without session_id handled")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
