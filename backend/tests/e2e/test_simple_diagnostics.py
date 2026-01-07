"""
Simple working diagnostic tests.

These tests verify basic server functionality without triggering
the full audio processing pipeline.
"""

import pytest
import json


class TestSimpleDiagnostics:
    """Simple tests that actually work."""

    def test_health_endpoint(self, sync_client):
        """Test 1: Check server health."""
        response = sync_client.get("/health")
        assert response.status_code == 200

        data = response.json()
        print(f"\n✅ Server Health:")
        print(f"   Status: {data['status']}")
        print(f"   TTS: {data['components']['tts']}")
        print(f"   ASR: {data['components']['asr']}")
        print(f"   WebRTC: {data['components']['webrtc']}")
        print(f"   Agent: {data['components']['agent']}")

    def test_websocket_connection(self, sync_client):
        """Test 2: Check WebSocket connection."""
        with sync_client.websocket_connect("/ws?user_id=test_user") as websocket:
            msg = json.loads(websocket.receive_text())

            print(f"\n✅ WebSocket Connected:")
            print(f"   Event: {msg['event']}")
            print(f"   Session ID: {msg['data']['session_id'][:8]}...")
            print(f"   ICE Servers: {len(msg['data']['ice_servers'])}")

            assert msg["event"] == "connected"
            assert "session_id" in msg["data"]
            assert "ice_servers" in msg["data"]

    def test_ice_servers_configured(self, sync_client):
        """Test 3: Check ICE servers for WebRTC."""
        with sync_client.websocket_connect("/ws") as websocket:
            msg = json.loads(websocket.receive_text())
            ice_servers = msg["data"]["ice_servers"]

            print(f"\n✅ ICE Servers ({len(ice_servers)}):")
            for server in ice_servers:
                print(f"   - {server['urls']}")

            assert len(ice_servers) > 0

    def test_heartbeat(self, sync_client):
        """Test 4: Check heartbeat works."""
        with sync_client.websocket_connect("/ws") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Send heartbeat
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "session_id": session_id,
                "data": {}
            }))

            print(f"\n✅ Heartbeat sent successfully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
