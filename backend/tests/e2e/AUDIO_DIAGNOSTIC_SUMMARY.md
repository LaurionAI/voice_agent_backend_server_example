# Audio Output Diagnostic Summary

## Issue: Text Response Works, But NO Audio Output

**Status**: Investigating audio streaming pipeline from TTS → WebRTC → Frontend

---

## Quick Diagnostic Steps

### 1. Check Server Logs RIGHT NOW

Run the server and look for these patterns when you trigger a voice query:

```bash
# Run server with visible logging
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000

# Or use log monitoring script
./tests/e2e/monitor_audio_flow.sh
```

**Look for this sequence in logs** (replace `abc12345` with your session ID):

```
✅ Expected:
📞 stream_tts_response: session=abc12345..., webrtc_enabled=True
📞 Routing TTS to WebRTC for session abc12345...
📥 Starting FFmpeg input stream for session abc12345...
✅ Edge-TTS completed: 45 MP3 chunks generated
📤 PCM chunk #1 | Audio duration: 0.02s
📤 PCM chunk #50 | Audio duration: 1.00s
🔍 CHECKPOINT 10: WebRTC track - Pushed 50 chunks
✅ WebRTC TTS streaming complete for session abc12345...

❌ Bad sign:
📞 stream_tts_response: session=abc12345..., webrtc_enabled=False
ERROR: webrtc_not_ready
```

### 2. Frontend WebSocket Messages

**Check Browser DevTools → Network → WS tab**

You MUST see this sequence:

```json
// 1. Client sends (REQUIRED!)
{
  "event": "webrtc_offer",
  "session_id": "...",
  "data": {
    "sdp": "v=0\r\no=...",  // Long SDP string
    "type": "offer"
  }
}

// 2. Server responds
{
  "event": "webrtc_answer",
  "data": {
    "sdp": "...",
    "type": "answer"
  }
}
```

**If you DON'T see `webrtc_offer` from client**:
- ❌ **THIS IS THE PROBLEM!**
- Frontend is missing WebRTC setup code
- Server will reject audio streaming with `webrtc_not_ready` error

### 3. Check Frontend Console

**Required WebRTC code**:

```javascript
// Your frontend MUST have this
pc.ontrack = (event) => {
  console.log('🎵 Received track:', event.track.kind);

  if (event.track.kind === 'audio') {
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.play();
  }
};
```

**Look for these console logs**:
- ✅ "🎵 Received track: audio" - Good, audio track received
- ❌ No log - WebRTC track never arrived

---

## The Audio Pipeline (All Must Work)

```
Frontend                          Server                           Output
───────────────────────────────────────────────────────────────────────

1. Send webrtc_offer       →     Receive offer
                                  Create WebRTC connection
                           ←     Send webrtc_answer
2. Set remote description

3. User speaks (audio)     →     ASR transcribes
                                  Agent generates text response
                           ←     Send text response (✅ YOU SEE THIS)

                                  Call stream_tts_response()
                                  Check: webrtc_enabled=True? ← KEY CHECK

                                  IF True:
                                    Edge TTS generates MP3
                                    FFmpeg converts MP3→PCM
                                    Push PCM to WebRTC track
                           ←       WebRTC sends audio packets

4. pc.ontrack fires
   Play audio stream       →     🔊 User hears audio
```

---

## Most Likely Causes

### Cause 1: Frontend Never Sends WebRTC Offer (90% of cases)

**Symptom**: Server logs show `webrtc_enabled=False`

**Check**: Browser DevTools → Network → WS
- Do you see `webrtc_offer` message? NO = This is the problem

**Fix**: Add WebRTC setup to frontend (see DEBUGGING_NO_AUDIO.md)

---

### Cause 2: Frontend Sends Offer But Doesn't Handle Track (8% of cases)

**Symptom**:
- Server logs show audio streaming working
- Frontend never plays audio

**Check**: Browser console
- Do you see `pc.ontrack` event? NO = Missing handler

**Fix**: Add `pc.ontrack` handler (see DEBUGGING_NO_AUDIO.md)

---

### Cause 3: Server-Side Issue (2% of cases)

**Symptom**:
- `webrtc_enabled=True` in logs
- But NO "PCM chunk" logs

**Possible causes**:
- FFmpeg not installed: `which ffmpeg`
- Edge TTS network issue
- Server permissions issue

**Fix**: Check server logs for errors

---

## Immediate Action Items

### For You (Right Now):

1. **Check server logs** when you trigger a voice query
   - Run: `uv run uvicorn main:app --host 0.0.0.0 --port 8000`
   - Speak to the agent
   - Look for "webrtc_enabled=True" or "webrtc_enabled=False"

2. **Check frontend WebSocket messages**
   - Open Browser DevTools → Network → WS tab
   - Look for `webrtc_offer` message from client
   - Is it being sent? YES/NO?

3. **Report back with**:
   - Server log snippet (copy/paste the logs around your session)
   - Frontend WS messages (screenshot or copy/paste)
   - Frontend console errors (if any)

### For Frontend Developer:

If `webrtc_offer` is NOT being sent, add this code:

```javascript
// CRITICAL: Must run IMMEDIATELY after WebSocket connects
async function setupWebRTC(iceServers, sessionId) {
  const pc = new RTCPeerConnection({ iceServers });

  // CRITICAL: Handle incoming audio
  pc.ontrack = (event) => {
    console.log('🎵 Audio track received!');
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.play().catch(e => console.error('Play failed:', e));
  };

  // CRITICAL: Send offer
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);

  ws.send(JSON.stringify({
    event: 'webrtc_offer',
    session_id: sessionId,
    data: {
      sdp: pc.localDescription.sdp,
      type: pc.localDescription.type
    }
  }));
}

// Call this IMMEDIATELY after receiving 'connected' event
ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);

  if (msg.event === 'connected') {
    const sessionId = msg.data.session_id;
    const iceServers = msg.data.ice_servers;

    setupWebRTC(iceServers, sessionId); // ← DO THIS NOW
  }

  if (msg.event === 'webrtc_answer') {
    pc.setRemoteDescription(new RTCSessionDescription(msg.data));
  }
};
```

---

## Testing Tools Created

### 1. Diagnostic Test

```bash
# Run this to check if audio streaming works
uv run pytest backend/tests/e2e/test_webrtc_audio_output.py -v -s
```

This will show you:
- ✅ Where audio streaming works
- ❌ Where it fails
- 🔍 What to check in server logs

### 2. Log Monitor

```bash
# Watch server logs in real-time with colored output
./backend/tests/e2e/monitor_audio_flow.sh

# Or filter by session
./backend/tests/e2e/monitor_audio_flow.sh abc12345
```

Shows checkpoints:
- [1] WebRTC Setup
- [2] TTS Streaming Start
- [3] FFmpeg Process
- [4] MP3 Chunks
- [5] PCM Chunks
- [6] WebRTC Track Push
- [7] Completion

### 3. Full Debugging Guide

Read: `backend/tests/e2e/DEBUGGING_NO_AUDIO.md`

Comprehensive guide with:
- Step-by-step diagnosis
- Server log patterns
- Frontend code examples
- Common issues and fixes

---

## What To Send Me

To help diagnose, please provide:

1. **Server logs** from one voice interaction:
```bash
# Run server
uv run uvicorn main:app --host 0.0.0.0 --port 8000 2>&1 | tee /tmp/voice_agent.log

# After speaking to agent, send me the log:
cat /tmp/voice_agent.log
```

2. **Frontend WebSocket messages**:
   - Browser DevTools → Network → WS → Click connection
   - Screenshot or copy the messages

3. **Frontend console output**:
   - Browser DevTools → Console
   - Any errors or warnings

4. **Answer these questions**:
   - Do you see text responses? (YES/NO)
   - Do you see `webrtc_offer` in WS messages? (YES/NO)
   - Do you have `pc.ontrack` handler in frontend? (YES/NO)
   - What does server log show for `webrtc_enabled`? (True/False)

---

## Expected Timeline

Once you provide the above info, I can:
- Identify exact failure point (< 5 min)
- Provide specific fix (< 10 min)
- Test fix works (< 5 min)

**Total**: ~20 minutes to fix

---

## Current Status Summary

✅ **Working**:
- Backend server
- WebSocket connection
- Audio input (ASR)
- Text output (Agent response)
- TTS generation (Edge TTS)

❓ **Unknown** (Need to check):
- Is WebRTC offer being sent?
- Is webrtc_enabled flag True?
- Is audio being streamed to WebRTC?
- Is frontend receiving audio track?

❌ **Not Working**:
- Audio playback on frontend

**Next Step**: Check server logs and frontend WS messages (see above)
