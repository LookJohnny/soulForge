from __future__ import annotations

import asyncio
import base64
import json
import time

from aiohttp import ClientSession, ClientTimeout


async def records(response):
    response.raise_for_status()
    pending = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        pending.extend(chunk)
        if len(pending) > 32_000_000:
            raise ValueError("upstream record too large")
        while b"\n" in pending:
            line, _, rest = pending.partition(b"\n")
            pending = bytearray(rest)
            if line.strip():
                yield json.loads(line)
    if pending.strip():
        raise ValueError("truncated upstream stream")


class Endpoint:
    def __init__(self, http: ClientSession, url: str, token: str):
        self.http, self.url = http, url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    async def post(self, path: str, data: dict):
        async with self.http.post(self.url + path, json=data, headers=self.headers,
                                  allow_redirects=False, timeout=ClientTimeout(total=40)) as response:
            response.raise_for_status()
            return await response.json()

    async def health(self, path="/health"):
        async with self.http.get(self.url + path, headers=self.headers,
                                 allow_redirects=False, timeout=ClientTimeout(total=3)) as response:
            response.raise_for_status()
            return await response.json()


class Gateway(Endpoint):
    async def open(self, body_id):
        return (await self.post("/media/sessions", {"body_id": body_id}))["session_id"]

    async def turn(self, sid, turn_id, text):
        async with self.http.post(self.url + f"/media/sessions/{sid}/turn",
                                  json={"turn_id": turn_id, "text": text}, headers=self.headers,
                                  allow_redirects=False, timeout=ClientTimeout(total=180, sock_read=90)) as response:
            async for item in records(response):
                if item.get("turn_id") != turn_id:
                    raise ValueError("gateway turn mismatch")
                yield item

    async def interrupt(self, sid, turn_id):
        return await self.post(f"/media/sessions/{sid}/interrupt", {"turn_id": turn_id})

    async def close(self, sid):
        return await self.post(f"/media/sessions/{sid}/close", {})

    async def receipt(self, sid, receipt_id, played=False):
        return await self.post(f"/media/sessions/{sid}/receipt", {
            "receipt_id": receipt_id, "played": played,
            "detail": "sender_transport_only; browser playback unverified",
        })

    async def transcribe(self, sid, pcm):
        return (await self.post(f"/media/sessions/{sid}/transcribe", {
            "audio_base64": base64.b64encode(pcm).decode(), "format": "pcm16",
            "sample_rate": 16000, "channels": 1,
        }))["text"]


class Worker(Endpoint):
    async def render(self, request_id, pcm):
        deadline = time.monotonic() + 30
        data = {"request_id": request_id, "sample_rate": 16000,
                "audio_base64": base64.b64encode(pcm).decode()}
        while True:
            async with self.http.post(self.url + "/render", headers=self.headers, json=data,
                                      allow_redirects=False, timeout=ClientTimeout(total=300, sock_read=120)) as response:
                if response.status == 429 and time.monotonic() < deadline:
                    # Only retry an explicitly rejected GPU request. Never repeat
                    # cognition/TTS or a render stream that has been accepted.
                    await asyncio.sleep(.2)
                    continue
                async for item in records(response):
                    if item.get("request_id") != request_id:
                        raise ValueError("worker request mismatch")
                    yield item
                return
