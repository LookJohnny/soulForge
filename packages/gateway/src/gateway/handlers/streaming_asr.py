"""Streaming ASR — real-time speech recognition using DashScope Recognition.

Runs ASR concurrently with audio reception. By the time VAD detects
end-of-speech, ASR has already processed most of the audio, reducing
perceived latency by 1-3 seconds compared to batch recognition.

Usage:
    asr_session = StreamingASR()
    asr_session.start()
    # As audio frames arrive:
    asr_session.feed(pcm_chunk)
    # When VAD says speech ended:
    text = await asr_session.finish()
"""

import asyncio
import logging
import os
import threading

import dashscope.audio.asr as dashscope_asr

logger = logging.getLogger(__name__)


class _ASRCallback(dashscope_asr.RecognitionCallback):
    """Callback handler for streaming recognition results."""

    def __init__(self):
        self.final_text = ""
        self.partial_text = ""
        self.error = None
        self._done = threading.Event()

    def on_event(self, result):
        # Intermediate results
        sentences = result.get_sentence()
        if sentences:
            self.partial_text = "".join(s.get("text", "") for s in sentences)

    def on_complete(self):
        if self.partial_text:
            self.final_text = self.partial_text
        self._done.set()

    def on_error(self, result):
        self.error = str(result)
        self._done.set()

    def on_close(self):
        self._done.set()

    def on_open(self):
        pass

    def wait(self, timeout: float = 10.0) -> str:
        self._done.wait(timeout=timeout)
        if self.error:
            logger.warning("streaming_asr.error: %s", self.error)
            return ""
        return self.final_text or self.partial_text


class StreamingASR:
    """Real-time streaming ASR session.

    Wraps DashScope Recognition in streaming mode. Feed PCM chunks
    as they arrive, get the final text when done.
    """

    def __init__(self, api_key: str, model: str = "paraformer-realtime-v2"):
        self._api_key = api_key
        self._model = model
        self._callback = _ASRCallback()
        self._recognition = None
        self._started = False

    def start(self):
        """Start the streaming ASR session."""
        self._callback = _ASRCallback()
        self._recognition = dashscope_asr.Recognition(
            model=self._model,
            format="pcm",
            sample_rate=16000,
            callback=self._callback,
            api_key=self._api_key,
        )
        self._recognition.start()
        self._started = True
        logger.info("streaming_asr.started")

    def feed(self, pcm_chunk: bytes):
        """Feed a PCM audio chunk to the recognizer."""
        if self._started and self._recognition:
            try:
                self._recognition.send_audio_frame(pcm_chunk)
            except Exception as e:
                logger.warning("streaming_asr.feed_error: %s", e)

    async def finish(self, timeout: float = 8.0) -> str:
        """Stop streaming and return the final recognized text."""
        if not self._started or not self._recognition:
            return ""

        try:
            self._recognition.stop()
        except Exception as e:
            logger.warning("streaming_asr.stop_error: %s", e)
            return ""

        # Wait for callback completion in a thread to avoid blocking
        text = await asyncio.to_thread(self._callback.wait, timeout)
        self._started = False
        logger.info("streaming_asr.result text=%s", text[:50] if text else "(empty)")
        return text

    def abort(self):
        """Abort the session without waiting for results."""
        if self._started and self._recognition:
            try:
                self._recognition.stop()
            except Exception:
                pass
        self._started = False
