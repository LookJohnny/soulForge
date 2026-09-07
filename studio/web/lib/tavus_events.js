/** Pure Tavus event state; no media playback, network, or brain side effects.
 * Speaking events report provider state, never proof that media reached a user.
 * https://docs.tavus.io/sections/event-schemas/conversation-started-stopped-speaking
 * https://docs.tavus.io/sections/event-schemas/conversation-utterance-streaming
 */
const integer = value => Number.isSafeInteger(value) && value >= 0 ? value : null;
const timestamp = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
const identifier = value => typeof value === 'string' && value.length ? value : null;
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function createTavusEventState(conversationId = null) {
  return {
    conversationId: identifier(conversationId),
    phase: 'idle', speaking: { user: false, pal: false }, caption: null,
    turnIndex: null, lastSequence: null,
    interrupt: { requested: false, confirmed: false, providerStopped: false },
    latency: null,
    _seen: [], _clocks: {}, _captions: {}, _spans: {},
    _pendingUserStop: null, _awaitingResponse: false,
  };
}

/** Accept a Daily app-message {data: envelope} or a direct Tavus envelope. */
export function normalizeTavusEvent(raw) {
  let data = object(raw) && !raw.event_type ? raw.data : raw;
  if (typeof data === 'string') {
    try { data = JSON.parse(data); } catch { return null; }
  }
  if (!object(data) || (data.message_type && data.message_type !== 'conversation')) return null;
  const properties = object(data.properties) ? data.properties : {};
  const legacy = /^conversation\.(user|pal|replica)\.(started_speaking|stopped_speaking)$/.exec(data.event_type);
  const eventType = legacy ? `conversation.${legacy[2]}` : data.event_type;
  const kinds = {
    'conversation.started_speaking': 'started_speaking',
    'conversation.stopped_speaking': 'stopped_speaking',
    'conversation.utterance': 'utterance',
    'conversation.utterance.streaming': 'utterance_streaming',
  };
  if (!Object.hasOwn(kinds, eventType)) return null;
  const roleValue = properties.role ?? legacy?.[1];
  const role = roleValue === 'replica' ? 'pal' : roleValue;
  if (role !== 'user' && role !== 'pal') return null;
  const kind = kinds[eventType];
  if (kind.startsWith('utterance') && typeof properties.speech !== 'string') return null;
  return {
    kind, role, conversationId: identifier(data.conversation_id),
    inferenceId: identifier(data.inference_id), turnIndex: integer(data.turn_idx),
    sequence: integer(data.seq), timestamp: timestamp(data.timestamp),
    text: typeof properties.speech === 'string' ? properties.speech : null,
    contentIndex: integer(properties.content_index),
    final: kind === 'utterance' || properties.final === true,
    interrupted: typeof properties.interrupted === 'boolean' ? properties.interrupted
      : typeof properties.is_interrupted === 'boolean' ? properties.is_interrupted : null,
  };
}

function sameSpan(a, b) {
  if (!a || !b) return false;
  if (a.inferenceId !== null && b.inferenceId !== null) return a.inferenceId === b.inferenceId;
  return a.turnIndex !== null && b.turnIndex !== null && a.turnIndex === b.turnIndex;
}

function phase(state) {
  if (state.interrupt.requested) return 'interrupt_requested';
  if (state.speaking.user) return 'listening';
  if (state.speaking.pal) return 'speaking';
  return state._awaitingResponse ? 'thinking' : 'listening';
}

function providerLatency(stop, start) {
  if (!stop || !start || stop.timestamp === null || start.timestamp === null) return null;
  if (stop.turnIndex !== null && start.turnIndex !== null && stop.turnIndex !== start.turnIndex) return null;
  const delta = (start.timestamp - stop.timestamp) * 1000;
  return delta >= 0 ? {
    providerTurnMs: Math.round(delta), source: 'provider-speaking-events',
    isFirstAudio: false, turnIndex: start.turnIndex,
  } : null;
}

/** Mark local intent only; the caller separately sends conversation.interrupt. */
export function requestTavusInterrupt(state) {
  return { ...state, phase: 'interrupt_requested',
    interrupt: { requested: true, confirmed: false, providerStopped: false } };
}

/** Return the unchanged object for irrelevant, duplicate, foreign, or stale events.
 * Reset with createTavusEventState(newConversationId) when joining another call.
 * Render caption.text as textContent. final means final text, not finished audio.
 */
export function reduceTavusEvent(state, raw) {
  const event = normalizeTavusEvent(raw);
  if (!event || (state.conversationId && event.conversationId && state.conversationId !== event.conversationId)) return state;
  const oldTurn = event.turnIndex !== null && state.turnIndex !== null && event.turnIndex < state.turnIndex;
  // A late stop for the still-active old PAL span may clear that span during
  // barge-in, but cannot replace the new user's caption or roll back the turn.
  const closesActiveSpan = event.kind === 'stopped_speaking' && state.speaking[event.role]
    && sameSpan(event, state._spans[event.role]);
  if (oldTurn && !closesActiveSpan) return state;
  const channel = `${event.role}:${event.kind.startsWith('utterance') ? 'caption' : 'speaking'}`;
  const clock = state._clocks[channel];
  if (clock && event.sequence !== null && clock.sequence !== null && event.sequence <= clock.sequence) return state;
  if (clock && event.sequence === null && event.timestamp !== null && clock.timestamp !== null && event.timestamp < clock.timestamp) return state;
  if (event.kind === 'stopped_speaking' && state.speaking[event.role]
      && event.inferenceId && state._spans[event.role]?.inferenceId
      && event.inferenceId !== state._spans[event.role].inferenceId) return state;
  // Exclude seq when stable span/time metadata exists: legacy role duplicates
  // may receive their own sequence number while describing the same event.
  const key = JSON.stringify([event.kind, event.role, event.turnIndex, event.inferenceId,
    event.timestamp, event.contentIndex, event.text, event.final, event.interrupted,
    event.inferenceId || event.timestamp !== null ? null : event.sequence]);
  if (state._seen.includes(key)) return state;

  const next = { ...state,
    conversationId: state.conversationId || event.conversationId,
    speaking: { ...state.speaking }, interrupt: { ...state.interrupt },
    _seen: [...state._seen.slice(-127), key], _clocks: { ...state._clocks },
    _captions: { ...state._captions }, _spans: { ...state._spans },
  };
  next._clocks[channel] = { sequence: event.sequence ?? clock?.sequence ?? null,
    timestamp: event.timestamp ?? clock?.timestamp ?? null };
  if (event.sequence !== null) next.lastSequence = Math.max(state.lastSequence ?? -1, event.sequence);
  if (event.turnIndex !== null) next.turnIndex = Math.max(state.turnIndex ?? -1, event.turnIndex);

  if (event.kind.startsWith('utterance')) {
    const previous = state._captions[event.role];
    const same = sameSpan(previous, event);
    const streaming = event.kind === 'utterance_streaming';
    // Streaming speech replaces the growing snapshot, never appends it. The
    // legacy full response may include a tail the PAL never actually spoke.
    if (same && previous.source === 'provider-utterance-streaming') {
      if (!streaming || (previous.final && !event.final)) return state;
      if (event.contentIndex !== null && previous.contentIndex !== null && event.contentIndex < previous.contentIndex) return state;
    }
    const caption = {
      role: event.role, text: event.text, final: event.final,
      inferenceId: event.inferenceId, turnIndex: event.turnIndex,
      contentIndex: event.contentIndex, interrupted: event.interrupted,
      source: streaming ? 'provider-utterance-streaming' : 'provider-utterance',
    };
    next.caption = caption;
    next._captions[event.role] = caption;
  } else if (event.kind === 'started_speaking') {
    next.speaking[event.role] = true;
    next._spans[event.role] = event;
    if (event.role === 'user') {
      next._pendingUserStop = null;
      next._awaitingResponse = false;
      next.latency = null;
    } else {
      next._awaitingResponse = false;
      next.latency = !state.speaking.user ? providerLatency(state._pendingUserStop, event) : null;
      next._pendingUserStop = null;
      if (!next.interrupt.requested) next.interrupt = { requested: false, confirmed: false, providerStopped: false };
    }
  } else {
    next.speaking[event.role] = false;
    delete next._spans[event.role];
    if (event.role === 'user' && !oldTurn) {
      const observed = providerLatency(event, state._spans.pal);
      // Provider timestamps can establish ordering even if the data channel
      // delivered the user's stop after the PAL's start.
      if (observed && state.speaking.pal) {
        next.latency = observed;
        next._pendingUserStop = null;
        next._awaitingResponse = false;
      } else {
        next._pendingUserStop = event;
        next._awaitingResponse = true;
      }
    } else if (event.role === 'pal') {
      next.interrupt = { requested: false, confirmed: event.interrupted === true,
        providerStopped: true };
    }
  }
  next.phase = phase(next);
  return next;
}
