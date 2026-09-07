"""Bounded, real loopback WebRTC acceptance probe (no synthetic fallback).

    python -m media_body.probe --health
    python -m media_body.probe --text '你好，请简单介绍自己。' --output outputs/selfhost-probe

The text command invokes the configured brain / TTS / GPU. It records received
tracks, not a screen or loudspeaker. Sender metrics and client decode-consumption
timestamps are deliberately separate; neither verifies human-perceived playback.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
from fractions import Fraction
import json
import math
from pathlib import Path
import time
from uuid import UUID, uuid4

from aiohttp import ClientSession, ClientTimeout
from aiortc import MediaStreamTrack, RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from aiortc.mediastreams import MediaStreamError
import av
import numpy as np

from .server import Settings

MAX_SECONDS = 60


class ProbeError(Exception):
    """Only fixed, locally constructed codes are safe for the output report."""


def _configuration(settings):
    if not isinstance(settings.token, str) or len(settings.token) < 24:
        raise ProbeError("media_token_unconfigured")
    if not isinstance(settings.port, int) or not 1 <= settings.port <= 65535:
        raise ProbeError("invalid_media_port")
    return f"http://127.0.0.1:{settings.port}"


async def _request(http, base, path, data=None):
    method = "GET" if data is None else "POST"
    async with http.request(method, base + path, json=data, allow_redirects=False) as response:
        if not 200 <= response.status < 300:
            raise ProbeError(f"http_{response.status}")
        raw = bytearray()
        async for block in response.content.iter_chunked(16_384):
            raw.extend(block)
            if len(raw) > 200_000:
                raise ProbeError("response_too_large")
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            raise ProbeError("invalid_json_response") from None
        if not isinstance(value, dict):
            raise ProbeError("invalid_json_response")
        return value


def _redact(value, settings):
    """Remove even echoed secrets from selected untrusted upstream fields."""
    secrets = [settings.token, settings.gateway_token, settings.worker_token]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        return value[:300]
    if isinstance(value, dict):
        return {k: _redact(v, settings) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, settings) for v in value[:20]]
    if type(value) is float and not math.isfinite(value):
        return None
    if value is None or type(value) in (bool, int, float):
        return value
    return None


def _safe_health(raw, settings):
    # Do not print arbitrary provider fields, URLs, headers, or credentials.
    def scalar(value):
        return value if value is None or type(value) in (str, bool, int, float) else None
    result = {key: scalar(raw.get(key)) for key in
              ("status", "readiness_scope", "end_to_end_verified")}
    result["ready"] = raw.get("ready") is True
    for section, fields in {
        "worker": ("ready", "status", "model", "revision", "block_samples", "fps", "reason"),
        "brain": ("ready", "readiness_scope", "end_to_end_verified"),
    }.items():
        source = raw.get(section)
        result[section] = {k: scalar(source.get(k)) for k in fields} if isinstance(source, dict) else {}
    return _redact(result, settings)


def _http(settings):
    return ClientSession(headers={"Authorization": "Bearer " + settings.token},
                         timeout=ClientTimeout(total=25, connect=5), trust_env=False)


async def check_health(settings, *, http_factory=_http):
    try:
        base = _configuration(settings)
        async with asyncio.timeout(30), http_factory(settings) as http:
            return _safe_health(await _request(http, base, "/health"), settings)
    except ProbeError as error:
        return {"ready": False, "error": str(error)}
    except Exception:
        return {"ready": False, "error": "health_request_failed"}


class ObservedTrack(MediaStreamTrack):
    """Timestamps when this client consumes decoded frames, not RTP arrival."""
    def __init__(self, source, counters, turn_clock):
        super().__init__()
        self.kind, self.source = source.kind, source
        self.counters, self.turn_clock = counters, turn_clock

    async def recv(self):
        frame = await self.source.recv()
        now = time.monotonic()
        stats = self.counters[self.kind]
        stats["decoded_frames"] += 1
        if self.turn_clock[0] is not None:
            elapsed = round((now - self.turn_clock[0]) * 1000, 2)
            if stats["first_frame_ms"] is None:
                stats["first_frame_ms"] = elapsed
            if self.kind == "audio" and stats["first_non_silent_frame_ms"] is None:
                samples = frame.to_ndarray().astype(np.float64)
                # aiortc normally yields s16. Normalize floating formats too.
                scale = 1.0 if frame.format.name.startswith(("flt", "dbl")) else 32768.0
                if float(np.sqrt(np.mean((samples / scale) ** 2))) >= .001:
                    stats["first_non_silent_frame_ms"] = elapsed
        return frame


class ReceivedRecorder:
    """Configure video before muxing audio, even when GPU startup is slow.

    aiortc normalizes each incoming RTP timestamp independently. Align these
    clocks by the first decoded frame's local consumption time; this is an
    explicit approximation, not a claim of RTCP-synchronized playback.
    """
    def __init__(self, filename):
        self.container = av.open(filename, mode="w", format="mp4")
        self.streams, self.tracks, self.origins = {}, {}, {}
        self.tasks, self.pending_audio = [], []
        self.video_ready = False
        self.error = None
        self.started = None

    def addTrack(self, track):
        self.tracks[track.kind] = track
        stream = self.container.add_stream("aac" if track.kind == "audio" else "libx264",
                                           rate=48000 if track.kind == "audio" else 25)
        if track.kind == "video":
            stream.pix_fmt = "yuv420p"
            stream.options = {"preset": "veryfast", "tune": "zerolatency"}
        self.streams[track.kind] = stream

    async def start(self):
        self.started = time.monotonic()
        self.tasks = [asyncio.create_task(self._receive(track)) for track in self.tracks.values()]

    def _encode(self, kind, frame):
        for packet in self.streams[kind].encode(frame):
            self.container.mux(packet)

    async def _receive(self, track):
        try:
            while True:
                frame = await track.recv()
                if frame.pts is None or frame.time_base is None:
                    raise ProbeError("received_frame_without_timestamp")
                if track.kind not in self.origins:
                    self.origins[track.kind] = (Fraction(frame.pts) * frame.time_base,
                                                time.monotonic() - self.started)
                first_pts, arrival = self.origins[track.kind]
                # Retain progression of the received media clock after anchoring
                # its first frame; avoid replacing every PTS with network jitter.
                seconds = Fraction(frame.pts) * frame.time_base - first_pts + Fraction(arrival)
                frame.pts = round(seconds / frame.time_base)
                if track.kind == "video" and not self.video_ready:
                    self.streams["video"].width, self.streams["video"].height = frame.width, frame.height
                    self.video_ready = True
                    for waiting in self.pending_audio:
                        self._encode("audio", waiting)
                    self.pending_audio.clear()
                if track.kind == "audio" and not self.video_ready:
                    if len(self.pending_audio) >= 3000:  # 60 seconds at 20 ms
                        raise ProbeError("recording_audio_buffer_full")
                    self.pending_audio.append(frame)
                else:
                    self._encode(track.kind, frame)
        except (asyncio.CancelledError, MediaStreamError):
            pass
        except Exception:
            self.error = "recording_encoder_failed"

    async def stop(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        try:
            if self.video_ready:
                for stream in self.streams.values():
                    for packet in stream.encode(None):
                        self.container.mux(packet)
        finally:
            self.container.close()
            self.pending_audio.clear()
        if self.error:
            raise ProbeError(self.error)


def _recording_info(path):
    """Inspect the actual finalized MP4; receiving tracks alone is insufficient."""
    streams = {}
    with av.open(str(path)) as container:
        for stream in container.streams:
            if stream.type not in {"audio", "video"}:
                continue
            frames = container.decode(stream)
            first = next(frames, None)
            streams[stream.type] = {"decodable": first is not None,
                                    "codec": stream.codec_context.name}
            # Seek back because decode(audio) may consume the entire container.
            container.seek(0)
    return {"bytes": path.stat().st_size, "streams": streams}


async def run_probe(settings, text, output, *, timeout=MAX_SECONDS,
                    http_factory=_http, pc_factory=RTCPeerConnection,
                    recorder_factory=ReceivedRecorder, tail_seconds=1.0):
    """Receive for <=60s, then spend <=10s closing owned resources.

    Injection points are only for offline tests; CLI always uses real HTTP,
    aiortc and FFmpeg. No microphone track is sent, so this is typed-turn testing.
    """
    if not 0 < timeout <= MAX_SECONDS or not 0 <= tail_seconds <= 2:
        raise ValueError("probe duration must be between 0 and 60 seconds")
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 4000:
        raise ValueError("text must contain 1-4000 characters")
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    stem = "probe-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex[:8]
    movie, timing = output / (stem + ".mp4"), output / (stem + ".json")
    report = {"ok": False, "status": "starting", "receive_limit_seconds": timeout,
              "cleanup_limit_seconds": 10,
              "scope": "local_aiortc_received_tracks; typed_input; no_microphone",
              "human_playback_verified": False, "interruption_verified": False,
              "sender": None,
              "client": {"clock_origin": "before_turn_http_request",
                         "measurement": "decoded_frame_consumption; not RTP arrival or display",
                         "audio": {"decoded_frames": 0, "first_frame_ms": None,
                                   "first_non_silent_frame_ms": None},
                         "video": {"decoded_frames": 0, "first_frame_ms": None}},
              "limitations": ["audio first_frame may be idle silence",
                              "non_silent uses RMS >= 0.001; not semantic speech detection",
                              "sender drained does not prove all tail frames arrived",
                              "recording re-encodes received media as AAC/H264 at 25 fps",
                              "track clocks aligned by first decoded arrival; no RTCP synchronization"],
              "cleanup": {"remote_closed": None, "peer_closed": None, "http_closed": None}}
    owner = str(uuid4())
    pc = recorder = http = None
    create_attempted = False
    cancelled = None
    turn_clock = [None]
    events = asyncio.Queue(maxsize=100)
    tracks, connected, channel_open = {}, asyncio.Event(), asyncio.Event()
    try:
        base = _configuration(settings)
        async with asyncio.timeout(timeout):
            http = http_factory(settings)
            report["health"] = _safe_health(await _request(http, base, "/health"), settings)
            if not report["health"]["ready"]:
                raise ProbeError("media_not_ready")
            pc = pc_factory(RTCConfiguration(iceServers=[]))
            channel = pc.createDataChannel("events", ordered=True)

            @pc.on("track")
            def on_track(track):
                if track.kind in {"audio", "video"}:
                    tracks[track.kind] = ObservedTrack(track, report["client"], turn_clock)

            @pc.on("connectionstatechange")
            def on_connection():
                if pc.connectionState == "connected":
                    connected.set()

            @channel.on("open")
            def on_open():
                channel_open.set()

            @channel.on("message")
            def on_message(message):
                try:
                    value = json.loads(message)
                    if (isinstance(value, dict) and value.get("type") in {"metrics", "error"}
                            and not events.full()):
                        events.put_nowait(value)
                except (ValueError, TypeError):
                    pass

            pc.addTransceiver("audio", direction="recvonly")
            pc.addTransceiver("video", direction="recvonly")
            await pc.setLocalDescription(await pc.createOffer())
            create_attempted = True  # Even a lost response must close this owner.
            answer = await _request(http, base, "/sessions", {
                "client_id": owner, "type": "offer", "sdp": pc.localDescription.sdp})
            try:
                sid = str(UUID(answer["session_id"]))
                if answer["type"] != "answer" or not isinstance(answer["sdp"], str):
                    raise ValueError
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ProbeError("invalid_session_answer") from None
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type="answer"))
            if pc.connectionState == "connected":
                connected.set()
            if channel.readyState == "open":
                channel_open.set()
            await connected.wait()
            await channel_open.wait()
            if set(tracks) != {"audio", "video"}:
                raise ProbeError("missing_remote_tracks")
            movie.touch(mode=0o600, exist_ok=False)
            recorder = recorder_factory(str(movie))
            for track in tracks.values():
                recorder.addTrack(track)
            await recorder.start()
            turn_clock[0] = time.monotonic()
            turn = await _request(http, base, f"/sessions/{sid}/turn", {"client_id": owner, "text": text.strip()})
            try:
                turn_id = str(UUID(turn["turn_id"]))
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ProbeError("invalid_turn_response") from None
            while True:
                event = await events.get()
                if event.get("turn_id") != turn_id:
                    continue
                if event["type"] == "error":
                    raise ProbeError("turn_failed")
                values = {}
                for key in ("first_audio_ready_ms", "first_video_ready_ms", "sender_drained_ms", "dropped_packets"):
                    value = event.get(key)
                    values[key] = value if type(value) in (float, int) and math.isfinite(value) and value >= 0 else None
                report["sender"] = {"scope": "media_body_generation_and_sender_drain",
                                    "browser_playback_verified": False, **values}
                break
            await asyncio.sleep(tail_seconds)
            report["tail_receive_seconds"] = tail_seconds
            if (not all(report["client"][k]["decoded_frames"] for k in ("audio", "video"))
                    or report["client"]["audio"]["first_non_silent_frame_ms"] is None):
                raise ProbeError("missing_received_speech_or_video")
            report.update(ok=True, status="received")
    except ProbeError as error:
        report.update(status="failed", error=str(error))
    except TimeoutError:
        report.update(status="timeout", error="receive_deadline_exceeded")
    except asyncio.CancelledError as error:
        cancelled = error
        report.update(status="cancelled", error="probe_cancelled")
    except Exception:
        report.update(status="failed", error="probe_failed")
    finally:
        # Close the recorder before checking its file and finalize every resource
        # independently: one close failure must not skip the other close calls.
        if recorder:
            try:
                await asyncio.wait_for(recorder.stop(), 2)
            except Exception:
                report["recording_error"] = "recording_finalize_failed"
                if report["ok"]:
                    report.update(ok=False, status="failed", error="recording_finalize_failed")
        if http and create_attempted:
            try:
                result = await asyncio.wait_for(_request(http, base, "/sessions/close-owned", {"client_id": owner}), 5)
                report["cleanup"]["remote_closed"] = result.get("ok") is True
            except Exception:
                report["cleanup"]["remote_closed"] = False
        if pc:
            try:
                await asyncio.wait_for(pc.close(), 2)
                report["cleanup"]["peer_closed"] = True
            except Exception:
                report["cleanup"]["peer_closed"] = False
        if http:
            try:
                await asyncio.wait_for(http.close(), 1)
                report["cleanup"]["http_closed"] = True
            except Exception:
                report["cleanup"]["http_closed"] = False
        if False in report["cleanup"].values():
            if report["ok"]:
                report.update(ok=False, status="failed", error="cleanup_unconfirmed")
            report["cleanup_error"] = "cleanup_unconfirmed"
        if movie.exists():
            try:
                report["recording"] = _recording_info(movie)
                report["recording"]["path"] = str(movie)
                if not all(report["recording"]["streams"].get(k, {}).get("decodable") for k in ("audio", "video")):
                    raise ValueError
            except Exception:
                report["recording_error"] = "recording_missing_decodable_tracks"
                if report["ok"]:
                    report.update(ok=False, status="failed", error="recording_missing_decodable_tracks")
        elif report["ok"]:
            report.update(ok=False, status="failed", error="recording_not_written")
        report["timing_path"] = str(timing)
        report = _redact(report, settings)
        timing.touch(mode=0o600, exist_ok=False)
        timing.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        timing.chmod(0o600)
        if movie.exists():
            movie.chmod(0o600)
    if cancelled:
        raise cancelled
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--health", action="store_true", help="readiness only; creates no session")
    mode.add_argument("--text", help="run a real typed turn; invokes configured providers")
    parser.add_argument("--output", default="outputs/selfhost-probe", help="directory for received MP4 and timing JSON")
    args = parser.parse_args(argv)
    try:
        settings = Settings.load()
        result = asyncio.run(check_health(settings) if args.health else run_probe(settings, args.text, args.output))
    except KeyboardInterrupt:
        result = {"ok": False, "error": "interrupted"}
    except Exception:
        result = {"ready": False, "ok": False, "error": "probe_configuration_or_output_failed"}
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if result.get("ready" if args.health else "ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
