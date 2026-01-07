# How To Fix: No Audio Output (Text Works, Audio Doesn't)

## Quick Answer

**Most likely cause**: Frontend is NOT sending WebRTC offer before audio streaming.

## How To Diagnose (2 minutes)

### Step 1: Run Server with Logging

```bash
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

### Step 2: Trigger a Voice Query

Speak to the agent through your frontend.

### Step 3: Check Server Logs

Look for this line (replace `abc12345` with your actual session ID):

```
📞 stream_tts_response: session=abc12345..., webrtc_enabled=True
```

**If you see `webrtc_enabled=False`**:
- ❌ **This is the problem!**
- Frontend didn't set up WebRTC
- Go to "The Fix" section below

**If you see `webrtc_enabled=True`**:
- Look for "PCM chunk #" in logs
- If missing: Server-side audio streaming issue
- See "Advanced Debugging" section

### Step 4: Check Browser DevTools

1. Open Browser DevTools → Network tab → WS (WebSocket)
2. Click on the WebSocket connection
3. Look at "Messages" tab

**You MUST see this message FROM CLIENT**:
```json
{
  "event": "webrtc_offer",
  "session_id": "...",
  "data": {
    "sdp": "v=0\r\no=...",  // Long string starting with v=0
    "type": "offer"
  }
}
```

**If you DON'T see `webrtc_offer` from client**:
- ❌ **This confirms the problem!**
- Frontend is missing WebRTC setup
- Go to "The Fix" section below

## The Fix

Add this code to your frontend (JavaScript):

```javascript
// ========================================
// CRITICAL: WebRTC Setup for Audio Output
// ========================================

let pc = null;  // RTCPeerConnection
let ws = null;  // WebSocket
let sessionId = null;

// 1. Connect to WebSocket
ws = new WebSocket('ws://localhost:8000/ws?user_id=user123');

ws.onmessage = async (event) => {
  const msg = JSON.parse(event.data);

  // 2. When connected, IMMEDIATELY set up WebRTC
  if (msg.event === 'connected') {
    sessionId = msg.data.session_id;
    const iceServers = msg.data.ice_servers;

    console.log('✅ Connected:', sessionId);

    // CRITICAL: Setup WebRTC NOW
    await setupWebRTC(iceServers);
  }

  // 3. Handle WebRTC answer from server
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

  // Handle other events (transcript, agent_response, etc.)
  // ...
};

async function setupWebRTC(iceServers) {
  // Create peer connection
  pc = new RTCPeerConnection({
    iceServers: iceServers
  });

  // CRITICAL: Listen for audio track from server
  pc.ontrack = (event) => {
    console.log('🎵 Received audio track!');

    // Create audio element and play
    const audio = new Audio();
    audio.srcObject = event.streams[0];
    audio.autoplay = true;

    // Handle autoplay blocking
    audio.play().catch(err => {
      console.warn('⚠️ Autoplay blocked:', err);
      console.warn('User interaction required to play audio');

      // You may need to call audio.play() after user clicks something
      document.addEventListener('click', () => {
        audio.play();
      }, { once: true });
    });
  };

  // Handle ICE candidates
  pc.onicecandidate = (event) => {
    if (event.candidate) {
      ws.send(JSON.stringify({
        event: 'webrtc_ice_candidate',
        session_id: sessionId,
        data: {
          candidate: event.candidate.candidate,
          sdpMid: event.candidate.sdpMid,
          sdpMLineIndex: event.candidate.sdpMLineIndex
        }
      }));
    }
  };

  // Create and send offer
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

  console.log('📤 Sent WebRTC offer');
}
```

## Verify the Fix

After adding the code:

1. **Check Browser Console**:
```
✅ Connected: abc12345-...
📤 Sent WebRTC offer
📥 Received WebRTC answer
✅ WebRTC setup complete!
🎵 Received audio track!
```

2. **Check Browser DevTools → Network → WS**:
   - Should now see `webrtc_offer` message

3. **Check Server Logs**:
```
📞 stream_tts_response: session=abc12345..., webrtc_enabled=True
📞 Routing TTS to WebRTC for session abc12345...
📤 PCM chunk #1 | Audio duration: 0.02s
✅ WebRTC TTS streaming complete
```

4. **Test**:
   - Speak to the agent
   - You should now HEAR audio response!

## Common Issues After Fix

### Issue: Audio plays but cuts off

**Cause**: Browser autoplay blocking

**Fix**: Require user interaction first:
```javascript
// Require user click before enabling audio
document.getElementById('start-button').addEventListener('click', async () => {
  await setupWebRTC(iceServers);
});
```

### Issue: No audio track received

**Cause**: WebRTC connection failed

**Fix**: Check browser console for WebRTC errors
- Check ICE connection state
- Verify firewall isn't blocking WebRTC

### Issue: Track received but no sound

**Cause**: Audio element not playing

**Fix**:
```javascript
pc.ontrack = (event) => {
  const audio = new Audio();
  audio.srcObject = event.streams[0];

  // Debug
  console.log('Track state:', event.track.readyState);  // Should be "live"
  console.log('Track muted:', event.track.muted);  // Should be false

  // Try to play
  audio.play()
    .then(() => console.log('✅ Playing'))
    .catch(err => console.error('❌ Play failed:', err));
};
```

## Testing

Run these tests to verify server is working:

```bash
# Simple diagnostics (fast)
uv run pytest backend/tests/e2e/test_simple_diagnostics.py -v -s

# WebSocket connection tests
uv run pytest backend/tests/e2e/test_websocket_connection.py -v -s

# All E2E tests
uv run pytest backend/tests/e2e/ -v
```

## Complete Flow (What Should Happen)

```
1. Frontend connects to WebSocket
   ↓
2. Server sends 'connected' with session_id and ice_servers
   ↓
3. Frontend IMMEDIATELY calls setupWebRTC()
   ↓
4. Frontend sends 'webrtc_offer' to server
   ↓
5. Server processes offer and sends 'webrtc_answer'
   ↓
6. Frontend sets remote description
   ↓
7. ✅ WebRTC connection established (webrtc_enabled = True)
   ↓
8. User speaks
   ↓
9. Server transcribes and generates text response
   ↓
10. Server calls stream_tts_response()
   ↓
11. Server generates TTS audio (Edge TTS)
   ↓
12. Server converts to PCM and sends via WebRTC
   ↓
13. Frontend pc.ontrack fires with audio
   ↓
14. Frontend plays audio
   ↓
15. 🔊 User hears the response!
```

## Need More Help?

See detailed debugging guide: [DEBUGGING_NO_AUDIO.md](DEBUGGING_NO_AUDIO.md)

Run diagnostic summary: [AUDIO_DIAGNOSTIC_SUMMARY.md](AUDIO_DIAGNOSTIC_SUMMARY.md)

## Summary

- **Problem**: No WebRTC setup = No audio output
- **Solution**: Add WebRTC setup code (see above)
- **Verify**: Check logs for `webrtc_enabled=True`
- **Test**: Speak and listen for audio response

**Time to fix**: ~10 minutes to add code and test
