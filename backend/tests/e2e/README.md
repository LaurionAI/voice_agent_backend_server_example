# E2E Tests for Voice Agent Backend

Comprehensive end-to-end tests for the voice agent backend server.

## Overview

These tests cover the complete voice conversation flow:

1. **WebSocket Connection** (`test_websocket_connection.py`)
   - Connection establishment
   - Heartbeat mechanism
   - Session management
   - Multiple simultaneous connections
   - Error handling

2. **WebRTC Setup** (`test_webrtc_setup.py`)
   - Offer/Answer exchange
   - ICE candidate handling
   - Connection negotiation
   - Invalid input handling

3. **Voice Conversation** (`test_voice_conversation.py`)
   - Complete conversation flow with WebRTC
   - Audio chunk sending and buffering
   - Transcript reception
   - Agent response reception
   - TTS audio streaming
   - Interruption handling
   - Edge cases (empty audio, etc.)

## Test Fixtures

### Generated Audio Files

Test audio files are located in `fixtures/`:

- `test_hello_chinese.mp3` - Chinese greeting
- `test_hello_english.mp3` - English greeting
- `test_query_schedule.mp3` - Chinese schedule query
- `test_weather_query.mp3` - English weather query
- `test_thank_you.mp3` - Chinese thank you

Metadata: `fixtures/audio_metadata.json`

### Generating Test Audio

To regenerate test audio files:

```bash
uv run python backend/tests/e2e/generate_test_audio.py
```

## Running Tests

### Run All E2E Tests

```bash
# From project root
uv run pytest backend/tests/e2e/ -v -s

# Or with coverage
uv run pytest backend/tests/e2e/ -v -s --cov=backend
```

### Run Specific Test File

```bash
# WebSocket connection tests
uv run pytest backend/tests/e2e/test_websocket_connection.py -v -s

# WebRTC setup tests
uv run pytest backend/tests/e2e/test_webrtc_setup.py -v -s

# Voice conversation tests
uv run pytest backend/tests/e2e/test_voice_conversation.py -v -s
```

### Run Specific Test

```bash
uv run pytest backend/tests/e2e/test_voice_conversation.py::TestVoiceConversation::test_full_conversation_flow_with_webrtc -v -s
```

## Test Architecture

### Fixtures (`conftest.py`)

- `app` - FastAPI application instance
- `client` - Async HTTP client
- `sync_client` - Synchronous test client for WebSocket
- `test_audio_*` - Preloaded test audio files
- `mock_webrtc` - Mock WebRTC connection
- `audio_encoder` - Audio chunk encoder
- `sample_websocket_message` - WebSocket message factory

### Mock Components

#### MockWebRTCConnection

Simulates WebRTC peer connection:
- Creates SDP offers
- Sets remote descriptions
- Handles ICE candidates
- Receives audio chunks

## Key Findings

### Voice Streaming Issue

**Problem**: Voice streaming requires WebRTC to be set up BEFORE the server attempts to stream TTS audio.

**Root Cause**: In `voice_session_manager.py:612-625`, the `stream_tts_response` method checks if `webrtc_enabled` is True. This flag is only set after a successful WebRTC offer/answer exchange (line 417).

**Solution**: Clients MUST:
1. Connect via WebSocket
2. Send `webrtc_offer` event
3. Receive and handle `webrtc_answer`
4. THEN send audio

**Test Demonstration**:
- `test_full_conversation_flow_with_webrtc` - Shows CORRECT flow ✅
- `test_conversation_without_webrtc_shows_error` - Shows INCORRECT flow ❌

## Test Coverage

- ✅ WebSocket connection lifecycle
- ✅ WebRTC negotiation
- ✅ Audio chunk buffering (1.5s timeout)
- ✅ ASR transcription
- ✅ Agent response
- ✅ TTS streaming via WebRTC
- ✅ Interruption handling
- ✅ Error handling (invalid messages, missing WebRTC, etc.)
- ✅ Multiple simultaneous connections
- ✅ Edge cases (empty audio, invalid JSON, etc.)

## Dependencies

Required packages (from `pyproject.toml`):
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `httpx` - HTTP client
- `fastapi` - Web framework
- `edge-tts` - TTS provider (for audio generation)
- `websockets` - WebSocket support

## CI/CD Integration

Add to your CI pipeline:

```yaml
# .github/workflows/test.yml
- name: Run E2E Tests
  run: |
    uv sync
    uv run pytest backend/tests/e2e/ -v --cov=backend --cov-report=xml
```

## Debugging

### Enable Verbose Logging

```bash
# Run with pytest logging
uv run pytest backend/tests/e2e/ -v -s --log-cli-level=DEBUG

# Run with full output
uv run pytest backend/tests/e2e/ -v -s --tb=long
```

### Inspect WebSocket Messages

All received messages are printed during test execution with `-s` flag.

### Check Test Audio

Play generated audio files to verify quality:

```bash
# macOS
afplay backend/tests/e2e/fixtures/test_hello_chinese.mp3

# Linux
mpg123 backend/tests/e2e/fixtures/test_hello_chinese.mp3
```

## Common Issues

### 1. Tests Timeout

**Cause**: Server not responding or slow ASR/TTS
**Solution**: Increase `max_wait` in test, check server logs

### 2. WebRTC Answer Not Received

**Cause**: Invalid SDP format
**Solution**: Check WebRTC manager implementation

### 3. No Speech Detected

**Cause**: Audio validation failing, VAD threshold too high
**Solution**: Adjust `speech_ratio_threshold` in audio validator

### 4. Import Errors

**Cause**: Missing dependencies
**Solution**: Run `uv sync` to install all dependencies

## Future Improvements

- [ ] Add performance benchmarks
- [ ] Test with real WebRTC (not just mock)
- [ ] Test audio quality metrics
- [ ] Load testing with multiple concurrent users
- [ ] Integration with real ASR service
- [ ] Record and replay real user sessions

## Contributing

When adding new tests:

1. Follow existing test structure
2. Use descriptive test names
3. Add docstrings explaining what's being tested
4. Update this README with new test coverage
5. Ensure tests are idempotent and can run in any order
