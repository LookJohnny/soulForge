# Asset Requirements For Reference-Image Quality

Goal: match the cozy night life-sim / Unity commercial-game look from the
reference image, not the current procedural WebGL prototype.

## Required Scene Assets

Use licensed assets only.

- Apartment shell: loft room, kitchen island, large night window, sofa zone,
  desk zone, shelves, warm pendant lamps, floor lamp, ceiling rails.
- Props: cup, pan, cutting board, plate, books, tablet, keyboard, drawing
  tablet, phone, repair wrench, plant pots, candles, bottles, fridge magnets.
- Lighting: night city HDRI, warm indoor practical lights, neon SoulForge sign,
  reflection probes, baked GI or high-quality realtime URP/HDRP lighting.
- Materials: wood floor, dark cabinets, warm fabric sofa, brushed metal,
  glass window, emissive UI screens, ceramic props, plant leaves.

Recommended safe sources:

- Unity Asset Store: use assets you have licensed under the Asset Store EULA.
- Poly Haven: CC0 HDRIs, textures, and models.
- Kenney: CC0/simple game assets for non-realistic placeholder props.
- Self-authored Blender/Unity assets.

Do not use ripped game assets or assets extracted from commercial games.

## Required Character Assets

Minimum set:

- Female humanoid robot companion.
- Male biped service robot.
- Non-human scout/assistant robot.

Each character should have:

- VRM or humanoid rig compatible with Unity Animator.
- Blend shapes or expression clips for neutral, warm, happy, focused, listening.
- IK targets for both hands and head/look direction.
- Separate material slots for skin/shell, emissive sensors, metal, fabric.
- Voice identity in `SoulForgeBehaviorEvent.voiceClipPath`.

## Required Animation Clips

The current behavior template names are the contract:

- `coffee`
- `cook`
- `sketch`
- `desk`
- `read`
- `call`
- `scan`
- `repair`
- `charge`
- `talk`
- `dance`

Unity Animator should expose triggers with exactly these names. For a first
pass, each state can be a purchased or mocap-derived clip. For production,
add Animation Rigging constraints so hands actually hold props.

## Required Cinematic Setup

Create empty camera anchors named:

- `wide`
- `coffee`
- `kitchen`
- `plant`
- `conversation`
- `sketch`
- `desk`
- `repair`
- `dance`
- `sofa`

Add these anchors to `SoulForgeTimelineDirector.shots`.

## Recorder Acceptance

For a short proof:

- 1920x1080 or 1280x720.
- 30 fps.
- 30 simulated minutes compressed into 60-120 seconds.
- Audio and subtitles enabled.

For the long acceptance target:

- 8 hours of autonomous playback.
- At least 2 fps for validation, 24-30 fps for final showcase if storage and
  render time allow.
- Recorder output must include visible activity changes, not only idle jitter.
- Export the exact behavior replay JSON used for the recording.
