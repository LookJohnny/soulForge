"""Full chat pipeline: (ASR) -> Filter -> Prompt(emotion+memory+relationship) -> LLM -> Filter -> (TTS).

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

from ai_core.dependencies import (
    get_asr_client, get_llm_client, get_prompt_builder, get_tts_client,
    get_emotion_engine, get_memory_service, get_cache,
    get_relationship_engine, get_personality_drift, get_proactive_trigger,
    get_touch_engine,
)
from ai_core.middleware.rate_limit import limiter
from ai_core.models.schemas import ChatRequest, ChatResponse, PADStateSchema, TouchEventRequest, TouchEventResponse
from ai_core.services.content_filter import ContentFilter
from ai_core.services.text_splitter import split_sentences

router = APIRouter(prefix="/pipeline", tags=["pipeline"])
logger = structlog.get_logger()
content_filter = ContentFilter()

MAX_AUDIO_BYTES = 10 * 1024 * 1024


def _get_brand_id(request: Request) -> str:
    auth = getattr(request.state, "auth", None)
    if not auth or not auth.brand_id:
        raise HTTPException(status_code=403, detail="No brand context in auth token")
    return auth.brand_id


@router.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(req: ChatRequest, request: Request):
    start = time.monotonic()
    brand_id = _get_brand_id(request)

    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        audio_bytes = base64.b64decode(req.audio_data)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="Audio data exceeds 10MB limit")
        asr = await get_asr_client()
        user_text = await asr.recognize(audio_bytes)

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        logger.warning("content_filter.blocked_input", reason=reason)
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Detect user mood from text
    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(user_text)
    await emotion_engine.set_user_mood(req.session_id, user_mood)

    # 3b. Check for recent touch context
    touch_engine = get_touch_engine()
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

    # 4. Retrieve memories
    memory_service = await get_memory_service()
    memories = []
    if req.end_user_id:
        memories = await memory_service.retrieve_memories(req.end_user_id, req.character_id)

    # 5. Retrieve relationship state
    rel_engine = await get_relationship_engine()
    rel_state = {"stage": "STRANGER", "affinity": 0}
    if req.end_user_id:
        rel_state = await rel_engine.get_state(req.end_user_id, req.character_id)
        # Limit memories by relationship depth
        depth = rel_engine.get_memory_depth(rel_state["stage"])
        memories = memories[:depth]

    # 6. Proactive trigger (first message of session)
    proactive_line = None
    if req.end_user_id:
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
    time_context = build_time_prompt(rel_state.get("last_interaction_date"))

    # 8. Build prompt (personality with drift + emotion + user mood + memories + relationship + trigger + time)
    builder = await get_prompt_builder()
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
            proactive_trigger=proactive_line,
            time_context=time_context,
            touch_context=touch_prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    # 8. LLM inference
    llm = await get_llm_client()
    ai_text = await llm.chat(
        system_prompt=prompt_result["system_prompt"],
        user_input=user_text,
    )

    # 9. Extract inline emotion tag + content safety filter
    from ai_core.services.emotion import extract_inline_emotion
    ai_text, inline_emotion = extract_inline_emotion(ai_text)
    ai_text = content_filter.filter_output(ai_text)

    # 10. Determine emotion: inline tag > keyword+empathy, then fuse via PAD
    text_emotion = inline_emotion or emotion_engine.detect_emotion(ai_text, previous=emotion_state, user_mood=user_mood)
    pad_state, new_emotion = await emotion_engine.update_with_pad(
        session_id=req.session_id,
        text_emotion=text_emotion,
        touch_gesture=touch_gesture,
        user_mood=user_mood,
        personality=prompt_result.get("personality"),
        relationship_stage=rel_state.get("stage"),
    )

    # 11. TTS with PAD-computed parameters (more nuanced than discrete lookup)
    audio_b64 = None
    if prompt_result.get("voice_id"):
        ssml_pitch = prompt_result.get("ssml_pitch", 1.0)
        ssml_rate = prompt_result.get("ssml_rate", 1.0)
        ssml_pitch, ssml_rate = emotion_engine.apply_tts_offsets_pad(pad_state, ssml_pitch, ssml_rate)

        tts = await get_tts_client()
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

    # 12. Async post-processing (memory + relationship + drift)
    if req.end_user_id:
        asyncio.create_task(
            memory_service.extract_and_store(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                user_input=user_text,
                ai_response=ai_text,
            )
        )
        asyncio.create_task(
            _post_turn_processing(
                end_user_id=req.end_user_id,
                character_id=req.character_id,
                session_id=req.session_id,
                new_emotion=new_emotion,
                touch_bonus=touch_affinity_bonus,
            )
        )

    latency = int((time.monotonic() - start) * 1000)
    logger.info(
        "pipeline.chat",
        latency_ms=latency,
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
        latency_ms=latency,
    )


# ─── Sentence boundary for streaming LLM output ───────────────
_STREAM_SENTENCE_RE = re.compile(r"[。！？；\n.!?;]|(?:\.{3,})|(?:……+)")


async def _prepare_context(req: ChatRequest, brand_id: str):
    """Shared context preparation for both blocking and streaming endpoints."""
    # 1. Determine user text input
    user_text = req.text_input
    if not user_text and req.audio_data:
        audio_bytes = base64.b64decode(req.audio_data)
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=422, detail="Audio data exceeds 10MB limit")
        asr = await get_asr_client()
        user_text = await asr.recognize(audio_bytes, audio_format=req.audio_format)

    if not user_text:
        raise HTTPException(status_code=400, detail="No input provided (text or audio)")

    # 2. Content safety check
    is_safe, reason = content_filter.check_input(user_text)
    if not is_safe:
        raise HTTPException(status_code=400, detail=f"输入内容被拦截: {reason}")

    # 3. Detect user mood + touch context
    emotion_engine = get_emotion_engine()
    user_mood = emotion_engine.detect_user_mood(user_text)
    await emotion_engine.set_user_mood(req.session_id, user_mood)

    touch_engine = get_touch_engine()
    touch_ctx = await touch_engine.get_touch_context(req.session_id)
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

    emotion_state = await emotion_engine.get_emotion(req.session_id)

    # 4. Memories + relationship
    memory_service = await get_memory_service()
    memories = []
    if req.end_user_id:
        memories = await memory_service.retrieve_memories(req.end_user_id, req.character_id)

    rel_engine = await get_relationship_engine()
    rel_state = {"stage": "STRANGER", "affinity": 0}
    if req.end_user_id:
        rel_state = await rel_engine.get_state(req.end_user_id, req.character_id)
        depth = rel_engine.get_memory_depth(rel_state["stage"])
        memories = memories[:depth]

    # 5. Proactive trigger
    proactive_line = None
    if req.end_user_id:
        trigger_svc = get_proactive_trigger()
        proactive_line = await trigger_svc.maybe_generate_trigger(
            end_user_id=req.end_user_id,
            character_id=req.character_id,
            session_id=req.session_id,
            relationship_stage=rel_state["stage"],
            memories=memories,
        )

    # 6. Time awareness
    from ai_core.services.time_awareness import build_time_prompt
    time_context = build_time_prompt(rel_state.get("last_interaction_date"))

    # 7. Build prompt (plain text mode for device/TTS pipelines)
    builder = await get_prompt_builder()
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
            proactive_trigger=proactive_line,
            time_context=time_context,
            touch_context=touch_prompt,
            structured_output=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "user_text": user_text,
        "user_mood": user_mood,
        "emotion_state": emotion_state,
        "touch_gesture": touch_gesture,
        "touch_affinity_bonus": touch_affinity_bonus,
        "rel_state": rel_state,
        "prompt_result": prompt_result,
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

    async def event_generator():
        full_text = ""
        buffer = ""
        sentence_idx = 0

        # Stream LLM tokens, split into sentences, TTS each immediately
        llm = await get_llm_client()
        async for chunk in llm.chat_stream(
            system_prompt=prompt_result["system_prompt"],
            user_input=user_text,
        ):
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

                # TTS this sentence immediately
                audio_b64 = None
                if prompt_result.get("voice_id"):
                    try:
                        tts = await get_tts_client()
                        audio_bytes = await tts.synthesize(
                            text=sentence,
                            voice=prompt_result["voice_id"],
                            speed=prompt_result.get("voice_speed", 1.0),
                            pitch_rate=prompt_result.get("pitch_rate", 0),
                            speech_rate=prompt_result.get("speech_rate", 0),
                        )
                        audio_b64 = base64.b64encode(audio_bytes).decode()
                    except Exception:
                        logger.exception("stream.tts_error")

                event = {
                    "type": "sentence",
                    "text": sentence,
                    "audio_data": audio_b64,
                    "index": sentence_idx,
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                sentence_idx += 1

        # Flush remaining buffer
        remaining = buffer.strip()
        if remaining:
            remaining = content_filter.filter_output(remaining)
            if remaining:
                audio_b64 = None
                if prompt_result.get("voice_id"):
                    try:
                        tts = await get_tts_client()
                        audio_bytes = await tts.synthesize(
                            text=remaining,
                            voice=prompt_result["voice_id"],
                            speed=prompt_result.get("voice_speed", 1.0),
                            pitch_rate=prompt_result.get("pitch_rate", 0),
                            speech_rate=prompt_result.get("speech_rate", 0),
                        )
                        audio_b64 = base64.b64encode(audio_bytes).decode()
                    except Exception:
                        logger.exception("stream.tts_error")

                event = {
                    "type": "sentence",
                    "text": remaining,
                    "audio_data": audio_b64,
                    "index": sentence_idx,
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        # Clean full text for emotion detection
        from ai_core.services.emotion import extract_inline_emotion
        ai_text, inline_emotion = extract_inline_emotion(full_text)
        ai_text = content_filter.filter_output(ai_text)

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
        )

        # Done event
        latency = int((time.monotonic() - start) * 1000)
        done_event = {
            "type": "done",
            "full_text": ai_text,
            "emotion": new_emotion,
            "pad": pad_state.to_dict(),
            "relationship_stage": rel_state["stage"],
            "latency_ms": latency,
        }
        yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"

        # Async post-processing
        if req.end_user_id:
            memory_service = await get_memory_service()
            asyncio.create_task(
                memory_service.extract_and_store(
                    end_user_id=req.end_user_id,
                    character_id=req.character_id,
                    session_id=req.session_id,
                    user_input=user_text,
                    ai_response=ai_text,
                )
            )
            asyncio.create_task(
                _post_turn_processing(
                    end_user_id=req.end_user_id,
                    character_id=req.character_id,
                    session_id=req.session_id,
                    new_emotion=new_emotion,
                    touch_bonus=ctx["touch_affinity_bonus"],
                )
            )

        logger.info("pipeline.chat_stream", latency_ms=latency, sentences=sentence_idx)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _post_turn_processing(
    end_user_id: str,
    character_id: str,
    session_id: str,
    new_emotion: str,
    touch_bonus: int = 0,
) -> None:
    """Async post-turn: relationship scoring + personality drift."""
    try:
        # Relationship scoring
        rel_engine = await get_relationship_engine()
        memory_svc = await get_memory_service()
        memories = await memory_svc.retrieve_memories(end_user_id, character_id, limit=5)
        recent_types = [m["type"] for m in memories[:3]]

        await rel_engine.award_points(
            end_user_id=end_user_id,
            character_id=character_id,
            memory_types=recent_types,
            touch_bonus=touch_bonus,
        )

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
            pctx = PersonaContext.from_archetype(_char.get("archetype", "ANIMAL")) if _char else None
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
                user_input=pctx.touch_silent_input() if pctx else "（对方没有说话，只是通过触摸和你互动。用一句简短的话或声音回应。）",
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
