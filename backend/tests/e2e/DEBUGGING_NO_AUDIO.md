# Debugging: No Audio Output from Frontend

This guide helps diagnose why there's **text output but no audio output** from the voice agent.

## Problem Description

**Symptoms:**
- ✅ WebSocket connection works
- ✅ Audio input from user works
- ✅ ASR transcription works (you see transcript)
- ✅ Agent text response works (you see text response)
- ❌ **No TTS audio playback** (no sound from speakers)

## Root Cause Analysis

The issue is in the **TTS → WebRTC → Frontend** audio streaming pipeline.

## Step-by-Step Diagnosis

### Step 1: Check if WebRTC is Set Up on Frontend

**Problem**: Frontend is NOT sending WebRTC offer before audio streaming.

**How to Check**:

1. Open browser DevTools → Network → WS (WebSocket)
2. Look for messages sent by frontend
3. You should see this sequence:

```json
// Message 1: WebRTC Offer (REQUIRED)
{
  "event": "webrtc_offer",
  "session_id": "...",
  "data": {
    "sdp": "v=0\r\no=...",  // Long SDP string
    "type": "offer"
  }
}

// Message 2: Server responds with answer
{
  "event": "webrtc_answer",
  "data": {
    "sdp": "...",
    "type": "answer"
  }
}
```

**If you DON'T see `webrtc_offer`**:
- ❌ **Frontend is missing WebRTC setup code**
- The server CANNOT stream audio without WebRTC
- You will see this error in server response:

```json
{
  "event": "error",
  "data": {
    "error_type": "webrtc_not_ready",
    "message": "WebRTC audio channel not established"
  }
}
```

**Fix**: Add WebRTC setup code to frontend (see Frontend Fix section below)

---

### Step 2: Check Server Logs for Audio Streaming

**Look for these log patterns** (with your session ID):

#### 2.1 WebRTC Enabled Check

Search for: `webrtc_enabled=True`

```
📞 stream_tts_response: session=abc12345..., webrtc_enabled=True
```

**If you see `webrtc_enabled=False`**:
- ❌ WebRTC was never set up properly
- Check Step 1

---

#### 2.2 TTS Streaming Start

Search for: `Routing TTS to WebRTC`

```
📞 Routing TTS to WebRTC for session abc12345...
```

**If this message is MISSING**:
- ❌ `stream_tts_response` was never called
- Check if agent response was generated
- Check for errors before this point

---

#### 2.3 FFmpeg Process Start

Search for: `Starting FFmpeg input stream`

```
📥 Starting FFmpeg input stream for session abc12345...
```

**If this message is MISSING**:
- ❌ FFmpeg process failed to start
- Check if FFmpeg is installed: `which ffmpeg`
- Check for FFmpeg errors in logs

---

#### 2.4 MP3 Chunks from TTS

Search for: `FFmpeg input:`

```
📥 FFmpeg input: 45 MP3 chunks, 87234 bytes
```

**If this message is MISSING**:
- ❌ TTS provider (Edge TTS) failed to generate audio
- Check for TTS errors
- Check network connectivity to Microsoft Edge TTS service

---

#### 2.5 PCM Chunks to WebRTC

Search for: `PCM chunk #`

```
📤 PCM chunk #1 | Audio duration: 0.02s
📤 PCM chunk #50 | Audio duration: 1.00s
📤 PCM chunk #100 | Audio duration: 2.00s
```

**If these messages are MISSING**:
- ❌ FFmpeg conversion failed (MP3 → PCM)
- Check FFmpeg stderr logs
- Audio is NOT being sent to WebRTC track

---

#### 2.6 WebRTC Track Push

Search for: `CHECKPOINT 10: WebRTC track`

```
🔍 CHECKPOINT 10: WebRTC track - Pushed 50 chunks, queue size=12/50 (~0.24s buffered)
```

**If this message is MISSING**:
- ❌ Audio chunks are NOT being pushed to WebRTC track
- WebRTC manager's `push_audio_chunk` is not being called

---

#### 2.7 Streaming Complete

Search for: `streaming_complete`

```
✅ WebRTC TTS streaming complete for session abc12345...
```

**If this message is MISSING**:
- ❌ Streaming was interrupted or never completed
- Check for errors or interruptions

---

### Step 3: Check Frontend WebRTC Audio Reception

**On the frontend**, check if audio track is received:

```javascript
// In your WebRTC setup code
pc.ontrack = (event) => {
  console.log('🎵 Received track:', event.track.kind, event.track.id);

  if (event.track.kind === 'audio') {
    // Create audio element to play the track
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.play().catch(err => {
      console.error('❌ Failed to play audio:', err);
    });
  }
};
```

**Common Issues**:

1. **`ontrack` never fires**
   - WebRTC connection failed
   - Check ICE connection state
   - Check browser console for WebRTC errors

2. **`ontrack` fires but no audio playback**
   - Audio element autoplay blocked by browser
   - User interaction required before audio plays
   - Check browser audio permissions

3. **`ontrack` fires but track is muted/inactive**
   - Check `event.track.readyState` (should be "live")
   - Check `event.track.muted` (should be false)

---

### Step 4: Check Server Logs Pattern Summary

**Full successful audio streaming logs should look like this**:

```
# 1. WebRTC Setup
📞 stream_tts_response: session=abc12345..., webrtc_enabled=True

# 2. Start Streaming
📞 Routing TTS to WebRTC for session abc12345...

# 3. FFmpeg Start
📥 Starting FFmpeg input stream for session abc12345...

# 4. TTS Generation
🎵 Streaming TTS for session abc12345... (45 chars)
✅ Edge-TTS completed: 45 MP3 chunks generated

# 5. FFmpeg Conversion
📥 FFmpeg input: 45 MP3 chunks, 87234 bytes

# 6. PCM Streaming
📤 PCM chunk #1 | Audio duration: 0.02s
📤 PCM chunk #50 | Audio duration: 1.00s
📤 PCM chunk #100 | Audio duration: 2.00s
📤 FFmpeg output: 150 PCM chunks, 288000 bytes
📊 Total audio duration: 3.00s

# 7. WebRTC Track Push
🔍 CHECKPOINT 10: WebRTC track - Pushed 50 chunks, queue size=12/50
🔍 CHECKPOINT 10: WebRTC track - Pushed 100 chunks, queue size=25/50
🔍 CHECKPOINT 10: WebRTC track - Pushed 150 chunks, queue size=0/50

# 8. Completion
✅ WebRTC TTS streaming complete for session abc12345...
```

**If you see PARTIAL logs**:
- Find which step is missing
- That's where the issue is

---

## Frontend Fix: Add WebRTC Setup

If WebRTC is not set up, here's the minimal code needed:

```javascript
// 1. Create WebSocket connection
const ws = new WebSocket('ws://localhost:8000/ws?user_id=user123');

let pc = null;
let session_id = null;

// 2. On connection, receive session_id and ICE servers
ws.onmessage = async (event) => {
  const msg = JSON.parse(event.data);

  if (msg.event === 'connected') {
    session_id = msg.data.session_id;
    const iceServers = msg.data.ice_servers;

    console.log('✅ Connected:', session_id);

    // 3. CRITICAL: Set up WebRTC immediately
    await setupWebRTC(iceServers);
  }

  // Handle other events...
};

async function setupWebRTC(iceServers) {
  // Create peer connection with ICE servers
  pc = new RTCPeerConnection({
    iceServers: iceServers
  });

  // CRITICAL: Listen for audio track from server
  pc.ontrack = (event) => {
    console.log('🎵 Received audio track:', event.track.id);

    // Play the audio
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.autoplay = true;

    // Handle autoplay restriction
    audio.play().catch(err => {
      console.warn('⚠️ Autoplay blocked, waiting for user interaction...');
      // You may need to call audio.play() after a user click
    });
  };

  // Handle ICE candidates
  pc.onicecandidate = (event) => {
    if (event.candidate) {
      ws.send(JSON.dumps({
        event: 'webrtc_ice_candidate',
        session_id: session_id,
        data: {
          candidate: event.candidate.candidate,
          sdpMid: event.candidate.sdpMid,
          sdpMLineIndex: event.candidate.sdpMLineIndex
        }
      }));
    }
  };

  // Create offer
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  // Send offer to server
  ws.send(JSON.stringify({
    event: 'webrtc_offer',
    session_id: session_id,
    data: {
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type
    }
  }));

  console.log('📤 Sent WebRTC offer');
}

// Wait for answer from server
ws.onmessage = async (event) => {
  const msg = JSON.parse(event.data);

  if (msg.event === 'webrtc_answer') {
    console.log('📥 Received WebRTC answer');

    await pc.setRemoteDescription(
      new RTCSessionDescription({
        sdp: msg.data.sdp,
        type: msg.data.type
      })
    );

    console.log('✅ WebRTC setup complete!');
  }
};
```

---

## Quick Diagnostic Checklist

Run through this checklist:

- [ ] **Frontend sends `webrtc_offer` event**
  - Check: Browser DevTools → Network → WS tab

- [ ] **Server responds with `webrtc_answer` event**
  - Check: Browser DevTools → Network → WS tab

- [ ] **Frontend has `pc.ontrack` handler**
  - Check: Your frontend code

- [ ] **Server logs show `webrtc_enabled=True`**
  - Check: Server logs

- [ ] **Server logs show PCM chunks being sent**
  - Check: Server logs for "PCM chunk #"

- [ ] **Frontend `ontrack` event fires**
  - Check: Browser console logs

- [ ] **Audio element plays the stream**
  - Check: Browser audio output

---

## Test with Diagnostic Script

Run the diagnostic test:

```bash
# This test shows exactly what's happening
uv run pytest backend/tests/e2e/test_webrtc_audio_output.py -v -s
```

Look for:
- ✅ PASS = Audio streaming path is working
- ❌ FAIL = Shows exactly where it's failing

---

## Common Issues and Fixes

### Issue 1: "webrtc_not_ready" Error

**Symptom**: Error event with `error_type: "webrtc_not_ready"`

**Cause**: Frontend didn't send WebRTC offer

**Fix**: Add WebRTC setup code (see above)

---

### Issue 2: No Audio Playback Despite WebRTC Setup

**Symptom**: WebRTC connected, but no sound from speakers

**Possible Causes**:

1. **Browser autoplay blocking**
   - Fix: Require user click before playing audio

2. **Audio element not connected to stream**
   - Fix: Check `audio.srcObject = event.streams[0]`

3. **WebRTC track not received**
   - Fix: Add `pc.ontrack` handler

4. **Server not sending audio**
   - Fix: Check server logs (Step 2)

---

### Issue 3: FFmpeg Not Installed

**Symptom**: "FFmpeg not found" error in server logs

**Fix**:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get install ffmpeg

# Verify
ffmpeg -version
```

---

### Issue 4: Edge TTS Network Error

**Symptom**: "Edge-TTS failed: No audio was received"

**Possible Causes**:
1. Network connectivity issues
2. Microsoft service temporarily unavailable
3. Invalid voice name

**Fix**:
- Check internet connection
- Try different voice name
- Update edge-tts: `uv pip install --upgrade edge-tts`

---

## Summary: The Complete Flow

For audio to work, this MUST happen in order:

```
1. Frontend connects to WebSocket
   ↓
2. Frontend sends WebRTC offer ← CRITICAL!
   ↓
3. Server sends WebRTC answer
   ↓
4. Frontend sets remote description
   ↓
5. WebRTC connection established (webrtc_enabled = True)
   ↓
6. User sends audio
   ↓
7. Server generates agent response
   ↓
8. Server calls stream_tts_response()
   ↓
9. Server generates TTS audio (Edge TTS → MP3)
   ↓
10. Server converts MP3 → PCM (FFmpeg)
   ↓
11. Server pushes PCM to WebRTC track
   ↓
12. WebRTC sends audio to frontend
   ↓
13. Frontend ontrack event fires
   ↓
14. Frontend plays audio
   ↓
15. ✅ User hears audio!
```

**If ANY step fails, no audio will play.**

Use server logs to find which step is failing!
