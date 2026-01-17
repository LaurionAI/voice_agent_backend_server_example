
import logging
import uuid
import json
import asyncio
from typing import Dict, Optional, Any
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, RTCIceCandidate
from .tracks import TTSAudioTrack

logger = logging.getLogger("webrtc.manager")

class WebRTCManager:
    """
    Manages WebRTC connections and tracks for voice streaming.
    """
    def __init__(self):
        self.pcs: Dict[str, RTCPeerConnection] = {}
        self.tracks: Dict[str, TTSAudioTrack] = {}
        self.senders: Dict[str, Any] = {}

        # Track ready events for each session (prevents race condition)
        self.track_ready_events: Dict[str, asyncio.Event] = {}

        # Default STUN servers (will be overridden if Metered.ca is used)
        self.default_rtc_config = RTCConfiguration(iceServers=[
            RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            RTCIceServer(urls=["stun:stun1.l.google.com:19302"])
        ])

    async def create_peer_connection(self, session_id: str, ice_servers: Optional[list] = None) -> RTCPeerConnection:
        """Create a new RTCPeerConnection for a session."""
        if session_id in self.pcs:
            await self.close_peer_connection(session_id)

        # Use custom ICE servers if provided, otherwise default to STUN
        if ice_servers:
            # Convert simple dict config to RTCIceServer objects if needed
            # aiortc expects RTCIceServer objects in RTCConfiguration
            rtc_ice_servers = []
            for server in ice_servers:
                # Handle Metered.ca format or standard format
                urls = server.get("urls")
                username = server.get("username")
                credential = server.get("credential")
                
                if urls:
                    if isinstance(urls, str):
                        urls = [urls]
                    rtc_ice_servers.append(RTCIceServer(
                        urls=urls,
                        username=username,
                        credential=credential
                    ))
            
            config = RTCConfiguration(iceServers=rtc_ice_servers)
            logger.info(f"🔧 Creating RTCPeerConnection for {session_id} with custom ICE servers (TURN)")
        else:
            config = self.default_rtc_config
            logger.info(f"🔧 Creating RTCPeerConnection for {session_id} with default STUN servers")

        pc = RTCPeerConnection(configuration=config)
        self.pcs[session_id] = pc

        # Create track ready event for this session (initially not set)
        self.track_ready_events[session_id] = asyncio.Event()

        # Create and add audio track
        track = TTSAudioTrack(track_id=f"audio_{session_id}")
        self.tracks[session_id] = track
        sender = pc.addTrack(track)
        self.senders[session_id] = sender
        logger.info(f"🎵 Added audio track to peer connection: {track.id} (label: {track.track_label})")
        logger.info(f"   Track kind: {track.kind}, readyState: live, sender: {sender}")

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info(f"🔌 WebRTC connection state for {session_id}: {pc.connectionState}")
            if pc.connectionState == "failed":
                await self.close_peer_connection(session_id)

        return pc

    async def handle_offer(self, session_id: str, sdp: str, type: str, ice_servers: Optional[list] = None) -> Optional[Dict]:
        """
        Handle SDP offer from client, set remote description,
        create answer, and set local description.
        """
        try:
            logger.info(f"📞 [handle_offer] Processing WebRTC offer for session {session_id[:8]}...")
            pc = await self.create_peer_connection(session_id, ice_servers=ice_servers)

            offer = RTCSessionDescription(sdp=sdp, type=type)
            logger.info(f"📝 [handle_offer] Setting remote description (offer)")
            logger.debug(f"   Offer SDP (first 300 chars): {sdp[:300]}")
            await pc.setRemoteDescription(offer)

            logger.info(f"📝 [handle_offer] Creating answer")
            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)

            logger.info(f"✅ [handle_offer] Answer created and set as local description")
            logger.debug(f"   Answer SDP (first 300 chars): {pc.localDescription.sdp[:300]}")

            # Log transceivers to see what was negotiated
            for idx, transceiver in enumerate(pc.getTransceivers()):
                logger.info(f"   Transceiver {idx}: {transceiver.kind}, direction={transceiver.direction}")
                if transceiver.sender and transceiver.sender.track:
                    track = transceiver.sender.track
                    logger.info(f"      Sender track: {track.id}, kind={track.kind}")

            # Signal that track is established and ready for audio streaming
            self.on_track_established(session_id)
            logger.info(f"✅ [handle_offer] Track established, ready for audio streaming")

            # Verify track is in our map
            if session_id in self.tracks:
                logger.info(f"   Track verified in tracks map: {self.tracks[session_id].id}")
            else:
                logger.error(f"❌ [handle_offer] Track NOT in tracks map after creation!")

            return {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type
            }
        except Exception as e:
            logger.error(f"❌ [handle_offer] Error for session {session_id[:8]}...: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def handle_ice_candidate(self, session_id: str, candidate_data: Dict[str, Any]):
        """
        Handle ICE candidate from client (Trickle ICE).
        """
        if session_id not in self.pcs:
            logger.warning(f"⚠️ Received ICE candidate for unknown session {session_id}")
            return

        try:
            pc = self.pcs[session_id]

            # Extract candidate - handle both direct and nested structures
            if isinstance(candidate_data.get("candidate"), dict):
                # Nested: {candidate: {candidate: "...", sdpMid: "...", ...}}
                candidate_obj = candidate_data["candidate"]
                candidate_str = candidate_obj.get("candidate", "")
                sdp_mid = candidate_obj.get("sdpMid")
                sdp_mline_index = candidate_obj.get("sdpMLineIndex")
            else:
                # Direct: {candidate: "...", sdpMid: "...", ...}
                candidate_str = candidate_data.get("candidate", "")
                sdp_mid = candidate_data.get("sdpMid")
                sdp_mline_index = candidate_data.get("sdpMLineIndex")
            
            if not candidate_str:
                return

            # Parse candidate string manually or use aiortc's method if available
            # aiortc's RTCIceCandidate requires parsed fields
            # A simplified parsing approach for standard candidate strings
            parts = candidate_str.split()
            if len(parts) < 8:
                logger.warning(f"⚠️ Invalid ICE candidate format: {candidate_str}")
                return
                
            # Example: candidate:842163049 1 udp 1677729535 192.168.1.10 56789 typ srflx raddr 0.0.0.0 rport 0
            foundation = parts[0].split(':')[1]
            component = int(parts[1])
            protocol = parts[2].lower()
            priority = int(parts[3])
            ip = parts[4]
            port = int(parts[5])
            type = parts[7]
            
            # Create candidate object
            candidate = RTCIceCandidate(
                foundation=foundation,
                component=component,
                protocol=protocol,
                priority=priority,
                ip=ip,
                port=port,
                type=type,
                sdpMid=sdp_mid,
                sdpMLineIndex=sdp_mline_index
            )
            
            logger.debug(f"❄️ Adding ICE candidate for {session_id}: {ip}:{port} ({type})")
            await pc.addIceCandidate(candidate)

        except Exception as e:
            logger.error(f"❌ Error handling ICE candidate for {session_id}: {e}")

    async def wait_for_track_ready(self, session_id: str, timeout: float = 5.0) -> bool:
        """
        Wait for WebRTC track to be fully established before streaming audio.

        This prevents audio chunk loss by ensuring the track is ready to receive data.

        Args:
            session_id: Session identifier
            timeout: Maximum time to wait in seconds (default: 5.0)

        Returns:
            True if track is ready, False if timeout occurred
        """
        if session_id not in self.track_ready_events:
            logger.warning(f"⚠️ No track ready event for session {session_id[:8]}...")
            return False

        try:
            await asyncio.wait_for(
                self.track_ready_events[session_id].wait(),
                timeout=timeout
            )
            logger.info(f"✅ WebRTC track ready | session={session_id[:8]}...")
            return True
        except asyncio.TimeoutError:
            logger.error(f"❌ Track ready timeout after {timeout}s | session={session_id[:8]}...")
            return False

    def on_track_established(self, session_id: str):
        """
        Signal that WebRTC track is fully established and ready to receive audio.

        Call this after SDP negotiation completes to allow audio streaming to begin.

        Args:
            session_id: Session identifier
        """
        if session_id not in self.track_ready_events:
            # Create event if it doesn't exist
            self.track_ready_events[session_id] = asyncio.Event()

        self.track_ready_events[session_id].set()
        logger.info(f"🎯 WebRTC track established | session={session_id[:8]}...")

    async def close_peer_connection(self, session_id: str):
        """Close peer connection and cleanup."""
        if session_id in self.pcs:
            pc = self.pcs[session_id]
            await pc.close()
            del self.pcs[session_id]
            logger.info(f"Closed WebRTC connection for {session_id}")

        # Clean up track ready event
        if session_id in self.track_ready_events:
            del self.track_ready_events[session_id]

        if session_id in self.tracks:
            del self.tracks[session_id]

        if session_id in self.senders:
            del self.senders[session_id]

    async def push_audio_chunk(self, session_id: str, pcm_data: bytes):
        """Push audio data to the track for the given session."""
        if session_id in self.tracks:
            track = self.tracks[session_id]
            await track.add_frame(pcm_data)
        else:
            # This might happen if WebRTC negotiation hasn't finished yet
            # but we started generating audio.
            logger.warning(f"[push_audio_chunk] No track for session {session_id[:8]}...")
            logger.warning(f"   Available tracks: {list(self.tracks.keys())[:5]}")
            logger.warning(f"   Dropping {len(pcm_data)} bytes of audio")

    async def replace_audio_track(self, session_id: str):
        """
        Replace the audio track (and sender) to drop any buffered frames
        in the old track after an interrupt. This keeps the same peer connection
        but resets the media pipeline on our side.
        """
        if session_id not in self.pcs or session_id not in self.senders:
            logger.warning(f"⚠️ Cannot replace track; no pc/sender for session {session_id}")
            return

        try:
            old_track = self.tracks.get(session_id)
            sender = self.senders[session_id]

            # Stop old track (flush should be called externally before replacing)
            # Note: Caller should flush() before calling replace_audio_track()
            if old_track:
                old_track.stop()

            # Create and attach a fresh track
            new_track = TTSAudioTrack(track_id=f"audio_{session_id}_repl")
            self.tracks[session_id] = new_track
            sender.replaceTrack(new_track)  # Note: replaceTrack is synchronous in aiortc
            logger.info(f"🔁 Replaced audio track for session {session_id}")
        except Exception as e:
            logger.error(f"❌ Failed to replace audio track for session {session_id}: {e}")

# Global instance
webrtc_manager = WebRTCManager()

def get_webrtc_manager():
    return webrtc_manager
