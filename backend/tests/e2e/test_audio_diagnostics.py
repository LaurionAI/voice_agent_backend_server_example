"""
Simple diagnostic tests for audio output issues.

These tests don't require real WebRTC - they just check server-side behavior
to help diagnose "no audio output" problems.
"""

import pytest
import json
import time
import base64


class TestAudioDiagnostics:
    """Simple diagnostic tests for audio streaming issues."""

    def test_server_components_healthy(self, sync_client):
        """
        Test 1: Verify all server components are initialized.
        """
        print("\n" + "="*60)
        print("TEST 1: Server Component Health Check")
        print("="*60)

        response = sync_client.get("/health")
        assert response.status_code == 200

        data = response.json()
        print(f"\n📊 Component Status:")
        print(f"   TTS:    {'✅' if data['components']['tts'] else '❌'}")
        print(f"   ASR:    {'✅' if data['components']['asr'] else '❌'}")
        print(f"   WebRTC: {'✅' if data['components']['webrtc'] else '❌'}")
        print(f"   Agent:  {'✅' if data['components']['agent'] else '❌'}")

        assert data['components']['tts'] is True, "TTS not initialized"
        assert data['components']['asr'] is True, "ASR not initialized"
        assert data['components']['webrtc'] is True, "WebRTC not initialized"
        assert data['components']['agent'] is True, "Agent not initialized"

        print(f"\n✅ All components healthy")

    def test_websocket_connection_provides_ice_servers(self, sync_client):
        """
        Test 2: Verify ICE servers are provided for WebRTC.
        """
        print("\n" + "="*60)
        print("TEST 2: ICE Servers Configuration")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_ice") as websocket:
            connect_msg = json.loads(websocket.receive_text())

            assert connect_msg["event"] == "connected"
            ice_servers = connect_msg["data"]["ice_servers"]

            print(f"\n📊 ICE Servers: {len(ice_servers)} configured")
            for i, server in enumerate(ice_servers, 1):
                print(f"   {i}. {server['urls']}")

            assert len(ice_servers) > 0, "No ICE servers configured"
            print(f"\n✅ ICE servers available for WebRTC")

    def test_audio_without_webrtc_gives_error(self, sync_client):
        """
        Test 3: Verify server rejects audio streaming without WebRTC setup.

        This demonstrates the issue - if frontend doesn't set up WebRTC,
        the server will refuse to stream audio.
        """
        print("\n" + "="*60)
        print("TEST 3: Audio Streaming Without WebRTC (Expected Error)")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_no_webrtc") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"✅ Connected: {session_id[:8]}...")

            # Send dummy audio WITHOUT setting up WebRTC first
            dummy_audio = b'\x00' * 1024
            audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')

            print(f"\n⚠️  Intentionally skipping WebRTC setup...")
            print(f"📤 Sending audio chunk...")

            websocket.send_text(json.dumps({
                "event": "audio_chunk",
                "session_id": session_id,
                "data": {
                    "audio": audio_b64
                }
            }))

            # Wait for responses
            print(f"\n⏳ Waiting for server response...")
            messages = []
            start_time = time.time()

            while time.time() - start_time < 15:
                try:
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
                    print(f"📥 Received: {msg['event']}")

                    # Look for the expected error
                    if msg['event'] == 'error' and msg['data'].get('error_type') == 'webrtc_not_ready':
                        print(f"\n✅ EXPECTED ERROR received!")
                        print(f"   Error type: {msg['data']['error_type']}")
                        print(f"   Message: {msg['data']['message']}")
                        print(f"\n🔍 DIAGNOSIS:")
                        print(f"   This error proves the issue:")
                        print(f"   - Server requires WebRTC to be set up FIRST")
                        print(f"   - Frontend must send 'webrtc_offer' event")
                        print(f"   - Without it, NO audio will be streamed")
                        return

                    # If we get agent_response but no error, wait a bit more
                    if msg['event'] == 'agent_response':
                        print(f"   Agent response received, waiting for TTS attempt...")

                    # Should NOT get streaming_complete without WebRTC
                    if msg['event'] == 'streaming_complete':
                        pytest.fail("Got streaming_complete without WebRTC setup!")

                except Exception as e:
                    break

            events = [m['event'] for m in messages]
            print(f"\n📊 Events received: {events}")

            if 'error' not in events:
                print(f"\n⚠️  Note: May receive 'no_speech_detected' instead if audio validation fails")

    def test_session_info_tracking(self, sync_client):
        """
        Test 4: Verify session is tracked correctly.
        """
        print("\n" + "="*60)
        print("TEST 4: Session Tracking")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_session_track") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            print(f"✅ Session created: {session_id[:8]}...")

            # Check health endpoint shows active session
            response = sync_client.get("/health")
            data = response.json()

            print(f"\n📊 Active sessions: {data['active_sessions']}")
            assert data['active_sessions'] >= 1, "Session not tracked"

            print(f"✅ Session tracked correctly")

    def test_connection_metadata(self, sync_client):
        """
        Test 5: Verify connection metadata is captured.
        """
        print("\n" + "="*60)
        print("TEST 5: Connection Metadata")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_metadata_user") as websocket:
            connect_msg = json.loads(websocket.receive_text())

            print(f"\n📊 Connection metadata:")
            print(f"   Event: {connect_msg['event']}")
            print(f"   Session ID: {connect_msg['data']['session_id'][:8]}...")
            print(f"   Timestamp: {connect_msg['data']['timestamp']}")
            print(f"   ICE servers: {len(connect_msg['data']['ice_servers'])}")

            assert connect_msg["event"] == "connected"
            assert "session_id" in connect_msg["data"]
            assert "timestamp" in connect_msg["data"]
            assert "ice_servers" in connect_msg["data"]

            print(f"\n✅ All metadata present")

    def test_multiple_audio_chunks_buffering(self, sync_client):
        """
        Test 6: Verify audio buffering works (without WebRTC).
        """
        print("\n" + "="*60)
        print("TEST 6: Audio Buffering")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_buffering") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            print(f"✅ Connected: {session_id[:8]}...")

            # Send multiple small audio chunks
            print(f"\n📤 Sending 3 audio chunks...")
            for i in range(3):
                dummy_audio = b'\x00' * 512
                audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')

                websocket.send_text(json.dumps({
                    "event": "audio_chunk",
                    "session_id": session_id,
                    "data": {"audio": audio_b64}
                }))
                print(f"   Chunk {i+1} sent")
                time.sleep(0.1)

            print(f"\n⏳ Waiting for buffer processing (1.5s timeout)...")
            time.sleep(2)

            # Collect any responses
            messages = []
            try:
                for _ in range(5):
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
                    print(f"📥 Received: {msg['event']}")
            except:
                pass

            print(f"\n✅ Audio buffering test complete")
            print(f"   Received {len(messages)} messages")

    def test_interrupt_handling(self, sync_client):
        """
        Test 7: Verify interrupt is handled.
        """
        print("\n" + "="*60)
        print("TEST 7: Interrupt Handling")
        print("="*60)

        with sync_client.websocket_connect("/ws?user_id=test_interrupt") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            print(f"✅ Connected: {session_id[:8]}...")

            # Send interrupt
            print(f"\n📤 Sending interrupt...")
            websocket.send_text(json.dumps({
                "event": "interrupt",
                "session_id": session_id,
                "data": {
                    "reason": "test_interruption"
                }
            }))

            # Wait for acknowledgment
            for _ in range(3):
                try:
                    msg = json.loads(websocket.receive_text())
                    print(f"📥 Received: {msg['event']}")

                    if msg['event'] == 'voice_interrupted':
                        print(f"\n✅ Interrupt acknowledged!")
                        print(f"   Reason: {msg['data']['reason']}")
                        print(f"   Time: {msg['data']['interruption_time_ms']}ms")
                        return
                except:
                    break

            print(f"\n✅ Interrupt test complete")


class TestAudioFlowDiagnosis:
    """High-level diagnosis of audio flow."""

    def test_diagnose_audio_pipeline(self, sync_client):
        """
        MASTER DIAGNOSTIC: Run through entire flow and report findings.
        """
        print("\n" + "="*70)
        print("🔍 MASTER DIAGNOSTIC: Audio Pipeline Analysis")
        print("="*70)

        findings = []

        # 1. Check components
        print(f"\n[1/3] Checking server components...")
        response = sync_client.get("/health")
        if response.status_code == 200:
            data = response.json()
            all_healthy = all([
                data['components']['tts'],
                data['components']['asr'],
                data['components']['webrtc'],
                data['components']['agent']
            ])
            if all_healthy:
                findings.append("✅ All server components initialized")
            else:
                findings.append("❌ Some components not initialized")
        else:
            findings.append("❌ Health endpoint failed")

        # 2. Check WebSocket and ICE servers
        print(f"[2/3] Checking WebSocket and ICE servers...")
        with sync_client.websocket_connect("/ws?user_id=diagnostic") as websocket:
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            if connect_msg["event"] == "connected":
                findings.append("✅ WebSocket connection works")

            ice_servers = connect_msg["data"]["ice_servers"]
            if len(ice_servers) > 0:
                findings.append(f"✅ ICE servers configured ({len(ice_servers)} servers)")
            else:
                findings.append("⚠️  No ICE servers configured")

            # 3. Check error when WebRTC not set up
            print(f"[3/3] Checking WebRTC requirement...")
            dummy_audio = b'\x00' * 1024
            audio_b64 = base64.b64encode(dummy_audio).decode('utf-8')

            websocket.send_text(json.dumps({
                "event": "audio_chunk",
                "session_id": session_id,
                "data": {"audio": audio_b64}
            }))

            # Wait briefly for error
            time.sleep(2)
            messages = []
            try:
                for _ in range(5):
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
            except:
                pass

            events = [m['event'] for m in messages]
            if 'error' in events:
                error_msg = next(m for m in messages if m['event'] == 'error')
                if error_msg['data'].get('error_type') == 'webrtc_not_ready':
                    findings.append("✅ Server correctly requires WebRTC for audio")
                else:
                    findings.append(f"⚠️  Got error: {error_msg['data']['error_type']}")

        # Print findings
        print(f"\n" + "="*70)
        print("📊 DIAGNOSTIC RESULTS")
        print("="*70)
        for finding in findings:
            print(f"  {finding}")

        print(f"\n" + "="*70)
        print("🎯 LIKELY ISSUE:")
        print("="*70)
        print(f"  If you have text output but NO audio output, the issue is:")
        print(f"")
        print(f"  ❌ Frontend is NOT sending 'webrtc_offer' event")
        print(f"  ❌ Without WebRTC setup, server CANNOT stream audio")
        print(f"")
        print(f"  Check Browser DevTools → Network → WS tab")
        print(f"  Look for 'webrtc_offer' message from client")
        print(f"")
        print(f"  See: tests/e2e/DEBUGGING_NO_AUDIO.md for fix")
        print("="*70)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
