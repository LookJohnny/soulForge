# SoulForge Unity Visual Client

This folder is a Unity handoff project for the game-quality visual layer.
This project has been opened and compiled locally with Unity 6
`6000.5.2f1`. The bootstrap apartment scene has been generated through
Unity batchmode at `Assets/SoulForge/Scenes/SoulForgeApartment.unity`.

## Target Role

SoulForge remains the behavior engine:

- 24-hour planning and minute-level activity expansion.
- LLM behavior planning that selects safe action templates.
- Voice synthesis, subtitles, emotion metadata, and relationship state.
- MuJoCo or hardware backends for physical validation.

Unity becomes the presentation and recording frontend:

- Licensed apartment/game environment assets.
- UniVRM character loading.
- Animator / IK / timeline-driven action clips.
- Cinematic camera, lighting, post processing, and Recorder capture.

## Verified Unity Setup

- Unity 6 `6000.5.2f1` is verified on this machine.
- The current `Packages/manifest.json` is intentionally kept to an offline
  minimal set that resolves with the installed editor cache.
- URP for fast iteration, HDRP only if you need higher-end desktop renders.
- UniVRM for `.vrm` model import.
- Animation Rigging package for hand IK and look-at constraints.
- Cinemachine for shot changes.
- Unity Recorder for long video output.

Animation Rigging, Cinemachine, UniVRM, and Recorder should be installed from
their official package sources once Unity Package Manager network access is
stable. They are not required for the generated blockout scene to compile.

The project already includes `Packages/manifest.json`, basic
`ProjectSettings`, a SoulForge assembly definition, replay samples, and runtime
bridge scripts.

Do not use ripped commercial game assets. Use assets you own, Unity Asset
Store assets under their license, or CC0 sources such as Poly Haven and Kenney.

## Import Steps

1. Open this folder from Unity Hub:
   `/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient`
2. Let Package Manager restore packages from `Packages/manifest.json`.
3. Install UniVRM and import your VRM characters.
4. Add an empty GameObject named `SoulForgeBridge`.
5. Attach `SoulForgeBridge`, `SoulForgeTimelineDirector`, and one
   `SoulForgeAgentController` per character.
6. Drag `Samples/replay_events.json` into the `Replay Json` field for offline
   testing.
7. Press Play. The bridge replays SoulForge behavior events and drives
   character actions, camera shots, dialogue, and optional voice clips.

Fast bootstrap inside Unity Editor:

```text
Menu: SoulForge -> Create Apartment Demo Scene
```

This creates `Assets/SoulForge/Scenes/SoulForgeApartment.unity` with a richer
night apartment graybox, camera anchors, diegetic HUD panels, replay bridge,
and three distinct procedural robot architectures: Astra-F, Mason-M, and
Hex-01. Replace the procedural placeholders with licensed VRM/robot assets for
final quality.

Verified batchmode bootstrap from the repo root:

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CreateApartmentDemoScene \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_create_scene_richer_v4.log"
```

Verified preview capture:

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CaptureApartmentPreview \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_capture_preview_richer_v3.log"
```

Recorder-free demo capture fallback:

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CaptureApartmentDemoFrames \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_capture_demo_frames_v3.log"

ffmpeg -y -framerate 12 \
  -i outputs/unity/apartment_demo_frames/frame_%04d.png \
  -c:v libx264 -pix_fmt yuv420p -movflags +faststart \
  outputs/unity/soulforge_unity_apartment_demo.mp4
```

Add replay-aligned voice, soft subtitles, and a voice manifest:

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/unity/soulforge_unity_apartment_demo.mp4 \
  --out outputs/unity/soulforge_unity_apartment_demo_voiceover.mp4 \
  --work-dir outputs/unity/unity_voice_demo \
  --mode auto \
  --duration 12 \
  --events-json unity/SoulForgeUnityClient/Assets/SoulForge/Samples/replay_events.json
```

Burn subtitles into the frame sequence for players that do not show embedded
`mov_text` subtitles:

```bash
python3 demo/burn_subtitles_to_frames.py \
  --frames-dir outputs/unity/apartment_demo_frames \
  --srt outputs/unity/unity_voice_demo/vtuber_life_voiceover.srt \
  --out-dir outputs/unity/apartment_demo_hardsub_frames \
  --fps 12

ffmpeg -y -framerate 12 \
  -i outputs/unity/apartment_demo_hardsub_frames/frame_%04d.png \
  -i outputs/unity/unity_voice_demo/voice_mix.m4a \
  -c:v libx264 -pix_fmt yuv420p \
  -c:a aac -b:a 192k -movflags +faststart \
  outputs/unity/soulforge_unity_apartment_demo_voiceover_hardsub.mp4
```

Detailed Unity opening steps are in `UNITY_OPEN_CHECKLIST.md`.
Asset requirements are in `ASSET_REQUIREMENTS.md`.

## Runtime Event Schema

```json
{
  "time": 3.95,
  "agentId": "mason",
  "agentName": "Mason-M",
  "actionTemplateId": "cook",
  "dialogue": "厨房执行器上线，热源保持安全距离。",
  "emotion": "calm",
  "cameraShot": "kitchen",
  "lookAtAgentId": "astra",
  "targetPosition": { "x": -0.18, "y": 0, "z": -0.72 },
  "voiceClipPath": "voice/mason_001.wav",
  "priority": "PLAN"
}
```

The production bridge should receive the same event shape over WebSocket or
read it from a JSONL replay file exported by the SoulForge engine.

Export a local replay file from the repo root:

```bash
node demo/export_unity_behavior_events.mjs \
  --out outputs/unity/soulforge_unity_replay_events.json \
  --duration 12
```

To refresh the Unity sample replay:

```bash
node demo/export_unity_behavior_events.mjs \
  --out unity/SoulForgeUnityClient/Assets/SoulForge/Samples/replay_events.json \
  --duration 12
```

## Acceptance Path

For the visual target in this thread, the next real step is:

1. Build a Unity apartment scene with licensed assets.
2. Import at least three robot architectures: female humanoid, male biped,
   and non-human robot.
3. Bind these template names to Animator states: `coffee`, `cook`, `sketch`,
   `desk`, `read`, `call`, `scan`, `repair`, `charge`, `talk`, `dance`.
4. Add hand IK targets for cup, pan, tablet, book, phone, wrench, and plant
   scanner props.
5. Use Unity Recorder to capture 8-hour autonomous playback.

Current WebGL output is a runnable prototype. Unity is the correct path for
the reference-image quality bar.
