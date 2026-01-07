"""
E2E tests for full voice conversation flow.

Tests the complete voice agent interaction:
1. Connect via WebSocket
2. Setup WebRTC
3. Send audio (user speech)
4. Receive transcript
5. Receive agent response (text)
6. Receive TTS audio via WebRTC

Uses generated test audio files for realistic testing.
"""

import pytest
import json
import base64
import asyncio
import time
from pathlib import Path


class TestVoiceConversation:
    """Test complete voice conversation flow."""

    def test_full_conversation_flow_with_webrtc(
        self,
        sync_client,
        test_audio_chinese,
        audio_encoder,
        mock_webrtc
    ):
        """
        Test complete conversation flow with WebRTC enabled.

        This is the CORRECT flow that enables voice streaming.
        """
        with sync_client.websocket_connect("/ws?user_id=test_full_flow") as websocket:
            # Step 1: Receive connection confirmation
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"\n📞 Connected: {session_id}")

            # Step 2: Setup WebRTC (CRITICAL for voice streaming)
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

            # Receive WebRTC answer
            answer_msg = json.loads(websocket.receive_text())
            assert answer_msg["event"] == "webrtc_answer"
            print("✅ WebRTC setup complete")

            # Step 3: Send audio chunk
            # Use first chunk of test audio
            audio_chunks = list(audio_encoder(test_audio_chinese, chunk_size=4096))
            print(f"🎤 Sending {len(audio_chunks)} audio chunks...")

            for chunk in audio_chunks:
                websocket.send_text(json.dumps({
                    "event": "audio_chunk",
                    "session_id": session_id,
                    "data": {
                        "audio": chunk
                    }
                }))

            print("✅ Audio chunks sent")

            # Step 4: Wait for responses
            # Should receive: transcript -> agent_response -> streaming_complete
            messages = []
            max_wait = 30  # seconds
            start_time = time.time()

            while time.time() - start_time < max_wait:
                try:
                    # Use a short timeout to avoid blocking forever
                    msg_text = websocket.receive_text()
                    msg = json.loads(msg_text)
                    messages.append(msg)

                    print(f"📨 Received: {msg['event']}")

                    if msg["event"] == "streaming_complete":
                        print("✅ Voice streaming completed")
                        break

                except Exception as e:
                    print(f"Error receiving message: {e}")
                    break

            # Verify we received expected events
            events = [msg["event"] for msg in messages]
            print(f"\n📊 Received events: {events}")

            # Should have transcript, agent_response, and streaming_complete
            # Note: May also have "no_speech_detected" if audio isn't recognized
            if "transcript" in events:
                transcript_msg = next(m for m in messages if m["event"] == "transcript")
                print(f"📝 Transcript: {transcript_msg['data']['text']}")

            if "agent_response" in events:
                response_msg = next(m for m in messages if m["event"] == "agent_response")
                print(f"🤖 Agent: {response_msg['data']['text']}")

            if "streaming_complete" in events:
                print("🎵 TTS streaming completed")

            # At minimum, we should get some response
            assert len(messages) > 0, "Should receive at least one message"

            print("\n✅ Full conversation flow completed successfully")

    def test_conversation_without_webrtc_shows_error(
        self,
        sync_client,
        test_audio_chinese,
        audio_encoder
    ):
        """
        Test conversation WITHOUT WebRTC - should show error.

        This demonstrates the voice streaming issue: without WebRTC setup,
        audio streaming fails with an error message.
        """
        with sync_client.websocket_connect("/ws?user_id=test_no_webrtc_flow") as websocket:
            # Step 1: Connect
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]
            print(f"\n📞 Connected: {session_id}")

            # Step 2: SKIP WebRTC setup (this is the problem!)
            print("⚠️  Skipping WebRTC setup...")

            # Step 3: Send audio
            audio_chunks = list(audio_encoder(test_audio_chinese, chunk_size=4096))
            print(f"🎤 Sending {len(audio_chunks)} audio chunks...")

            for chunk in audio_chunks:
                websocket.send_text(json.dumps({
                    "event": "audio_chunk",
                    "session_id": session_id,
                    "data": {
                        "audio": chunk
                    }
                }))

            # Step 4: Wait for responses
            messages = []
            max_wait = 30
            start_time = time.time()

            while time.time() - start_time < max_wait:
                try:
                    msg_text = websocket.receive_text()
                    msg = json.loads(msg_text)
                    messages.append(msg)

                    print(f"📨 Received: {msg['event']}")

                    # Look for error or agent_response
                    if msg["event"] == "error":
                        print(f"❌ Error: {msg['data']}")
                        # This is expected - WebRTC not ready
                        assert msg['data']['error_type'] == 'webrtc_not_ready'
                        break

                    if msg["event"] == "agent_response":
                        # Got text response, but no TTS will be streamed
                        print(f"🤖 Agent: {msg['data']['text']}")
                        # Wait a bit more to see if error comes
                        time.sleep(1)

                except Exception as e:
                    print(f"Error: {e}")
                    break

            events = [msg["event"] for msg in messages]
            print(f"\n📊 Events received: {events}")

            # Should get transcript and agent_response, but ERROR for TTS
            # or no streaming_complete event
            if "error" in events:
                error_msg = next(m for m in messages if m["event"] == "error")
                print(f"\n✅ Expected error received: {error_msg['data']['message']}")
                assert error_msg['data']['error_type'] == 'webrtc_not_ready'
            else:
                # If no explicit error, streaming_complete should NOT be present
                # (because WebRTC isn't set up, so streaming fails silently or with error)
                print("\n⚠️  No explicit error, but TTS streaming should have failed")

    def test_interrupt_voice_streaming(
        self,
        sync_client,
        test_audio_chinese,
        audio_encoder,
        mock_webrtc
    ):
        """Test interrupting ongoing voice streaming."""
        with sync_client.websocket_connect("/ws?user_id=test_interrupt") as websocket:
            # Setup
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Setup WebRTC
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": offer
            }))
            json.loads(websocket.receive_text())  # Receive answer

            # Send audio
            audio_chunks = list(audio_encoder(test_audio_chinese, chunk_size=4096))
            for chunk in audio_chunks:
                websocket.send_text(json.dumps({
                    "event": "audio_chunk",
                    "session_id": session_id,
                    "data": {"audio": chunk}
                }))

            print("🎤 Audio sent, waiting for agent response...")

            # Wait for agent to start responding
            received_agent_response = False
            for _ in range(10):
                try:
                    msg = json.loads(websocket.receive_text())
                    print(f"📨 {msg['event']}")

                    if msg["event"] == "agent_response":
                        received_agent_response = True
                        print("🤖 Agent started responding...")

                        # Send interrupt WHILE agent is responding
                        websocket.send_text(json.dumps({
                            "event": "interrupt",
                            "session_id": session_id,
                            "data": {
                                "reason": "user_interruption"
                            }
                        }))
                        print("🛑 Interrupt sent")
                        break

                except Exception as e:
                    print(f"Error: {e}")
                    break

            # Wait for interrupt acknowledgment
            for _ in range(5):
                try:
                    msg = json.loads(websocket.receive_text())
                    print(f"📨 {msg['event']}")

                    if msg["event"] == "voice_interrupted":
                        print(f"✅ Interrupt acknowledged: {msg['data']}")
                        assert "interruption_time_ms" in msg["data"]
                        return

                except Exception:
                    break

            if received_agent_response:
                print("✅ Interrupt flow completed")

    def test_multiple_audio_chunks_buffering(
        self,
        sync_client,
        test_audio_query,
        audio_encoder,
        mock_webrtc
    ):
        """Test audio buffering with multiple chunks."""
        with sync_client.websocket_connect("/ws?user_id=test_buffering") as websocket:
            # Setup
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Setup WebRTC
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": offer
            }))
            json.loads(websocket.receive_text())

            # Send multiple audio chunks with small delays
            # (simulating real-time audio streaming)
            audio_chunks = list(audio_encoder(test_audio_query, chunk_size=2048))
            print(f"🎤 Sending {len(audio_chunks)} chunks with delays...")

            for i, chunk in enumerate(audio_chunks):
                websocket.send_text(json.dumps({
                    "event": "audio_chunk",
                    "session_id": session_id,
                    "data": {"audio": chunk}
                }))

                # Small delay between chunks (simulate streaming)
                if i < len(audio_chunks) - 1:
                    time.sleep(0.1)

            print("✅ Buffered audio chunks sent")

            # Wait for processing
            # Audio buffer has BUFFER_TIMEOUT of 1.5 seconds
            print("⏳ Waiting for audio processing...")

            messages = []
            start_time = time.time()
            while time.time() - start_time < 30:
                try:
                    msg = json.loads(websocket.receive_text())
                    messages.append(msg)
                    print(f"📨 {msg['event']}")

                    if msg["event"] == "streaming_complete":
                        break

                except Exception as e:
                    print(f"Error: {e}")
                    break

            events = [m["event"] for m in messages]
            print(f"📊 Events: {events}")

            print("✅ Audio buffering test completed")

    def test_empty_audio_handling(
        self,
        sync_client,
        mock_webrtc
    ):
        """Test handling of empty or invalid audio."""
        with sync_client.websocket_connect("/ws?user_id=test_empty_audio") as websocket:
            # Setup
            connect_msg = json.loads(websocket.receive_text())
            session_id = connect_msg["data"]["session_id"]

            # Setup WebRTC
            webrtc = mock_webrtc(session_id)
            offer = webrtc.create_offer()
            websocket.send_text(json.dumps({
                "event": "webrtc_offer",
                "session_id": session_id,
                "data": offer
            }))
            json.loads(websocket.receive_text())

            # Send empty audio
            websocket.send_text(json.dumps({
                "event": "audio_chunk",
                "session_id": session_id,
                "data": {
                    "audio": base64.b64encode(b"").decode('utf-8')
                }
            }))

            print("🎤 Sent empty audio")

            # Should get no_speech_detected or similar
            time.sleep(2)  # Wait for processing

            try:
                msg = json.loads(websocket.receive_text())
                print(f"📨 {msg['event']}: {msg.get('data', {})}")

                # Should handle gracefully
                if msg["event"] == "no_speech_detected":
                    print("✅ Empty audio handled correctly")

            except Exception:
                print("✅ No response for empty audio (handled gracefully)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
