"""
Pytest fixtures for E2E tests.

Provides common test fixtures including:
- FastAPI test client
- WebSocket test client
- Mock WebRTC connections
- Test audio data
"""

import pytest
import json
import base64
from pathlib import Path
from typing import AsyncGenerator
from fastapi.testclient import TestClient
from httpx import AsyncClient
import asyncio


@pytest.fixture(scope="session")
def fixtures_dir():
    """Get fixtures directory path."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def audio_metadata(fixtures_dir):
    """Load audio metadata."""
    metadata_path = fixtures_dir / "audio_metadata.json"
    with open(metadata_path, 'r', encoding='utf-8') as f:
        return json.load(f)


@pytest.fixture
def test_audio_chinese(fixtures_dir):
    """Load Chinese test audio."""
    audio_path = fixtures_dir / "test_hello_chinese.mp3"
    with open(audio_path, 'rb') as f:
        return f.read()


@pytest.fixture
def test_audio_english(fixtures_dir):
    """Load English test audio."""
    audio_path = fixtures_dir / "test_hello_english.mp3"
    with open(audio_path, 'rb') as f:
        return f.read()


@pytest.fixture
def test_audio_query(fixtures_dir):
    """Load query test audio."""
    audio_path = fixtures_dir / "test_query_schedule.mp3"
    with open(audio_path, 'rb') as f:
        return f.read()


@pytest.fixture(scope="module")
def app():
    """Get FastAPI app instance."""
    # Import here to avoid circular imports
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))

    from main import app
    return app


@pytest.fixture
def sync_client(app):
    """Create synchronous test client for WebSocket testing."""
    with TestClient(app) as client:
        yield client


class MockWebRTCConnection:
    """Mock WebRTC connection for testing."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.local_description = None
        self.remote_description = None
        self.ice_candidates = []
        self.audio_chunks = []

    def create_offer(self):
        """Create mock WebRTC offer."""
        return {
            "sdp": f"mock-sdp-offer-{self.session_id}",
            "type": "offer"
        }

    def set_remote_description(self, sdp: str, type: str):
        """Set remote description."""
        self.remote_description = {"sdp": sdp, "type": type}

    def add_ice_candidate(self, candidate: dict):
        """Add ICE candidate."""
        self.ice_candidates.append(candidate)

    def receive_audio_chunk(self, chunk: bytes):
        """Receive audio chunk (for mock playback)."""
        self.audio_chunks.append(chunk)


@pytest.fixture
def mock_webrtc():
    """Create mock WebRTC connection."""
    def _create_mock(session_id: str):
        return MockWebRTCConnection(session_id)
    return _create_mock


def encode_audio_chunk(audio_data: bytes, chunk_size: int = 4096):
    """
    Split audio into chunks and encode as base64.

    Args:
        audio_data: Raw audio bytes
        chunk_size: Size of each chunk

    Yields:
        Base64 encoded audio chunks
    """
    for i in range(0, len(audio_data), chunk_size):
        chunk = audio_data[i:i + chunk_size]
        yield base64.b64encode(chunk).decode('utf-8')


@pytest.fixture
def audio_encoder():
    """Get audio encoder function."""
    return encode_audio_chunk


@pytest.fixture
def sample_websocket_message():
    """Create sample WebSocket message."""
    def _create_message(event: str, data: dict, session_id: str = None):
        message = {
            "event": event,
            "data": data
        }
        if session_id:
            message["session_id"] = session_id
        return json.dumps(message)
    return _create_message
