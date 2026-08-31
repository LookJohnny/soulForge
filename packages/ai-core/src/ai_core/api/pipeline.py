"""Full chat pipeline.

(ASR) -> Filter -> Prompt(emotion+memory+relationship) -> LLM -> Filter -> (TTS).

Integrates: emotion tracking, conversation memory, relationship evolution,
personality drift, and proactive triggers.

Provides both blocking (/chat) and streaming (/chat/stream) endpoints.
"""

import asyncio
import base64
import json
import re
import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ai_core.config import settings
from ai_core.dependencies import (
    get_asr_client,
    get_cache,
    get_emotion_engine,
    get_event_engine,
    get_llm_client,
    get_memory_service,
    get_personality_drift,
    get_proactive_trigger,
    get_prompt_builder,
    get_relationship_engine,
    get_touch_engine,
    get_tts_client,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import (
    ChatRequest,
    ChatResponse,
    PADStateSchema,
    TouchEventRequest,
    TouchEventResponse,
)
from ai_core.services.content_filter import ContentFilter
from ai_core.services.hardware_mapper import pad_to_hardware
from ai_core.services.latency import Stopwatch, latency_tracker
from ai_core.services.tts.context import prepare_for_character as _tts_prepare_for_character

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = structlog.get_logger()
content_filter = ContentFilter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024


_BACKGROUND_TASKS: set[asyncio.Task] = set()


def _spawn(coro, label: str = "task") -> None:
    """F15 (audit): bare create_task results were dropped — tasks could be
    GC'd mid-flight and exceptions vanished. Keep a strong ref and log."""
    task = asyncio.create_task(coro)
    _BACKGROUND_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BACKGROUND_TASKS.discard(t)
        if not t.cancelled() and t.exception() is not None:
            logger.error("pipeline.background_task_failed", task=label, error=str(t.exception()))

    task.add_done_callback(_done)


def _get_brand_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return auth.brand_id


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(req: ChatRequest, request: Request):
    start = time.monotonic()
    sw = Stopwatch()
    brand_id = _get_brand_id(request)

    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        audio_bytes = base64.b64decode(req.audio_data)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="Audio data exceeds 10MB limit")
        asr = await get_asr_client()
        user_text = await asr.recognize(audio_bytes)
        sw.mark("asr")

    if not user_text and req.idle_mode:
        # Idle mode — the character is alone; prompt a spontaneous musing.
        from ai_core.services.persona_context import idle_input

        user_text = idle_input(req.idle_state)

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        logger.warning("content_filter.blocked_input", reason=reason)
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Detect user mood from text. In idle mode nobody spoke — keep the
    # stored mood untouched.
    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(user_text)
    if not req.idle_mode:
        await emotion_engine.set_user_mood(req.session_id, user_mood)

    # 3b. Check for recent touch context (idle turns must not consume it)
    touch_engine = get_touch_engine()
    touch_ctx = None
    if not req.idle_mode:
        touch_ctx = await touch_engine.get_touch_context(req.session_id)
    touch_prompt = ""
    touch_gesture = None
    touch_affinity_bonus = 0
    if touch_ctx:
        touch_prompt = touch_ctx.get("prompt", "")
        touch_gesture = touch_ctx.get("gesture")
        touch_affinity_bonus = touch_ctx.get("affinity_bonus", 0)
        # Touch influences user mood detection
        touch_mood = touch_ctx.get("mood_hint")
        if touch_mood and touch_mood != "neutral" and user_mood == "neutral":
            user_mood = touch_mood
            await emotion_engine.set_user_mood(req.session_id, user_mood)
        # Clear touch context after consumption
        await touch_engine.clear_touch_context(req.session_id)

    # 3c. Get current emotion state (discrete, for prompt builder compatibility)
    emotion_state = await emotion_engine.get_emotion(req.session_id)
    prev_pad = await emotion_engine.get_pad_state(req.session_id)

    # 3d. Track silence + mood shift across turns for mid-session embodiment
    cache = get_cache()
    _now_ts = time.time()
    _last_seen_raw = await cache.get(f"last_user_seen:{req.session_id}")
    silence_seconds = 0.0
    if _last_seen_raw:
        try:
            silence_seconds = max(0.0, _now_ts - float(_last_seen_raw))
        except (TypeError, ValueError):
            silence_seconds = 0.0
    prev_user_mood = await cache.get(f"prev_user_mood:{req.session_id}")
    if not req.idle_mode:
        # Idle musings must not reset the silence tracking the user's
        # absence is measured by.
        await cache.set(f"last_user_seen:{req.session_id}", str(_now_ts), ttl=3600)
        await cache.set(f"prev_user_mood:{req.session_id}", user_mood or "neutral", ttl=3600)

    # 4. Retrieve memories
    memory_service = await get_memory_service()
    memories = []
    if req.end_user_id:
        memories = await memory_service.retrieve_memories(
            req.end_user_id,
            req.character_id,
            query=user_text,
            context={"user_mood": user_mood},
        )

    # 5. Retrieve relationship state
    rel_engine = await get_relationship_engine()
    rel_state = {"stage": "STRANGER", "affinity": 0}
    if req.end_user_id:
        rel_state = await rel_engine.get_state(req.end_user_id, req.character_id)
        # Limit memories by relationship depth
        depth = rel_engine.get_memory_depth(rel_state["stage"])
        memories = memories[:depth]

    # 6. Proactive trigger (first message of session; not for idle musings)
    proactive_line = None
    if req.end_user_id and not req.idle_mode:
        trigger_svc = get_proactive_trigger()
        proactive_line = await trigger_svc.maybe_generate_trigger(
            end_user_id=req.end_user_id,
            character_id=req.character_id,
            session_id=req.session_id,
            relationship_stage=rel_state["stage"],
            memories=memories,
        )

    # 7. Time awareness
    from ai_core.services.time_awareness import build_time_prompt

    # Archetype for embodiment / time wording — need character row
    _char_row = await (await get_prompt_builder())._get_character(req.character_id, brand_id)
    _archetype = (_char_row or {}).get("archetype", "ANIMAL")
    time_context = build_time_prompt(
        rel_state.get("last_interaction_date"),
        archetype=_archetype,
        last_interaction_at=rel_state.get("last_interaction_at"),
    )

    # 7b. Embodied sensations + mid-session inner thought
    from ai_core.services.embodiment import build_mid_session_thought, build_sensations

    sensations = build_sensations(
        pad=prev_pad,
        touch_gesture=touch_gesture,
        touch_duration_ms=(touch_ctx or {}).get("duration_ms") if touch_ctx else None,
        archetype=_archetype,
    )
    mid_thought = build_mid_session_thought(
        silence_seconds=silence_seconds,
        user_mood=user_mood,
        prev_user_mood=prev_user_mood,
        archetype=_archetype,
    )

    # 7b. Visual-novel events
    builder = await get_prompt_builder()
    _char_for_events = await builder._get_character(req.character_id, brand_id)
    triggered_event, event_context = await _check_events(
        req,
        rel_state=rel_state,
        emotion_state=emotion_state,
        pad_magnitude=0.0,
        user_text=user_text,
        character_name=(_char_for_events or {}).get("nickname") or "",
    )

    # 8. Build prompt with emotion, memory, relationship, trigger, time, and body context.
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            brand_id=brand_id,
            end_user_id=req.end_user_id,
            user_input=user_text,
            emotion_state=emotion_state,
            user_mood=user_mood,
            memories=memories,
            relationship_stage=rel_state["stage"],
            relationship_state=rel_state if req.end_user_id else None,
            event_context=event_context,
            proactive_trigger=proactive_line,
            time_context=time_context,
            touch_context=touch_prompt,
            sensations=sensations,
            mid_session_thought=mid_thought,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    sw.mark("context")

    # 8. LLM inference
    llm = await get_llm_client()
    ai_raw = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=user_text,
    )
    sw.mark("llm")

    # 9. Parse structured output — dialogue/action/thought/pad/voice/stance
    from ai_core.services.emotion import extract_inline_emotion
    from ai_core.services.response_parser import parse_llm_response

    parsed = parse_llm_response(ai_raw)
    ai_text = parsed.dialogue if parsed.dialogue else ai_raw
    ai_text, inline_emotion = extract_inline_emotion(ai_text)
    ai_text = content_filter.filter_output(ai_text)

    # 10. Emotion update — trust the LLM's explicit PAD when structured parse
    # succeeded. Fall back to keyword detection only for unparsed responses.
    mood_cause = _derive_mood_cause(
        user_mood=user_mood,
        touch_gesture=touch_gesture,
        rel_state=rel_state,
        llm_cause=(parsed.state_changes or {}).get("mood_cause") if parsed.parsed_ok else None,
    )
    if parsed.parsed_ok:
        pad_state, new_emotion = await emotion_engine.update_with_explicit_pad(
            session_id=req.session_id,
            pad_values={"p": parsed.pad.p, "a": parsed.pad.a, "d": parsed.pad.d},
            touch_gesture=touch_gesture,
            user_mood=user_mood,
            personality=prompt_result.get("personality"),
            relationship_stage=rel_state.get("stage"),
            cause=mood_cause,
        )
    else:
        text_emotion = inline_emotion or emotion_engine.detect_emotion(
            ai_text, previous=emotion_state, user_mood=user_mood
        )
        pad_state, new_emotion = await emotion_engine.update_with_pad(
            session_id=req.session_id,
            text_emotion=text_emotion,
            touch_gesture=touch_gesture,
            user_mood=user_mood,
            personality=prompt_result.get("personality"),
            relationship_stage=rel_state.get("stage"),
            cause=mood_cause,
        )

    # 11. TTS with PAD-computed parameters (more nuanced than discrete lookup)
    audio_b64 = None
    if prompt_result.get("voice_id"):
        ssml_pitch = prompt_result.get("ssml_pitch", 1.0)
        ssml_rate = prompt_result.get("ssml_rate", 1.0)
        ssml_pitch, ssml_rate = emotion_engine.apply_tts_offsets_pad(
            pad_state, ssml_pitch, ssml_rate
        )

        tts = await get_tts_client()
        _tts_prepare_for_character(tts, prompt_result)
        audio_bytes = await tts.synthesize(
            text=ai_text,
            voice=prompt_result["voice_id"],
            speed=prompt_result.get("voice_speed", 1.0),
            pitch_rate=prompt_result.get("pitch_rate", 0),
            speech_rate=prompt_result.get("speech_rate", 0),
            ssml_pitch=ssml_pitch,
            ssml_rate=ssml_rate,
            ssml_effect=prompt_result.get("ssml_effect", ""),
        )
        audio_b64 = base64.b64encode(audio_bytes).decode()
        sw.mark("tts")

    # 12. Relationship turn (inline: one cached read + one upsert) so the
    # response can carry the deltas. Idle musings never move the relationship.
    rel_payload = None
    if req.end_user_id and not req.idle_mode:
        rel_payload = await _apply_relationship_turn(
            req,
            user_mood=user_mood,
            user_text=user_text,
            touch_bonus=touch_affinity_bonus,
            llm_suggestion=parsed.state_changes if parsed.parsed_ok else None,
        )
        if rel_payload:
            rel_state = {
                **rel_state,
                "stage": rel_payload["stage"],
                "affinity": rel_payload["axes"]["affection"],
            }

    # 13. Async post-processing (memory + drift).
    # Idle musings are the character talking to itself — they must not
    # create memories or earn relationship points.
    if req.end_user_id and not req.idle_mode:
        _spawn(
            memory_service.extract_and_store(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                user_input=user_text,
                ai_response=ai_text,
            )
        )
        _spawn(
            _post_turn_processing(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                new_emotion=new_emotion,
                touch_bonus=touch_affinity_bonus,
            )
        )

    latency = int((time.monotonic() - start) * 1000)
    stages = {k: int(v) for k, v in sw.stages.items()}
    stages["total"] = latency
    latency_tracker.record_turn("chat", stages)
    logger.info(
        "pipeline.chat",
        latency_ms=latency,
        stages=stages,
        character_id=req.character_id,
        emotion=new_emotion,
        stage=rel_state["stage"],
    )

    return ChatResponse(
        text=ai_text,
        audio_data=audio_b64,
        emotion=new_emotion,
        pad=PADStateSchema(**pad_state.to_dict()),
        relationship_stage=rel_state["stage"],
        affinity=rel_state.get("affinity", 0),
        relationship=rel_payload,
        mood_causes=await emotion_engine.get_pad_causes(req.session_id),
        event=triggered_event.to_payload() if triggered_event else None,
        latency_ms=latency,
        stages=stages,
    )


# ─── Sentence boundary for streaming LLM output ───────────────
_STREAM_SENTENCE_RE = re.compile(r"[。！？；\n.!?;]|(?:\.{3,})|(?:……+)")


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _emit_sentence(
    *,
    tts,
    sentence: str,
    index: int,
    prompt_result: dict,
    stage_ms: dict,
    start: float,
    stream_audio: bool,
):
    """Yield SSE event(s) for one sentence: text, then its audio.

    When ``stream_audio`` is set and the provider supports streaming, the
    text is sent first (``sentence`` event with audio_data=None), followed by
    progressive ``audio_chunk`` events and a closing ``audio_end``. This lets
    the device start decoding/playing before the whole clip is synthesised.
    Otherwise the whole clip rides on the ``sentence`` event (legacy path).
    """
    voice_id = prompt_result.get("voice_id")
    if not voice_id:
        yield _sse({"type": "sentence", "text": sentence, "audio_data": None, "index": index})
        return

    _tts_prepare_for_character(tts, prompt_result)

    if stream_audio and tts.supports_streaming():
        # Text first so the device can render it immediately.
        yield _sse({"type": "sentence", "text": sentence, "audio_data": None, "index": index})
        _t = time.monotonic()
        first = True
        try:
            async for audio_chunk in tts.synthesize_stream(
                text=sentence,
                voice=voice_id,
                speed=prompt_result.get("voice_speed", 1.0),
                pitch_rate=prompt_result.get("pitch_rate", 0),
                speech_rate=prompt_result.get("speech_rate", 0),
            ):
                if first:
                    stage_ms.setdefault("first_audio", (time.monotonic() - start) * 1000)
                    first = False
                yield _sse(
                    {
                        "type": "audio_chunk",
                        "index": index,
                        "audio_data": base64.b64encode(audio_chunk).decode(),
                    }
                )
        except Exception:
            logger.exception("stream.tts_error")
        stage_ms["tts"] = stage_ms.get("tts", 0.0) + (time.monotonic() - _t) * 1000
        yield _sse({"type": "audio_end", "index": index})
        return

    # Non-streaming providers (or streaming disabled): whole clip per sentence.
    audio_b64 = None
    try:
        _t = time.monotonic()
        audio_bytes = await tts.synthesize(
            text=sentence,
            voice=voice_id,
            speed=prompt_result.get("voice_speed", 1.0),
            pitch_rate=prompt_result.get("pitch_rate", 0),
            speech_rate=prompt_result.get("speech_rate", 0),
        )
        stage_ms["tts"] = stage_ms.get("tts", 0.0) + (time.monotonic() - _t) * 1000
        audio_b64 = base64.b64encode(audio_bytes).decode()
    except Exception:
        logger.exception("stream.tts_error")
    if audio_b64:
        stage_ms.setdefault("first_audio", (time.monotonic() - start) * 1000)
    yield _sse({"type": "sentence", "text": sentence, "audio_data": audio_b64, "index": index})


async def _prepare_context(req: ChatRequest, brand_id: str):
    """Shared context preparation for both blocking and streaming endpoints."""
    sw = Stopwatch()
    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        audio_bytes = base64.b64decode(req.audio_data)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="Audio data exceeds 10MB limit")
        asr = await get_asr_client()
        user_text = await asr.recognize(audio_bytes, audio_format=req.audio_format)
        sw.mark("asr")
        logger.info(
            "pipeline.asr_result text=%s bytes=%d",
            user_text[:50] if user_text else "(empty)",
            len(audio_bytes),
        )

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Detect user mood (sync, text-based)
    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(user_text)

    # Resolve service singletons (cheap once initialised) before fanning out.
    touch_engine = get_touch_engine()
    cache = get_cache()
    memory_service = await get_memory_service()
    rel_engine = await get_relationship_engine()
    builder = await get_prompt_builder()

    # 3b. Fan out every independent read concurrently. These hit different
    # stores (Redis emotion/pad/cache via a pooled client, relationship DB,
    # character DB, memory vector search) and have no ordering dependency, so
    # collapsing the serial chain into one gather removes several network
    # round-trips from the pre-LLM critical path. Memory retrieval does not
    # consume the touch-adjusted mood (context['user_mood'] is unused
    # downstream), so launching it before touch resolution is safe.
    async def _retrieve_memories() -> list:
        if not req.end_user_id:
            return []
        return await memory_service.retrieve_memories(
            req.end_user_id,
            req.character_id,
            query=user_text,
            context={"user_mood": user_mood},
        )

    async def _rel_state() -> dict:
        if not req.end_user_id:
            return {"stage": "STRANGER", "affinity": 0}
        return await rel_engine.get_state(req.end_user_id, req.character_id)

    (
        _,
        touch_ctx,
        emotion_state,
        prev_pad,
        _last_seen_raw,
        prev_user_mood,
        rel_state,
        _char_row,
        memories,
    ) = await asyncio.gather(
        emotion_engine.set_user_mood(req.session_id, user_mood),
        touch_engine.get_touch_context(req.session_id),
        emotion_engine.get_emotion(req.session_id),
        emotion_engine.get_pad_state(req.session_id),
        cache.get(f"last_user_seen:{req.session_id}"),
        cache.get(f"prev_user_mood:{req.session_id}"),
        _rel_state(),
        builder._get_character(req.character_id, brand_id),
        _retrieve_memories(),
    )

    # 3c. Resolve touch context (may override a neutral mood).
    # Idle musings must not consume the pending touch or reset trackers.
    if req.idle_mode:
        touch_ctx = {}
    touch_prompt = ""
    touch_gesture = None
    touch_affinity_bonus = 0
    if touch_ctx:
        touch_prompt = touch_ctx.get("prompt", "")
        touch_gesture = touch_ctx.get("gesture")
        touch_affinity_bonus = touch_ctx.get("affinity_bonus", 0)
        touch_mood = touch_ctx.get("mood_hint")
        if touch_mood and touch_mood != "neutral" and user_mood == "neutral":
            user_mood = touch_mood
            await emotion_engine.set_user_mood(req.session_id, user_mood)
        await touch_engine.clear_touch_context(req.session_id)

    # 3d. Silence + mood-shift tracking for mid-session embodiment
    _now_ts = time.time()
    silence_seconds = 0.0
    if _last_seen_raw:
        try:
            silence_seconds = max(0.0, _now_ts - float(_last_seen_raw))
        except (TypeError, ValueError):
            silence_seconds = 0.0
    if not req.idle_mode:  # idle musings must not reset silence/mood trackers
        await asyncio.gather(
            cache.set(f"last_user_seen:{req.session_id}", str(_now_ts), ttl=3600),
            cache.set(f"prev_user_mood:{req.session_id}", user_mood or "neutral", ttl=3600),
        )

    # 4. Limit memories by relationship depth
    if req.end_user_id:
        depth = rel_engine.get_memory_depth(rel_state["stage"])
        memories = memories[:depth]

    # 5. Proactive trigger (needs memories + relationship; never during idle musings)
    proactive_line = None
    if req.end_user_id and not req.idle_mode:
        trigger_svc = get_proactive_trigger()
        proactive_line = await trigger_svc.maybe_generate_trigger(
            end_user_id=req.end_user_id,
            character_id=req.character_id,
            session_id=req.session_id,
            relationship_stage=rel_state["stage"],
            memories=memories,
        )

    # 6. Time awareness + embodied sensations (needs archetype)
    from ai_core.services.embodiment import build_mid_session_thought, build_sensations
    from ai_core.services.time_awareness import build_time_prompt

    _archetype = (_char_row or {}).get("archetype", "ANIMAL")
    time_context = build_time_prompt(
        rel_state.get("last_interaction_date"),
        archetype=_archetype,
        last_interaction_at=rel_state.get("last_interaction_at"),
    )
    sensations = build_sensations(
        pad=prev_pad,
        touch_gesture=touch_gesture,
        touch_duration_ms=(touch_ctx or {}).get("duration_ms") if touch_ctx else None,
        archetype=_archetype,
    )
    mid_thought = build_mid_session_thought(
        silence_seconds=silence_seconds,
        user_mood=user_mood,
        prev_user_mood=prev_user_mood,
        archetype=_archetype,
    )

    # 6b. Visual-novel events (milestones / romance arc / time-of-day)
    triggered_event, event_context = await _check_events(
        req,
        rel_state=rel_state,
        emotion_state=emotion_state,
        pad_magnitude=prev_pad.magnitude() if prev_pad else 0.0,
        user_text=user_text,
        character_name=(_char_row or {}).get("nickname") or (_char_row or {}).get("name") or "",
    )

    # 7. Build prompt (plain text mode for device/TTS pipelines)
    try:
        prompt_result = await builder.build(
            character_id=req.character_id,
            brand_id=brand_id,
            end_user_id=req.end_user_id,
            user_input=user_text,
            emotion_state=emotion_state,
            user_mood=user_mood,
            memories=memories,
            relationship_stage=rel_state["stage"],
            relationship_state=rel_state if req.end_user_id else None,
            event_context=event_context,
            proactive_trigger=proactive_line,
            time_context=time_context,
            touch_context=touch_prompt,
            sensations=sensations,
            mid_session_thought=mid_thought,
            structured_output=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    sw.mark("context")

    return {
        "user_text": user_text,
        "user_mood": user_mood,
        "emotion_state": emotion_state,
        "touch_gesture": touch_gesture,
        "touch_affinity_bonus": touch_affinity_bonus,
        "rel_state": rel_state,
        "prompt_result": prompt_result,
        "triggered_event": triggered_event,
        "timings": dict(sw.stages),
    }


@router.post("/chat/stream")
@limiter.limit("30/minute")
async def chat_stream(req: ChatRequest, request: Request):
    """Streaming chat: yields SSE events with per-sentence text+audio.

    Events:
      {"type":"sentence","text":"...","audio_data":"base64...","index":0}
      {"type":"sentence","text":"...","audio_data":"base64...","index":1}
      {"type":"done","full_text":"...","emotion":"...","pad":{...},"latency_ms":N}
    """
    start = time.monotonic()
    brand_id = _get_brand_id(request)
    ctx = await _prepare_context(req, brand_id)

    user_text = ctx["user_text"]
    prompt_result = ctx["prompt_result"]
    rel_state = ctx["rel_state"]

    # Audio turns are transcribed here, so only ai-core can spot a vision
    # request the gateway couldn't see. Hand the turn back: the gateway
    # captures a frame and re-issues it as text+image (image_data is then
    # always set, so this cannot loop).
    from ai_core.services.vision import is_vision_trigger

    if req.image_data is None and user_text and is_vision_trigger(user_text):

        async def _need_vision():
            yield _sse({"type": "need_vision", "user_text": user_text})

        return StreamingResponse(_need_vision(), media_type="text/event-stream")

    # Per-turn camera frame: describe via VLM and wrap the utterance with
    # visual context. History/memory keep the plain user_text; only the LLM
    # input carries the visual wrapper. Vision failures degrade to an honest
    # "看不清" turn — never an exception.
    llm_input = user_text
    if req.image_data is not None:  # "" = vision turn whose capture failed
        from ai_core.services.vision import build_vision_turn, describe_image

        t_vlm = time.monotonic()
        try:
            description = await describe_image(req.image_data)
        except Exception:  # degrade to an honest 看不清 turn — never a 500
            logger.exception("pipeline.vision_failed")
            description = None
        ctx["timings"]["vlm"] = (time.monotonic() - t_vlm) * 1000
        llm_input = build_vision_turn(user_text, description)

    async def event_generator():
        # F2 (audit): headers are flushed before this runs — any exception here
        # used to kill the stream silently and the device waited out its idle
        # timeout. Errors now surface as an `error` event and `done` is
        # guaranteed exactly once, in the finally block.
        done_emitted = False
        try:
            async for sse in _event_body():
                if '"type": "done"' in sse or '"type":"done"' in sse:
                    done_emitted = True
                yield sse
        except Exception as exc:
            logger.exception("pipeline.stream_failed")
            yield _sse({"type": "error", "message": str(exc)[:200]})
        finally:
            if not done_emitted:
                yield _sse({"type": "done", "full_text": "", "error": True})

    async def _event_body():
        full_text = ""
        filtered_sentences: list[str] = []
        buffer = ""
        sentence_idx = 0
        # Stage timings: asr/context from _prepare_context, the rest stamped
        # here relative to `start` (request arrival).
        stage_ms: dict[str, float] = dict(ctx["timings"])

        # Stream LLM tokens, split into sentences, TTS each immediately.
        llm = await get_llm_client()
        tts = await get_tts_client()
        # Stream audio chunk-by-chunk only when the caller opted in AND it's
        # globally enabled. Provider capability is checked inside _emit_sentence.
        stream_audio = bool(req.audio_streaming and settings.tts_streaming)
        history = (
            [{"role": m.role, "content": m.content} for m in req.history] if req.history else None
        )
        async for chunk in llm.chat_stream(
            system_prompt=prompt_result["system_prompt"],
            user_input=llm_input,
            history=history,
        ):
            stage_ms.setdefault("llm_first_token", (time.monotonic() - start) * 1000)
            buffer += chunk
            full_text += chunk

            # Check for sentence boundary in buffer
            while True:
                match = _STREAM_SENTENCE_RE.search(buffer)
                if not match:
                    break
                # Extract complete sentence (up to and including delimiter)
                end = match.end()
                sentence = buffer[:end].strip()
                buffer = buffer[end:]

                if not sentence:
                    continue

                sentence = content_filter.filter_output(sentence)
                if not sentence:
                    continue
                filtered_sentences.append(sentence)

                async for sse in _emit_sentence(
                    tts=tts,
                    sentence=sentence,
                    index=sentence_idx,
                    prompt_result=prompt_result,
                    stage_ms=stage_ms,
                    start=start,
                    stream_audio=stream_audio,
                ):
                    yield sse
                sentence_idx += 1

        # Flush remaining buffer
        remaining = buffer.strip()
        if remaining:
            remaining = content_filter.filter_output(remaining)
            if remaining:
                filtered_sentences.append(remaining)
                async for sse in _emit_sentence(
                    tts=tts,
                    sentence=remaining,
                    index=sentence_idx,
                    prompt_result=prompt_result,
                    stage_ms=stage_ms,
                    start=start,
                    stream_audio=stream_audio,
                ):
                    yield sse

        # F16 (audit): assemble the canonical text from the sentences that were
        # actually sent — re-filtering full_text could redact text the user
        # already heard, splitting what's spoken from what's remembered.
        from ai_core.services.emotion import extract_inline_emotion

        _, inline_emotion = extract_inline_emotion(full_text)
        ai_text = extract_inline_emotion(" ".join(filtered_sentences))[0]

        # Emotion update
        emotion_engine = get_emotion_engine()
        text_emotion = inline_emotion or emotion_engine.detect_emotion(
            ai_text, previous=ctx["emotion_state"], user_mood=ctx["user_mood"]
        )
        pad_state, new_emotion = await emotion_engine.update_with_pad(
            session_id=req.session_id,
            text_emotion=text_emotion,
            touch_gesture=ctx["touch_gesture"],
            user_mood=ctx["user_mood"],
            personality=prompt_result.get("personality"),
            relationship_stage=rel_state.get("stage"),
            cause=_derive_mood_cause(
                user_mood=ctx["user_mood"], touch_gesture=ctx["touch_gesture"], rel_state=rel_state
            ),
        )
        mood_causes = await emotion_engine.get_pad_causes(req.session_id)

        # Emotion event — emitted before `done` so devices with expression
        # hardware (LED / servo face) can react while audio is still playing.
        hw = pad_to_hardware(
            pad_state.p,
            pad_state.a,
            pad_state.d,
            species=prompt_result.get("_species", ""),
        )
        yield _sse(
            {
                "type": "emotion",
                "emotion": new_emotion,
                "pad": pad_state.to_dict(),
                "hardware": hw.to_dict(),
                "causes": mood_causes,
                "energy": rel_state.get("energy", 100),
            }
        )

        # Scene card (if an event fired this turn) — after the reply audio
        # queued, before relationship/done, so the choice UI appears with
        # the line it belongs to.
        if ctx.get("triggered_event") is not None:
            yield _sse(ctx["triggered_event"].to_payload())

        # Relationship turn — emitted before `done` so the body can animate
        # the HUD while audio is still playing.
        rel_payload = None
        if req.end_user_id and not req.idle_mode:
            rel_payload = await _apply_relationship_turn(
                req,
                user_mood=ctx["user_mood"],
                user_text=user_text,
                touch_bonus=ctx["touch_affinity_bonus"],
                llm_suggestion=None,
            )
            if rel_payload:
                yield _sse(rel_payload)

        # Done event
        latency = int((time.monotonic() - start) * 1000)
        stages = {k: int(v) for k, v in stage_ms.items()}
        stages["total"] = latency
        latency_tracker.record_turn("chat_stream", stages)
        done_event = {
            "type": "done",
            "full_text": ai_text,
            "user_text": user_text,
            "emotion": new_emotion,
            "pad": pad_state.to_dict(),
            "relationship_stage": rel_payload["stage"] if rel_payload else rel_state["stage"],
            "relationship": rel_payload,
            "latency_ms": latency,
            "stages": stages,
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

        # Async post-processing (idle musings must not create memories)
        if req.end_user_id and not req.idle_mode:
            memory_service = await get_memory_service()
            _spawn(
                memory_service.extract_and_store(
                    end_user_id=req.end_user_id,
                    character_id=req.character_id,
                    session_id=req.session_id,
                    user_input=user_text,
                    ai_response=ai_text,
                )
            )
            _spawn(
                _post_turn_processing(
                    end_user_id=req.end_user_id,
                    character_id=req.character_id,
                    session_id=req.session_id,
                    new_emotion=new_emotion,
                    touch_bonus=ctx["touch_affinity_bonus"],
                )
            )

        logger.info(
            "pipeline.chat_stream", latency_ms=latency, stages=stages, sentences=sentence_idx
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _check_events(
    req: ChatRequest,
    *,
    rel_state: dict,
    emotion_state: str | None,
    pad_magnitude: float,
    user_text: str,
    character_name: str,
) -> tuple[object | None, str]:
    """Trigger this turn's scene (if any) and build the prompt's event context.

    Returns (triggered_event, event_context). Never raises.
    """
    if not req.end_user_id or req.idle_mode:
        return None, ""
    try:
        engine = await get_event_engine()
        parts = []
        last = await engine.last_outcome_context(req.end_user_id, req.character_id)
        if last:
            parts.append(last)
        trig = await engine.check(
            req.end_user_id,
            req.character_id,
            rel_state=rel_state,
            emotion=emotion_state,
            emotion_intensity=min(100.0, pad_magnitude * 60),
            message=user_text,
            character_name=character_name,
        )
        if trig:
            parts.append(trig.prompt_context())
        return trig, "\n".join(parts)
    except Exception:
        logger.exception("events.check_error")
        return None, ""


_MOOD_ZH = {
    "happy": "开心",
    "sad": "难过",
    "angry": "生气",
    "worried": "担心",
    "excited": "兴奋",
    "tired": "累",
    "lonely": "孤单",
}


def _derive_mood_cause(
    *,
    user_mood: str | None,
    touch_gesture: str | None,
    rel_state: dict | None,
    llm_cause: str | None = None,
) -> str | None:
    """One short reason for this turn's mood, for the causality ring.

    Priority: the LLM's own stated reason → a long absence → touch → the
    user's visible mood.  Returns None when nothing notable happened.
    """
    if llm_cause:
        return llm_cause
    if rel_state and rel_state.get("_decay_mood_cause"):
        return rel_state["_decay_mood_cause"]
    if touch_gesture:
        return f"刚被{touch_gesture}了"
    if user_mood and user_mood != "neutral":
        return f"你看起来{_MOOD_ZH.get(user_mood, user_mood)}"
    return None


async def _apply_relationship_turn(
    req: ChatRequest,
    *,
    user_mood: str | None,
    user_text: str,
    touch_bonus: int = 0,
    llm_suggestion: dict | None = None,
) -> dict | None:
    """Move the five-axis relationship for this turn; returns the wire payload.

    Never raises — a relationship hiccup must not break a reply.
    """
    try:
        rel_engine = await get_relationship_engine()
        result = await rel_engine.apply_turn(
            req.end_user_id,
            req.character_id,
            user_mood=user_mood,
            user_text=user_text,
            llm_suggestion=llm_suggestion,
            touch_bonus=touch_bonus,
        )
        return result.to_payload()
    except Exception:
        logger.exception("relationship.apply_turn_error")
        return None


async def _post_turn_processing(
    end_user_id: str,
    character_id: str,
    session_id: str,
    new_emotion: str,
    touch_bonus: int = 0,
) -> None:
    """Async post-turn: personality drift (relationship moved inline via
    ``_apply_relationship_turn`` so the turn's deltas can be streamed)."""
    try:
        memory_svc = await get_memory_service()
        memories = await memory_svc.retrieve_memories(end_user_id, character_id, limit=5)
        recent_types = [m["type"] for m in memories[:3]]

        # Personality drift
        cache = get_cache()
        emotion_key = f"emotion_history:{session_id}"
        raw = await cache.get(emotion_key)
        emotion_list = json.loads(raw) if raw else []
        emotion_list.append(new_emotion)
        await cache.set(emotion_key, json.dumps(emotion_list), ttl=1800)

        drift_svc = await get_personality_drift()
        await drift_svc.compute_and_apply_drift(
            end_user_id=end_user_id,
            character_id=character_id,
            emotion_history=emotion_list,
            memory_types=recent_types,
        )
    except Exception:
        logger.exception("post_turn_processing.error")


@router.post("/touch", response_model=TouchEventResponse)
@limiter.limit("60/minute")
async def touch_event(req: TouchEventRequest, request: Request):
    """Process a touch sensor event. Stores touch context for next chat turn,
    and optionally returns an immediate short verbal reaction."""
    brand_id = _get_brand_id(request)
    touch_engine = get_touch_engine()
    touch_result = await touch_engine.process_touch(
        session_id=req.session_id,
        gesture=req.gesture,
        zone=req.zone,
        pressure=req.pressure,
        duration_ms=req.duration_ms,
    )

    # NOTE: Touch affinity bonus is NOT awarded here to avoid double-counting.
    # It is stored in the touch context cache and awarded once when the next
    # /pipeline/chat turn consumes it via _post_turn_processing(touch_bonus=...).

    # Update character emotion via PAD model (smooth transition)
    emotion_engine = get_emotion_engine()
    pad_state, new_emotion = await emotion_engine.update_with_pad(
        session_id=req.session_id,
        touch_gesture=req.gesture,
    )

    # For strong touch gestures (hug, squeeze), generate an immediate short response
    text_response = None
    audio_b64 = None
    immediate_gestures = ("hug", "squeeze", "shake")
    pctx = None

    if req.gesture in immediate_gestures:
        try:
            builder = await get_prompt_builder()
            # Get archetype for PersonaContext
            from ai_core.services.persona_context import PersonaContext

            _char = await builder._get_character(req.character_id, brand_id)
            pctx = (
                PersonaContext.from_archetype(_char.get("archetype", "ANIMAL")) if _char else None
            )
            prompt_result = await builder.build(
                character_id=req.character_id,
                brand_id=brand_id,
                end_user_id=req.end_user_id,
                user_input="（触摸互动）",
                emotion_state=new_emotion,
                touch_context=touch_result["prompt"],
            )

            llm = await get_llm_client()
            text_response = await llm.chat(
                system_prompt=prompt_result["system_prompt"],
                user_input=pctx.touch_silent_input()
                if pctx
                else "（对方没有说话，只是通过触摸和你互动。用一句简短的话或声音回应。）",
            )

            text_response = content_filter.filter_output(text_response)

            # TTS for immediate response (using PAD-based offsets)
            voice_id = prompt_result.get("voice_id")
            if voice_id and text_response:
                ssml_pitch = prompt_result.get("ssml_pitch", 1.0)
                ssml_rate = prompt_result.get("ssml_rate", 1.0)
                ssml_pitch, ssml_rate = emotion_engine.apply_tts_offsets_pad(
                    pad_state, ssml_pitch, ssml_rate
                )
                tts = await get_tts_client()
                _tts_prepare_for_character(tts, prompt_result)
                audio_bytes = await tts.synthesize(
                    text=text_response,
                    voice=voice_id,
                    speed=prompt_result.get("voice_speed", 1.0),
                    pitch_rate=prompt_result.get("pitch_rate", 0),
                    speech_rate=prompt_result.get("speech_rate", 0),
                    ssml_pitch=ssml_pitch,
                    ssml_rate=ssml_rate,
                    ssml_effect=prompt_result.get("ssml_effect", ""),
                )
                audio_b64 = base64.b64encode(audio_bytes).decode()
        except Exception:
            logger.exception("touch.immediate_response_error")

    logger.info(
        "pipeline.touch",
        gesture=req.gesture,
        zone=req.zone,
        emotion=new_emotion,
        has_response=text_response is not None,
    )

    return TouchEventResponse(
        text=text_response,
        audio_data=audio_b64,
        gesture=touch_result["gesture"],
        intent=touch_result["intent"],
        emotion_hint=new_emotion,
        affinity_bonus=touch_result["affinity_bonus"],
    )
