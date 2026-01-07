"""
Diagnostic tests for WebRTC audio output issues.

These tests specifically check if TTS audio is being streamed via WebRTC.
Use these to diagnose "no audio output" problems.
"""

import pytest
import json
import time
import base64


class TestWebRTCAudioOutput:
    """Diagnostic tests for WebRTC audio streaming."""

    def test_check_webrtc_enabled_flag(self, sync_client, mock_webrtc):
        """
        Test 1: Verify webrtc_enabled flag is set after offer/answer.

        This is THE critical check - if this flag isn't True, no audio will stream.
        """
        with sync_client.websocket_connect("/ws?user_id=test_webrtc_flag") as websocket:
            print("\n" + "="*60)
            print("TEST 1: Checking webrtc_enabled flag")
            print("="*60)

            # Connect
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"✅ Connected: {session_id}")

            # Send WebRTC offer
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            print(f"\n📤 Sending WebRTC offer...")
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "sdp": offer["sdp"],
                    "type": offer["type"]
                }
            }))

            # Receive answer
            answer_msg = json.loads(websocket.receive_text())

            print(f"\n📥 Received: {answer_msg['event']}")

            if answer_msg["event"] == "webrtc_answer":
                print("✅ PASS: WebRTC offer/answer exchange successful")
                print(f"   SDP length: {len(answer_msg['data']['sdp'])}")
                print(f"   Type: {answer_msg['data']['type']}")
                print("\n⚠️  IMPORTANT: Frontend must now:")
                print("   1. Set this as remote description")
                print("   2. Listen for audio track events")
                print("   3. Play the received audio stream")
            else:
                print(f"❌ FAIL: Expected webrtc_answer, got {answer_msg['event']}")
                pytest.fail("WebRTC setup failed")

    def test_audio_streaming_with_webrtc(self, sync_client, mock_webrtc):
        """
        Test 2: Verify TTS audio streaming occurs when WebRTC is set up.

        Sends a simple text message that should trigger TTS audio streaming.
        """
        with sync_client.websocket_connect("/ws?user_id=test_audio_stream") as websocket:
            print("\n" + "="*60)
            print("TEST 2: Checking TTS audio streaming")
            print("="*60)

            # Setup
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"✅ Connected: {session_id}")

            # Setup WebRTC
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            print(f"\n📤 Setting up WebRTC...")
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "sdp": offer["sdp"],
                    "type": offer["type"]
                }
            }))

            answer_msg = json.loads(websocket.receive_text())
            assert answer_msg["event"] == "webrtc_answer"
            print("✅ WebRTC setup complete")

            # Send a simple audio chunk to trigger agent response
            # Use minimal audio data
            dummy_audio = b'\x00' * 1024  # 1KB of silence
            audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')

            print(f"\n📤 Sending audio chunk to trigger agent response...")
            websocket.send_text(json.dumps({
                "event": "audio_chunk",
                "session_id": session_id,
                "data": {
                    "audio": audio_b64
                }
            }))

            # Wait for responses
            print("\n⏳ Waiting for agent response and audio streaming...")
            messages = []
            max_wait = 20
            start_time = time.time()

            while time.time() - start_time < max_wait:
                try:
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
                    event = msg['event']

                    print(f"📥 Received: {event}")

                    if event == "error":
                        error_type = msg['data'].get('error_type', 'unknown')
                        error_message = msg['data'].get('message', 'unknown')

                        if error_type == "webrtc_not_ready":
                            print(f"\n❌ FAIL: WebRTC not ready!")
                            print(f"   Message: {error_message}")
                            print("\n🔍 DIAGNOSIS:")
                            print("   - WebRTC offer/answer completed BUT flag not set")
                            print("   - Check server logs for WebRTC setup errors")
                            print("   - Verify WebRTC manager is working correctly")
                            pytest.fail("WebRTC audio streaming failed: WebRTC not ready")
                        else:
                            print(f"\n⚠️  Error: {error_type} - {error_message}")

                    elif event == "streaming_complete":
                        print("\n✅ PASS: Audio streaming completed!")
                        print(f"\n📊 Message sequence received:")
                        for i, m in enumerate(messages, 1):
                            print(f"   {i}. {m['event']}")
                        return

                except Exception as e:
                    print(f"Error receiving message: {e}")
                    break

            # Analyze what we got
            events = [m['event'] for m in messages]
            print(f"\n📊 Events received: {events}")

            if "error" in events:
                error_msg = next(m for m in messages if m['event'] == 'error')
                print(f"\n❌ FAIL: Received error: {error_msg['data']}")

            if "streaming_complete" not in events:
                print(f"\n⚠️  WARNING: No 'streaming_complete' event received")
                print(f"\n🔍 DIAGNOSIS:")
                if "agent_response" in events:
                    print("   ✅ Agent text response received")
                    print("   ❌ But no TTS audio streaming")
                    print("\n   Possible causes:")
                    print("   1. WebRTC track not created on server")
                    print("   2. FFmpeg conversion failing")
                    print("   3. Audio chunks not being sent to WebRTC")
                else:
                    print("   ❌ No agent response at all")
                    print("\n   Possible causes:")
                    print("   1. Audio validation failed (no speech detected)")
                    print("   2. ASR transcription failed")
                    print("   3. Agent processing failed")

    def test_audio_without_webrtc_shows_error(self, sync_client):
        """
        Test 3: Verify error message when WebRTC is NOT set up.

        This demonstrates what happens when frontend skips WebRTC setup.
        """
        with sync_client.websocket_connect("/ws?user_id=test_no_webrtc_error") as websocket:
            print("\n" + "="*60)
            print("TEST 3: Checking error when WebRTC NOT set up")
            print("="*60)

            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"✅ Connected: {session_id}")

            # SKIP WebRTC setup intentionally
            print(f"\n⚠️  Skipping WebRTC setup (simulating frontend issue)...")

            # Send audio to trigger agent response
            dummy_audio = b'\x00' * 1024
            audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')

            print(f"\n📤 Sending audio chunk...")
            websocket.send_text(json.dumps({
                "event": "audio_chunk",
                "session_id": session_id,
                "data": {
                    "audio": audio_b64
                }
            }))

            # Wait for response
            print("\n⏳ Waiting for response...")
            messages = []
            max_wait = 20
            start_time = time.time()

            while time.time() - start_time < max_wait:
                try:
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
                    event = msg['event']

                    print(f"📥 Received: {event}")

                    if event == "error" and msg['data'].get('error_type') == 'webrtc_not_ready':
                        print(f"\n✅ PASS: Correct error received!")
                        print(f"   Error message: {msg['data']['message']}")
                        print("\n🔍 THIS IS THE ISSUE:")
                        print("   Frontend is NOT setting up WebRTC before audio streaming")
                        print("   Server correctly rejects TTS streaming without WebRTC")
                        return

                    elif event == "streaming_complete":
                        print(f"\n⚠️  Unexpected: Got streaming_complete without WebRTC!")

                except Exception as e:
                    print(f"Error: {e}")
                    break

            events = [m['event'] for m in messages]
            print(f"\n📊 Events received: {events}")

            if "error" not in events:
                print(f"\n⚠️  No error received - server may have changed behavior")

    def test_ice_servers_provided(self, sync_client):
        """
        Test 4: Verify ICE servers are provided for NAT traversal.

        Without ICE servers, WebRTC may fail in real-world scenarios.
        """
        with sync_client.websocket_connect("/ws?user_id=test_ice_servers") as websocket:
            print("\n" + "="*60)
            print("TEST 4: Checking ICE servers configuration")
            print("="*60)

            connect_msg = json.loads(websocket.receive_text())
            ice_servers = connect_msg["data"]["ice_servers"]

            print(f"\n📊 ICE Servers Configuration:")
            print(f"   Count: {len(ice_servers)}")

            has_stun = False
            has_turn = False

            for i, server in enumerate(ice_servers, 1):
                urls = server.get('urls', '')
                print(f"\n   Server {i}:")
                print(f"      URLs: {urls}")

                if urls.startswith('stun:'):
                    has_stun = True
                    print(f"      Type: STUN (NAT traversal)")
                elif urls.startswith('turn:'):
                    has_turn = True
                    print(f"      Type: TURN (relay)")
                    if 'username' in server:
                        print(f"      Auth: ✅ (username provided)")
                    else:
                        print(f"      Auth: ❌ (no credentials)")

            print(f"\n📊 Summary:")
            print(f"   STUN servers: {'✅ Yes' if has_stun else '❌ No'}")
            print(f"   TURN servers: {'✅ Yes' if has_turn else '⚠️  No (may fail behind strict NAT)'}")

            if not has_stun:
                print(f"\n⚠️  WARNING: No STUN servers configured!")
                print(f"   WebRTC may fail to establish connection")

    def test_server_logs_diagnostic(self, sync_client, mock_webrtc):
        """
        Test 5: Trigger full flow and show what to check in server logs.

        This test guides you through checking server logs for the issue.
        """
        with sync_client.websocket_connect("/ws?user_id=test_diagnostic") as websocket:
            print("\n" + "="*60)
            print("TEST 5: Server Log Diagnostic Guide")
            print("="*60)

            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            session_short = session_id[:8]

            print(f"\n🔍 Session ID: {session_id}")
            print(f"   (Short: {session_short}...)")

            print("\n📋 CHECK SERVER LOGS FOR THESE MESSAGES:")
            print(f"\n1. WebRTC Setup:")
            print(f"   ✅ Look for: 'session={session_short}... | webrtc_enabled=True'")
            print(f"   ❌ If False: WebRTC setup failed")

            print(f"\n2. TTS Streaming Attempt:")
            print(f"   ✅ Look for: 'Routing TTS to WebRTC for session {session_short}...'")
            print(f"   ❌ If missing: stream_tts_response not called or blocked")

            print(f"\n3. FFmpeg Process:")
            print(f"   ✅ Look for: 'Starting FFmpeg input stream for session {session_short}...'")
            print(f"   ❌ If missing: FFmpeg not starting")

            print(f"\n4. Audio Chunks:")
            print(f"   ✅ Look for: 'PCM chunk #X' messages")
            print(f"   ❌ If missing: Audio not being sent to WebRTC")

            print(f"\n5. Errors:")
            print(f"   🔍 Look for: 'ERROR' or 'WebRTC not enabled' near session {session_short}")

            # Setup WebRTC
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()

            print(f"\n📤 Sending WebRTC offer...")
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": {
                    "sdp": offer["sdp"],
                    "type": offer["type"]
                }
            }))

            answer_msg = json.loads(websocket.receive_text())

            if answer_msg["event"] == "webrtc_answer":
                print(f"✅ WebRTC setup completed")
                print(f"\n👉 NOW CHECK SERVER LOGS for:")
                print(f"   'session={session_short}... | webrtc_enabled=True'")
            else:
                print(f"❌ WebRTC setup failed - check server logs for errors")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
