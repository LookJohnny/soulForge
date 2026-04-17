"""Chat endpoint — structured JSON responses, streaming, emotion tracking, and memory."""

import asyncio
import base64
import json
import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai_core.dependencies import (
    get_llm_client, get_prompt_builder, get_tts_client,
    get_emotion_engine,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.services.content_filter import ContentFilter
from ai_core.services.response_parser import parse_llm_response, StructuredResponse, PADValues
from ai_core.services.hardware_mapper import pad_to_hardware
from ai_core.services.text_splitter import split_sentences
from ai_core.models.schemas import HistoryMessage

router = APIRouter(prefix="/chat", tags=["chat"])
logger = structlog.get_logger()
content_filter = ContentFilter()


def _get_brand_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return auth.brand_id


class ChatPreviewRequest(BaseModel):
    character_id: str
    text: str = Field(max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=50)
    voice: str | None = None
    with_audio: bool = True
    with_hardware: bool = False  # opt-in for toy hardware commands
    session_id: str | None = None


class ChatPreviewResponse(BaseModel):
    text: str
    action: str | None = None
    thought: str | None = None
    audio_base64: str | None = None
    audio_format: str | None = None
    emotion: str | None = None
    latency_ms: int = 0


# ── Shared helpers ────────────────────────────────

def _pad_to_discrete(pad: PADValues) -> str:
    from ai_core.services.pad_model import PADState, pad_to_emotion
    return pad_to_emotion(PADState(p=pad.p, a=pad.a, d=pad.d))


async def _update_emotion(
    parsed: StructuredResponse,
    emotion_engine,
    session_id: str | None,
    emotion_state: str | None,
    user_mood: str | None,
    full_text: str,
) -> str | None:
    """Shared emotion update logic for both streaming and non-streaming."""
    if parsed.parsed_ok:
        new_emotion = _pad_to_discrete(parsed.pad)
        if session_id:
            from ai_core.services.pad_model import PADState
            await emotion_engine.pad.set_pad(session_id, PADState(p=parsed.pad.p, a=parsed.pad.a, d=parsed.pad.d))
            await emotion_engine.set_emotion(session_id, new_emotion)
        return new_emotion

    # Fallback: legacy detection
    from ai_core.services.emotion import extract_inline_emotion
    _, inline_emotion = extract_inline_emotion(full_text)
    text_emotion = inline_emotion or emotion_engine.detect_emotion(
        parsed.dialogue, previous=emotion_state or "calm", user_mood=user_mood
    )
    if session_id:
        _, new_emotion = await emotion_engine.update_with_pad(
            session_id=session_id, text_emotion=text_emotion, user_mood=user_mood,
        )
        return new_emotion
    return text_emotion


def _resolve_tts_params(parsed: StructuredResponse, emotion_engine, new_emotion: str | None, prompt_result: dict) -> dict:
    """Shared TTS parameter resolution."""
    base_pitch = prompt_result.get("ssml_pitch", 1.0)
    base_rate = prompt_result.get("ssml_rate", 1.0)
    if parsed.parsed_ok:
        return parsed.voice.to_ssml(base_pitch, base_rate)
    p, r = emotion_engine.apply_tts_offsets(new_emotion or "calm", base_pitch, base_rate)
    return {"ssml_pitch": p, "ssml_rate": r, "ssml_effect": ""}


def _detect_audio_format(data: bytes) -> str:
    if len(data) >= 3 and (data[:3] == b"ID3" or (data[0] == 0xFF and (data[1] & 0xE0) == 0xE0)):
        return "mp3"
    if len(data) >= 4 and data[:4] == b"RIFF":
        return "wav"
    return "mp3"  # default assumption for DashScope


# ── Non-streaming endpoint ────────────────────────

@router.post("/preview", response_model=ChatPreviewResponse)
@limiter.limit("30/minute")
async def chat_preview(req: ChatPreviewRequest, request: Request):
    start = time.monotonic()
    brand_id = _get_brand_id(request)

    is_safe, reason = content_filter.check_input(req.text)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(req.text)
    emotion_state = await emotion_engine.get_emotion(req.session_id) if req.session_id else None

    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id, brand_id=brand_id,
            user_input=req.text, emotion_state=emotion_state, user_mood=user_mood,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else None

    llm = await get_llm_client()
    raw_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"], user_input=req.text,
        history=history, json_mode=True,
    )

    parsed = parse_llm_response(raw_text)
    dialogue = content_filter.filter_output(parsed.dialogue)
    new_emotion = await _update_emotion(parsed, emotion_engine, req.session_id, emotion_state, user_mood, raw_text)

    audio_b64, audio_fmt = None, None
    if req.with_audio and dialogue:
        voice_id = req.voice or prompt_result.get("voice_id")
        tts = await get_tts_client()

        if hasattr(tts._provider, "set_character_context"):
            tts._provider.set_character_context(
                species=prompt_result.get("_species", ""),
                personality=prompt_result.get("personality"),
                voice_clone_ref_id=prompt_result.get("_voice_clone_ref_id"),
                audio_clips=prompt_result.get("_audio_clips"),
            )
        if hasattr(tts._provider, "synthesize_with_pad"):
            audio_data = await tts._provider.synthesize_with_pad(
                text=dialogue, voice=voice_id,
                pad_p=parsed.pad.p, pad_a=parsed.pad.a, pad_d=parsed.pad.d,
            )
        else:
            tts_params = _resolve_tts_params(parsed, emotion_engine, new_emotion, prompt_result)
            audio_data = await tts.synthesize_to_wav(
                text=dialogue, voice=voice_id,
                speed=prompt_result.get("voice_speed", 1.0),
                pitch_rate=prompt_result.get("pitch_rate", 0),
                speech_rate=prompt_result.get("speech_rate", 0),
                **tts_params,
            )
        audio_b64 = base64.b64encode(audio_data).decode()
        audio_fmt = _detect_audio_format(audio_data)

    return ChatPreviewResponse(
        text=dialogue, action=parsed.action or None, thought=parsed.thought or None,
        audio_base64=audio_b64, audio_format=audio_fmt, emotion=new_emotion,
        latency_ms=int((time.monotonic() - start) * 1000),
    )


# ── Streaming endpoint ────────────────────────────

@router.post("/preview/stream")
@limiter.limit("30/minute")
async def chat_preview_stream(req: ChatPreviewRequest, request: Request):
    brand_id = _get_brand_id(request)

    is_safe, reason = content_filter.check_input(req.text)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(req.text)
    emotion_state = await emotion_engine.get_emotion(req.session_id) if req.session_id else None

    builder = await get_prompt_builder()
    try:
        prompt_result = await builder.build(
            character_id=req.character_id, brand_id=brand_id,
            user_input=req.text, emotion_state=emotion_state, user_mood=user_mood,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    history = [{"role": m.role, "content": m.content} for m in req.history] if req.history else None

    async def event_stream():
        try:
            llm = await get_llm_client()
            raw_text = ""

            # ── Phase 1: Real-time stream LLM tokens to client ──
            # Text appears immediately as the LLM generates.
            # May contain JSON/YAML artifacts — cleaned up in Phase 2.
            async for chunk in llm.chat_stream(
                system_prompt=prompt_result["system_prompt"], user_input=req.text,
                history=history, json_mode=True,
            ):
                raw_text += chunk
                yield f"data: {json.dumps({'type': 'text', 'chunk': chunk}, ensure_ascii=False)}\n\n"

            # ── Phase 2: Parse complete output → extract clean dialogue + metadata ──
            parsed = parse_llm_response(raw_text)
            dialogue = content_filter.filter_output(parsed.dialogue)

            # Send text_replace to clean up JSON/YAML artifacts from stream
            yield f"data: {json.dumps({'type': 'text_replace', 'text': dialogue}, ensure_ascii=False)}\n\n"

            # ── Phase 3: Metadata events ──
            if parsed.action:
                yield f"data: {json.dumps({'type': 'action', 'text': parsed.action}, ensure_ascii=False)}\n\n"
            if parsed.thought:
                yield f"data: {json.dumps({'type': 'thought', 'text': parsed.thought}, ensure_ascii=False)}\n\n"

            # ── Phase 4: Emotion update ──
            new_emotion = await _update_emotion(parsed, emotion_engine, req.session_id, emotion_state, user_mood, raw_text)
            yield f"data: {json.dumps({'type': 'emotion', 'emotion': new_emotion, 'pad': {'p': parsed.pad.p, 'a': parsed.pad.a, 'd': parsed.pad.d}, 'stance': parsed.stance}, ensure_ascii=False)}\n\n"

            # Phase 4b: Hardware commands (opt-in)
            if req.with_hardware:
                hw = pad_to_hardware(
                    parsed.pad.p, parsed.pad.a, parsed.pad.d,
                    species=prompt_result.get("_species", ""),
                )
                yield f"data: {json.dumps({'type': 'hardware', **hw.to_dict()}, ensure_ascii=False)}\n\n"

            # ── Phase 5: TTS (sentence-level progressive audio) ──
            if req.with_audio and dialogue:
                voice_id = req.voice or prompt_result.get("voice_id")
                tts = await get_tts_client()
                sentences = split_sentences(dialogue)

                # Fish Audio: set species for voice matching + use PAD-driven synthesis
                if hasattr(tts._provider, "set_character_context"):
                    tts._provider.set_character_context(
                        species=prompt_result.get("_species", ""),
                        personality=prompt_result.get("personality"),
                        voice_clone_ref_id=prompt_result.get("_voice_clone_ref_id"),
                        audio_clips=prompt_result.get("_audio_clips"),
                    )
                use_pad_tts = hasattr(tts._provider, "synthesize_with_pad")

                for i, sentence in enumerate(sentences):
                    try:
                        if use_pad_tts:
                            audio_data = await tts._provider.synthesize_with_pad(
                                text=sentence, voice=voice_id,
                                pad_p=parsed.pad.p, pad_a=parsed.pad.a, pad_d=parsed.pad.d,
                            )
                        else:
                            tts_params = _resolve_tts_params(parsed, emotion_engine, new_emotion, prompt_result)
                            audio_data = await tts.synthesize_to_wav(
                                text=sentence, voice=voice_id,
                                speed=prompt_result.get("voice_speed", 1.0),
                                pitch_rate=prompt_result.get("pitch_rate", 0),
                                speech_rate=prompt_result.get("speech_rate", 0),
                                **tts_params,
                            )
                        audio_b64 = base64.b64encode(audio_data).decode()
                        yield f"data: {json.dumps({'type': 'audio', 'index': i, 'total': len(sentences), 'audio_base64': audio_b64, 'audio_format': _detect_audio_format(audio_data)}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        logger.warning("tts.sentence_error", error=str(e), index=i)

        except asyncio.CancelledError:
            logger.info("chat.stream_cancelled")
            return
        except Exception as e:
            logger.error("chat.stream_error", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': '服务暂时出错，请重试'}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
