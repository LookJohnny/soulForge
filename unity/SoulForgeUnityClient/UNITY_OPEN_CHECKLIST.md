# Unity Open Checklist

Use this after Unity Hub and Unity Editor are installed.

Verified local editor:

```text
/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app
```

`Assets/SoulForge/Scenes/SoulForgeApartment.unity` has already been generated
once through batchmode. Re-run `SoulForge -> Create Apartment Demo Scene` only
when you want to rebuild the blockout scene from the editor script.

1. Open `/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient` as a
   Unity project.
2. Let Package Manager restore packages from `Packages/manifest.json`.
3. Install UniVRM from the official UniVRM release or UPM instructions.
4. Import the three robot character models.
5. Open `Assets/SoulForge/Scenes/SoulForgeApartment.unity`.
6. Create these root objects:
   - `SoulForgeBridge`
   - `SoulForgeDirector`
   - `SoulForgeHUD`
   - `Astra-F`
   - `Mason-M`
   - `Hex-01`
   - `CameraShots`
7. Attach:
   - `SoulForgeBridge` to `SoulForgeBridge`
   - `SoulForgeTimelineDirector` to `SoulForgeDirector`
   - `SoulForgeDialogueHud` to `SoulForgeHUD`
   - `SoulForgeAgentController` to each character
   - `SoulForgeVoiceClipPlayer` to an audio object
8. Assign `Assets/SoulForge/Samples/replay_events.json` to Bridge Replay Json.
9. Add camera anchors listed in `ASSET_REQUIREMENTS.md`.
10. Press Play and verify:
   - agents move to target positions,
   - Animator triggers fire,
   - dialogue text changes,
   - camera shot changes,
   - look-at direction changes during dialogue.
11. Install/configure Unity Recorder and capture a short proof.

Optional command-line rebuild:

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CreateApartmentDemoScene \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_create_scene_richer_v4.log"
```

Optional command-line preview capture:

```bash
"/Applications/Unity/Hub/Editor/6000.5.2f1/Unity.app/Contents/MacOS/Unity" \
  -batchmode -quit \
  -projectPath "/Users/lovelyjoy/Desktop/soulForge/unity/SoulForgeUnityClient" \
  -executeMethod SoulForge.UnityClient.Editor.SoulForgeSceneBuilder.CaptureApartmentPreview \
  -logFile "/Users/lovelyjoy/Desktop/soulForge/outputs/unity/unity_capture_preview_richer_v3.log"
```

Optional Recorder-free demo frame capture:

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

Optional voice and hard-subtitle pass:

```bash
node demo/synthesize_vtuber_voice_track.mjs \
  --video outputs/unity/soulforge_unity_apartment_demo.mp4 \
  --out outputs/unity/soulforge_unity_apartment_demo_voiceover.mp4 \
  --work-dir outputs/unity/unity_voice_demo \
  --mode auto \
  --duration 12 \
  --events-json unity/SoulForgeUnityClient/Assets/SoulForge/Samples/replay_events.json

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
