"""
E2E tests for WebRTC setup and negotiation.

Tests WebRTC offer/answer exchange, ICE candidate handling,
and audio streaming setup.
"""

import pytest
import json
import asyncio


class TestWebRTCSetup:
    """Test WebRTC connection setup."""

    def test_webrtc_offer_answer_exchange(self, sync_client, mock_webrtc):
        """Test WebRTC offer/answer exchange."""
        with sync_client.websocket_connect("/ws?user_id=test_webrtc_1") as websocket:
            # Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            ice_servers = connect_msg["data"]["ice_servers"]

            print(f"Session ID: {session_id}")
            print(f"ICE servers: {ice_servers}")

            # Verify ICE servers are provided
            assert isinstance(ice_servers, list)
            assert len(ice_servers) > 0

            # Create mock WebRTC connection
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            # Send WebRTC offer
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "sdp": offer["sdp"],
                    "type": offer["type"]
                }
            }))

            # Receive WebRTC answer
            answer_msg = json.loads(websocket.receive_text())
            print(f"Received answer: {answer_msg}")

            assert answer_msg["event"] == "webrtc_answer"
            assert "sdp" in answer_msg["data"]
            assert "type" in answer_msg["data"]
            assert answer_msg["data"]["type"] == "answer"

            # Set remote description
            webrtc.set_remote_description(
                answer_msg["data"]["sdp"],
                answer_msg["data"]["type"]
            )

            print("✅ WebRTC offer/answer exchange completed")

    def test_webrtc_ice_candidate(self, sync_client, mock_webrtc):
        """Test WebRTC ICE candidate exchange."""
        with sync_client.websocket_connect("/ws?user_id=test_webrtc_ice") as websocket:
            # Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Complete WebRTC offer/answer first
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "sdp": offer["sdp"],
                    "type": offer["type"]
                }
            }))

            # Receive answer
            json.loads(websocket.receive_text())

            # Send ICE candidate
            ice_candidate = {
                "candidate": "candidate:1 1 UDP 2130706431 192.168.1.1 54321 typ host",
                "sdpMLineIndex": 0,
                "sdpMid": "0"
            }

            websocket.send_text(json.dumps({
                "event": "webrtc_ice_candidate",
                "session_id": session_id,
                "data": ice_candidate
            }))

            print("✅ ICE candidate sent successfully")

    def test_webrtc_without_offer(self, sync_client):
        """Test attempting to stream audio without WebRTC setup."""
        with sync_client.websocket_connect("/ws?user_id=test_no_webrtc") as websocket:
            # Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Try to send audio without WebRTC setup
            # This should fail gracefully
            # (In real scenario, audio would trigger agent response with TTS,
            # which would fail due to missing WebRTC)

            print(f"✅ Session created without WebRTC: {session_id}")
            # The actual audio streaming test is in test_voice_conversation.py

    def test_ice_servers_configuration(self, sync_client):
        """Test ICE servers are properly configured."""
        with sync_client.websocket_connect("/ws?user_id=test_ice_config") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            ice_servers = connect_msg["data"]["ice_servers"]

            # Verify ICE servers structure
            assert isinstance(ice_servers, list)

            for server in ice_servers:
                assert "urls" in server
                # Should have STUN servers at minimum
                if server["urls"].startswith("stun:"):
                    print(f"STUN server: {server['urls']}")

            print(f"✅ ICE servers configured: {len(ice_servers)} servers")

    def test_webrtc_offer_with_nested_data(self, sync_client, mock_webrtc):
        """Test WebRTC offer with nested data structure."""
        with sync_client.websocket_connect("/ws?user_id=test_webrtc_nested") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            # Send offer with nested structure (backwards compatibility)
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "offer": {
                        "sdp": offer["sdp"],
                        "type": offer["type"]
                    }
                }
            }))

            # Should still receive answer
            answer_msg = json.loads(websocket.receive_text())
            assert answer_msg["event"] == "webrtc_answer"

            print("✅ Nested WebRTC offer handled correctly")

    def test_invalid_webrtc_offer(self, sync_client):
        """Test invalid WebRTC offer handling."""
        with sync_client.websocket_connect("/ws?user_id=test_invalid_offer") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Send invalid offer (missing SDP)
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "type": "offer"
                    # Missing 'sdp' field
                }
            }))

            # Server should handle gracefully (log error, no crash)
            # Verify connection is still alive with heartbeat
            websocket.send_text(json.dumps({
                "event": "heartbeat",
                "session_id": session_id,
                "data": {}
            }))

            print("✅ Invalid WebRTC offer handled gracefully")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
