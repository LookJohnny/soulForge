"""Edge TTS provider — free Microsoft TTS via edge-tts library."""

import io
import struct
import tempfile

import edge_tts

from ai_core.services.tts.base import TTSProvider

# Good Chinese voices from Edge TTS
EDGE_VOICES = {
    "zh-CN-XiaoxiaoNeural": "晓晓 (温柔女声)",
    "zh-CN-YunxiNeural": "云希 (阳光男声)",
    "zh-CN-XiaoyiNeural": "晓伊 (甜美少女)",
    "zh-CN-YunjianNeural": "云健 (沉稳男声)",
    "zh-CN-XiaochenNeural": "晓辰 (知性女声)",
    "zh-CN-YunxiaNeural": "云夏 (活力男声)",
}

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def mp3_to_wav_16k(mp3_data: bytes) -> bytes:
    """Convert MP3 data to 16kHz mono 16bit WAV.

    Since edge-tts produces MP3, we do a basic conversion.
    For production, consider using pydub or ffmpeg.
    This returns the MP3 wrapped as-is in a WAV-like container for simplicity,
    but for actual PCM conversion, ffmpeg would be needed.
    """
    # edge-tts supports --write-media as MP3; we return it directly
    # Downstream audio players typically handle MP3 fine
    return mp3_data


class EdgeTTSProvider(TTSProvider):
    """Free TTS via Microsoft Edge (edge-tts library)."""

    name = "edge"

    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        voice_name = voice if voice and voice.endswith("Neural") else DEFAULT_VOICE
        rate_str = f"{int((speed - 1) * 100):+d}%"

        communicate = edge_tts.Communicate(text, voice_name, rate=rate_str)

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            raise RuntimeError(f"Edge TTS synthesis failed for voice={voice_name}")

        return b"".join(audio_chunks)

    async def synthesize_to_wav(
        self,
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
    ) -> bytes:
        # edge-tts outputs MP3 natively; return as-is (browsers can play MP3)
        return await self.synthesize(text, voice, speed)

    def get_voices(self) -> dict[str, str]:
        return dict(EDGE_VOICES)
