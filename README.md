# Voice Agent Backend Server

Use this server to add realtime voice conversations with AI agents to your application. By connecting via WebSocket and WebRTC, you can quickly build voice-enabled applications such as AI assistants, voice chatbots, or interactive voice interfaces with just a few lines of code.

## Installation

Install dependencies using `uv`:

```bash
uv sync
```

Set up environment variables in `.env`:

```bash
ZHIPUAI_API_KEY=your_api_key_here  # For GLM-4.5-air agent
```

## Usage

Start the server:

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

The server exposes a WebSocket endpoint at `ws://localhost:8000/ws` for voice streaming and a REST API at `http://localhost:8000` for health checks.

## Examples

### Connecting to the server

```python
import asyncio
import websockets
import json

async def connect():
    uri = "ws://localhost:8000/ws?user_id=user123"
    async with websockets.connect(uri) as ws:
        # Receive connection confirmation
        message = await ws.recv()
        data = json.loads(message)
        print(f"Connected! Session: {data['data']['session_id']}")
        
        # Setup WebRTC with provided ICE servers
        ice_servers = data['data']['ice_servers']
        # ... setup WebRTC peer connection ...

asyncio.run(connect())
```

### Sending audio for transcription

```python
import base64

# Send audio chunk
audio_bytes = b"..."  # Your audio data
audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

await ws.send(json.dumps({
    "event": "audio_chunk",
    "data": {
        "audio": audio_b64
    }
}))

# Receive transcript
message = await ws.recv()
data = json.loads(message)
if data['event'] == 'transcript':
    print(f"User said: {data['data']['text']}")
```

### Receiving agent responses

```python
# Listen for agent responses
async for message in ws:
    data = json.loads(message)
    
    if data['event'] == 'agent_response':
        print(f"Agent: {data['data']['text']}")
    
    elif data['event'] == 'streaming_complete':
        print("Audio streaming finished")
```

### Setting up WebRTC for audio streaming

```python
# After receiving 'connected' event with ICE servers
ice_servers = data['data']['ice_servers']

# Create peer connection
pc = RTCPeerConnection()
for server in ice_servers:
    pc.addIceServer(server)

# Create offer
offer = await pc.createOffer()
await pc.setLocalDescription(offer)

# Send offer to server
await ws.send(json.dumps({
    "event": "webrtc_offer",
    "data": {
        "sdp": pc.localDescription.sdp,
        "type": pc.localDescription.type
    }
}))

# Receive answer
message = await ws.recv()
data = json.loads(message)
if data['event'] == 'webrtc_answer':
    await pc.setRemoteDescription(
        RTCSessionDescription(
            sdp=data['data']['sdp'],
            type=data['data']['type']
        )
    )
```

### Interrupting the agent

```python
# Interrupt ongoing agent response
await ws.send(json.dumps({
    "event": "interrupt",
    "data": {
        "reason": "user_interruption"
    }
}))
```

## WebSocket Events

**Client → Server:**
- `audio_chunk` - Send audio data for transcription
- `webrtc_offer` - WebRTC SDP offer for audio streaming
- `webrtc_ice_candidate` - WebRTC ICE candidate
- `interrupt` - Interrupt ongoing agent response
- `heartbeat` - Keep connection alive

**Server → Client:**
- `connected` - Connection established (includes session_id and ICE servers)
- `transcript` - Speech-to-text result
- `agent_response` - Agent's text response
- `webrtc_answer` - WebRTC SDP answer
- `voice_interrupted` - Interruption acknowledged
- `streaming_complete` - TTS streaming finished

## HTTP Endpoints

**`GET /`** - Service info
```json
{
  "service": "Voice Agent Demo",
  "status": "running",
  "version": "1.0.0"
}
```

**`GET /health`** - Health check
```json
{
  "status": "healthy",
  "active_sessions": 2,
  "components": {
    "tts": true,
    "asr": true,
    "webrtc": true,
    "agent": true
  }
}
```

## Configuration

### TTS Provider

Change TTS voice in `main.py`:

```python
tts_config = TTSConfig(
    voice="zh-CN-XiaoxiaoNeural",  # Chinese female voice
    rate="+0%"
)
tts_provider = get_tts_provider("edge-tts", tts_config)
```

### ASR Processor

Change ASR model in `main.py`:

```python
asr_processor = HFSpaceASR(space_name="hz6666/SenseVoiceSmall")
```

### Agent Model

Configure LLM in `main.py`:

```python
agent = SimpleAgent(model="glm-4.5-air", temperature=0.7)
```

## Deployment

Deploy to Render using the provided `render.yaml` configuration:

```bash
# The server will automatically deploy on push to main branch
# Make sure to set environment variables in Render dashboard:
# - ZHIPUAI_API_KEY
# - OPENAI_API_KEY (optional)
# - HF_TOKEN (optional)
```

For local production deployment:

```bash
uvicorn main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 4 \
  --log-level info
```

## Architecture

The server uses a framework-first design:

- **Framework** (`lib/voice_streaming_framework/`) - Reusable WebRTC, WebSocket, and audio handling
- **Application** (`app/voice_agent/`) - Business logic, agent, and integrations

This separation allows you to reuse the framework across different projects while customizing the application logic per use case.
