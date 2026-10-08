# The turn pipeline (2026-10 refactor)

How one user utterance becomes speech, and why each stage looks the way it does.
The refactor was driven by measurements on a local model (Qwen3-1.7B on a 16 GB
Mac). On that setup, first audio took 22–27 s. It now takes about 6–9 s.

```
gateway                         Runtime (engine/server)                   AI Core                 Nous Tone
───────                         ───────────────────────                   ───────                 ─────────
turn task ─ event ────────────► lane[agent].user ─ prepare (loop thread)
                                PriorityGate (1 slot kept for users)
                                think (thread) ─ POST /cognition/decide/stream ─► prompt, LLM stream ─► generate (priority 1)
                                     ◄── line ──────────────────────────────────── line complete ◄──── dialogue first
                                speak_early (loop) ─ action ──► TTS(line) ─► device       │ tone read (between tokens)
                                     ◄── result ─────────────────────────────── rest of decision, state
                                commit (loop): plan, body actions, no repeated lines
                                decision_complete (+cognitive_state) ─► mood chunk, done
```

## Runtime: lanes instead of one serial worker (`engine/server/scheduler.py`)

**Before.** One worker ran every event for every agent in FIFO order, so a user's
utterance waited behind any character's arrival notice. That decision ran in a
thread, and the thread mutated plans, history and the trace while `tick()` used
them on the loop thread. Actions and trace entries could be lost.

**Now:**
- **`prepare_event / think / commit`** (`CompanionRuntime`). Only `think`, which
  is the model call, leaves the loop thread, so runtime state has a single writer.
- **Per-agent lanes.** Each lane serves its user queue before its ambient one,
  using the event classes from `event_class`:
  - `user`: an utterance, or a body's event that has a reply body.
  - `droppable`: an arrival notice or a proactive line.
  - `ambient`: a conversation turn or deferred motion, which must still complete.
- **`PriorityGate`.** At most `--max-concurrent-decisions` model calls run at once
  (default 2), and ambient work never takes the last slot.
- **Preemption.** A user event preempts its agent's in-flight droppable decision,
  and that decision's result is discarded. The model call also stops early (see
  Nous Tone below).
- **Ambient budget.** Set with `RUNTIME_AMBIENT_MIN_INTERVAL_S`. It is per agent,
  applies only to droppable events, and never to conversation turns. A
  conversation's opening event is also `agent_state`, and budgeting it away would
  freeze the conversation.
- **Quiet fallback.** When a droppable decision fails, the result is a silent beat
  instead of the canned "嗯，我听着呢。". User turns, perception events and a
  configured mock keep the deterministic fallback.

## Streaming decisions (speech before the decision is complete)

**AI Core.** `POST /cognition/decide/stream` emits NDJSON:
`{"type":"line"}` for each line, then `{"type":"result"}` or `{"type":"error"}`.
- **Dialogue first.** The hint lists `dialogue` first and says the remaining
  fields must follow. On a user turn the prefill
  `{"dialogue": [{"agent": "<id>", "text": "` pins the speaker. An autonomous
  turn only opens the array, so it may stay silent.
- **Line extraction.** `DialogueStream` hands over each array element as its
  closing brace arrives, wherever the array sits in the object.
- **Each line is admitted on its own:** the speaker must be this agent, the
  output filter runs on it, and its tone is read before it is handed over.
- **Lenient fallback.** Once a line has been spoken it cannot be retracted. A
  malformed non-speech field therefore degrades the decision to the quietest
  valid plan rather than a 503. A decision that is invalid with nothing spoken
  still fails as before.

**Runtime.**
- `AICoreBehaviorLLM.decide_stream` reads the NDJSON.
- `SafeDecisionLLM` relays each line to the scheduler, which hops to the loop and
  calls `speak_early`.
- If the stream is cut, the decision keeps the lines already spoken and adds no
  canned speech.
- `commit` drops the `speak_line` actions for lines already spoken.
- `decision_complete` now carries `cognitive_state`, because every line may have
  been spoken before any state existed.

**Gateway.**
- `CharacterBridge.stream_event` yields each action as it arrives and ends at
  `decision_complete`. The old 0.6 s quiet window used to cut multi-line turns.
- `_runtime_text_stream` synthesizes each line as soon as it arrives, so TTS of
  line 1 overlaps generation of line 2.
- A turn the gateway gave up on is expired. Its late lines are rejected, not
  replayed as unsolicited speech in the middle of the next turn.

## Gateway: one reply renderer (`gateway/reply.py`)

**Before.** Voice (streaming ASR), batch ASR and text turns were three copies of
the same ~120-line loop.

**Now:**
- **`render_turn` plus a `TurnStyle`.** The style says how the device plays the
  turn: voice turns are paced and support barge-in; text turns are free-buffered.
- **One speaker per session.** `speech_lock(session)` makes user turns,
  unsolicited Runtime speech and touch replies play one at a time.
- **Turns off the receive loop.** Turns run as per-session tasks (`_spawn_turn`).
  The socket keeps reading abort, barge-in audio and camera frames during a
  decision, and abort cancels the turn.
- **Microphone re-arming.** `_rearm_listening` re-arms the microphone, with its
  PCM16/Opus format, after every voice turn. Before, a browser mic went deaf
  after one successful turn.

## Other fixes found by the audits

| Area | Fix |
|---|---|
| Model sharing (Nous Tone) | `priority` is a priority lock. `preemptible` lets background generations stop for a waiting user (non-stream: HTTP 409). Tone reads run between the active generation's tokens; they used to wait for the whole decision. |
| TTS | Circuit breaker: after a primary TTS failure the fallback is used for `TTS_BREAKER_S` (60 s). Before, an unreachable Fish cost a ~10 s connect timeout on every sentence. |
| AI Core | The local provider makes no SDK retries; before, a slow generation could be re-run up to 3 times. Logging and declared-memory writes are best effort and run alongside the state chain, so a logging failure no longer turns a generated reply into a 503. The schema no longer asks for `memory_update` and caps the free-text fields that are only logged. |
| Data | `hasattr(v, "hex")` also matched floats. `voice_speed` 1.0 became `"1.0"`, so the character voice silently fell back to the default in `/tts/synthesize`. Memory rows had the same bug. |
| Gateway | Fixed: receipt double-confirmation; sentences over the TTS limit are split; non-numeric latency stages no longer crash a turn; text-only clients are no longer idle-closed while chatting; no vision capture on the Runtime path, which ignores images; the ASR session no longer leaks on a repeated `listen start`. |
| Tests | `test_relationship` used a fixed date against wall-clock decay; it has failed since late August. |

## Prompt layout: a static head, so the prefill is reused

A local model spent about 3 s on every turn just reading a ~2.2k-token prompt.
The order is now chosen so most of it is identical from turn to turn, and Nous
Tone reuses the cached KV of a matching prompt head:

1. **System prompt.** It holds the character, style, rules, contract and schema,
   and is byte-identical across turns. `PromptBuilder.build(defer_dynamic=True)`
   leaves the per-turn sections out of it.
2. **History.** It is trimmed in blocks (16, then the last 8), not as a sliding
   window, so most turns only append to it.
3. **Last message.** It carries the moment, mood, relationship numbers,
   memories and retrieved knowledge (`templates/now_block.jinja2`), then the
   current PAD, then the observation JSON. On a user turn, the user's words come
   last as an escaped JSON string, so they can't close their quote and pose as
   instructions.

The system prompt is identical across comparable turns: same character, same
kind of turn and same contract inputs. Three things still change it:
- the relationship stage (rare; each change invalidates the cache once);
- user versus autonomous turns, which get different contract text, so each kind
  keeps its own cached prefix (Nous Tone holds several);
- on autonomous turns, the current activity named in the silent-turn example.

Keep per-turn content out of the system prompt. Anything that changes per turn
and is placed early breaks the prefix for everything after it.

## History must not teach parroting

A small model imitates its own past replies. One reply that only echoed the user
entered the history, and from then on most replies were echoes. A line that only
repeats the user (`echoes()`) is still spoken, but it is never written to history.

## Measured (local Qwen3-1.7B, real stack)

| | Before | After |
|---|---|---|
| User request waiting behind ambient generation | 4–8 s, sometimes a timeout | 0–1 s (preempted) |
| Gap between sentences (Fish unreachable) | ~12 s | ~2 s |
| First audio after the user's message | 22–27 s | ~6–9 s; ~4–5 s with prefix reuse (from the 2nd turn) |
| Prompt tokens prefilled per turn | ~2.2k | ~0.7–0.9k (1.3–1.5k reused) |
| Decision output | 110–160 tokens | 85–105 tokens |

Remaining costs:
- Prompt prefill: now about 1 s; only the changed part is read.
- Decode: the first line completes after about 2–3 s.
- TTS.

With 1.7B, reply quality is the limit. The habit of echoing the user's question
came mostly from echoed replies left in history; that is now prevented (see
above). 4B is still clearly better, but it needs more memory than this Mac can
spare next to the stack.
