# Local open model and per-sentence expressions

SoulForge can run its chat brain on a local open model served by Nous Tone. Nous Tone lives in the
`AI-Emotion-Experiment/tone` repository and exposes an OpenAI-compatible API, plus tone steering and a
readout probe. The avatar's face then follows the tone of each spoken sentence, read from the model's
residual stream, instead of only the turn-level PAD recipe.

```
user ─► gateway ─► Runtime ─► ai-core /cognition/decide ─► Nous Tone /v1/chat/completions   (one decision)
                                     │
                                     └─► Nous Tone /v1/tone/read  (each dialogue line, split into the TTS sentences)
                                                       │
       dialogue[].tone_readout ─► speak_line.params.tone_readout ─► gateway: one expression cue per TTS sentence
                                                                              │ (sent right before that sentence's clip)
       browser: cue bound to the next clip ─► fired when that clip starts playing ─► VrmBody.setExpressionTarget()
```

## Running it

Set these in the root `.env`. The launcher then starts Nous Tone as a fifth service, before ai-core:

```dotenv
LLM_PROVIDER=nous_tone
LLM_MODEL=Qwen3-1.7B
LLM_BASE_URL=http://127.0.0.1:7880/v1
NOUS_TONE_DIR=/path/to/AI-Emotion-Experiment/tone
NOUS_TONE_MODEL=/path/to/Qwen3-1.7B
NOUS_TONE_PACKS=/path/to/packs/qwen3-1.7b/joy /path/to/packs/qwen3-1.7b/warmth ...   # optional: steering
NOUS_TONE_READOUT=/path/to/packs/qwen3-1.7b/readout_v2                                 # required for expressions
NOUS_TONE_PYTHON=/path/to/venv-with-torch/bin/python
CHARACTER_RUNTIME_TIMEOUT_S=150   # the file wins over launcher defaults: raise it here if it is set
```

Leave `NOUS_TONE_DIR` unset to use a Nous Tone server that you run yourself at `LLM_BASE_URL`.

Optional settings:
- `NOUS_TONE_STEER` / `NOUS_TONE_TARGET`: JSON, for example `{"warmth": 0.8}`. These steer every completion.
- `NOUS_TONE_READ_ENABLED=false`: turns the readouts off.
- `NOUS_TONE_READ_TIMEOUT`: the read timeout, default 5 s.

A local provider never receives `LLM_API_KEY`, which belongs to a hosted provider.

### Defaults when `LLM_PROVIDER=nous_tone`

The launcher applies these only to keys the file doesn't already set.

| Setting | Value | Why |
|---|---|---|
| `LLM_TIMEOUT` | 120 s | A local decision takes seconds, not a hosted API's ~1 s. |
| `SOULFORGE_COGNITION_TIMEOUT_S` | 120 s | Same reason. |
| `RUNTIME_LLM_TIMEOUT` | 120 s | Same reason. |
| `CHARACTER_RUNTIME_TIMEOUT_S` | 150 s | The gateway waits for the whole Runtime decision, so it must outlast cognition. |
| `RUNTIME_AMBIENT_MIN_INTERVAL_S` | 60 s | Limits how often characters notice each other's arrival (see below). |

## What a local model needs (measured on a 16 GB M-series Mac)

### Model size

| Model | Decision JSON valid (6 prompts) | Time per decision | Memory (bf16) |
|---|---|---|---|
| Qwen3-1.7B | 6/6 | ~8–12 s | 3.4 GB |
| Qwen3-4B-Instruct-2507 | 6/6, more natural lines | ~21–25 s | 8 GB |

On this machine 4B thrashes when it runs next to Docker and the stack. Building 4B steering packs also
needs gradients and is not practical here; build them on a GPU machine.

### How the stack adapts to one local model

- **Priority.** A local model serves one completion at a time. User turns (`priority: 1`) go ahead of
  queued autonomous decisions, and tone reads are high priority too. Only Nous Tone receives this
  field; hosted APIs reject unknown arguments, so it is never sent to them.
- **Prefill.** On real user turns, the 1.7B model either echoed the observation JSON or answered in the
  plain-text style of its history, and those decisions were rejected. The reply is now forced to open
  with `{"selected_intent": "`. After this change, no user-turn decision was rejected in the test runs.
- **JSON mode.** With `response_format: json_object`, Nous Tone stops generating as soon as the
  top-level object closes, and returns only that object.
- **Ambient budget.** With five characters, every arrival made each other character run its own
  cognition call, which kept the model busy all the time. The Runtime now makes at most one such
  decision per 60 s. A user's turn is never budgeted.
- **Diagnostics.** `cognition.invalid_decision` now logs which rule a model output broke; it never
  logs user content. Nous Tone logs queue wait, generation time and tokens/s for each request.
  `NOUS_TONE_LOG_TEXT=1` additionally logs outputs, for local debugging only.

For the turn pipeline behind these numbers (lanes, streaming decisions,
preemption, the single reply renderer), see [turn-pipeline.md](turn-pipeline.md).
After that refactor, first audio on 1.7B dropped from 22–27 s to about 6–9 s.

## The face: three changes in `studio/web/lib`

### 1. Direct expression input (`VrmBody.setExpressionTarget(weights, {hold, declared})`)

The per-sentence weights (`happy`, `sad`, `angry`, `surprised`, `relaxed`, `neutral`) bypass the
13-recipe PAD quantization. Each frame they mix with the PAD recipe:

```
target = (1 − blend)·PAD + blend·(cue·gain + neutral·fallback)
```

- **blend** rises at 5/s while a cue holds and falls at 1.2/s after it expires.
- **gain** is `0.6 + 0.4·intensity`, taken from the character's expression profile.
- **neutral** is the share of the sentence the probe cannot attribute to any tone. That share shows
  the line's declared emotion (`dialogue[].emotion`, mapped by `DECLARED_EMOTIONS`). If nothing was
  declared, it shows the PAD mood instead. A neutral reading never blanks the face.
- **Consistency gate.** The probe's worst error on short lines is a valence flip, for example
  "好开心啊…" read as sad 0.56. When the readout's strongest channel contradicts the declared
  emotion's valence and its weight is below 0.9, only 30% of the readout is kept and the rest moves
  to neutral, which the declared emotion then fills.

The result still goes through the existing per-frame damping (2.5/s). PAD keeps driving head pose,
blink rate and gaze.

### 2. Timed to the audio, with per-mouth speaking gain

The gateway sends `{"type":"expression", weights, readout, text, index, declared}` immediately before
the sentence's audio clip. `GatewayClient` binds the cue to the next clip and emits `cue` when that clip
starts on the AudioContext timeline. On the real stack this is about 0.3–0.6 s after the text arrives.
Raw Opus frames work the same way, keyed by frame timestamp.

While speaking, only the mouth gives way to the visemes; the old rule dimmed the whole face to ×0.45:
- **Split drive.** VRoid faces whose `Fcl_ALL_X` exactly equals `BRW_X + EYE_X + MTH_X` (residual under
  2%, checked at load) are driven by part: brows and eyes at full weight, mouth ×0.45. On utsuwa all
  five emotions split exactly, and Joy has 0% of its energy in the mouth part, so its smiling eyes no
  longer dim while she talks.
- **Whole drive.** Other faces scale each expression by its share of deformation in the mouth region.
  The mouth region is the set of vertices the visemes move; for example, AvatarSample_B Joy 0.33,
  Surprised 0.93.

### 3. Per-model channel mapping (`planChannels`)

- **Detection.** Missing channels are found at load. three-vrm maps VRM0 `fun` to `relaxed`, and utsuwa
  also has a custom `Surprised`, so utsuwa has all five channels.
- **Substitutes.** `relaxed` → `happy ×0.5` and `happy` → `relaxed`. `sad`, `angry` and `surprised`
  have no safe substitute; a wrong face is worse than none.
- **Faces with no emotion channels** (rose, robert, polybot: visemes and blink only). Emotions they
  cannot show move the head and gaze instead, using the same head poses as the PAD recipes, and a
  console warning names what is missing. `body.faceInfo` reports
  `{support, missing, fallbacks, split, mouthShare}`.

`VrmBody.load` now ignores a load that a newer load has superseded. Before this, two overlapping
loads, such as the soul-pack avatar and a manual switch, put two models on stage.

## Tests

| Command | Covers |
|---|---|
| `node studio/tests/test_expression_mixer.mjs` | Mixing, the neutral and declared fallback, mapping, speaking gain, and the split check on the real utsuwa / AvatarSample_B vertex data |
| `uv run pytest packages/ai-core/tests/test_tone_reader.py` | Sentence split identical to the gateway's, reader failures falling back to PAD, `priority`/`prefill`/`tone` sent only to Nous Tone, the hosted key never forwarded |
| `uv run pytest packages/gateway/tests/test_expression_cues.py` | Per-sentence cue selection and wire order: cue → sentence → clip, on both text paths |
| `uv run pytest tests/test_ambient_budget.py tests/test_live_stack.py` | The ambient budget and the managed tone service |
| `node studio/tests/test_live_smoke.mjs` | Browser: the cue waits for its clip, the face follows it, the HUD shows "此句 · …" |
| `python -m unittest tests.test_tone` (in `tone/`) | Engine read / priority / prefill / JSON mode / calibration |

## Known limits

- **Readout accuracy.** Single sentences are short, and readout quality is the weakest link. Scores
  are on the 40-line companion dev set (`tone/eval/companion_lines.json`, one annotator, so these
  are dev numbers only):

  | Probe | Accuracy | Valence-correct | Valence flips | Warmth recall |
  |---|---|---|---|---|
  | `readout_v2` (production) | 0.70 | 0.725 | 5 | 0.12 |
  | `readout_v3` (short-reply variants) | 0.725 | 0.725 | 9 | 0.25 |

  v2 is used because it errs toward neutral, which the declared and PAD fallbacks handle, rather
  than toward the opposite valence.
- **Latency.** A user turn takes about 10 s of decision on 1.7B, plus TTS. Fish TTS was unreachable
  from this network during testing (SSL connect error) and fell back to Edge after an ~11 s timeout
  per sentence.
- **Pre-existing issues seen during testing, not changed here:**
  - `voice_speed` stored as a list breaks the character voice lookup in `/tts/synthesize`, which then
    uses the default voice;
  - the provider-status badge covers the top-right toolbar at 1280×800;
  - `test_relationship::test_stage_change_reported` fails on the base commit.
