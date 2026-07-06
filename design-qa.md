# SoulForge Unity Visual QA

Source visual: `/Users/lovelyjoy/Desktop/ig_0aaa0f42f4538644016a4870f7c2f48191a34205b9139ae4aa.png`

Latest implementation:
- Preview: `outputs/unity/soulforge_unity_apartment_preview.png`
- Video: `outputs/unity/soulforge_unity_apartment_demo_voiceover_hardsub_graded.mp4`
- Contact sheet: `outputs/unity/soulforge_unity_apartment_demo_contact_sheet_graded.jpg`

What now works:
- Unity scene generation and frame capture complete without compile errors.
- 12-second demo video records at 1280x720, 12 fps, 144 frames.
- AAC voice mix is present for the full video duration.
- Hard subtitles are burned into the final video.
- Screen-space game HUD is captured into the frames.
- CC0 3D furniture/character assets replace most primitive set dressing.
- Offline cinematic grade adds stronger contrast, color, bloom, and vignette.

Blocking gaps against the reference:
- Final result: blocked.
- The current Kenney CC0 low-poly assets do not reach the reference image's commercial Unity/illustrated game fidelity.
- Characters are still prototype-grade and do not match VTuber/UniVRM character quality.
- The apartment set lacks high-resolution materials, realistic foliage, dense clutter, and physically believable soft lighting.
- HUD layout is structurally similar but not yet polished to reference-level spacing, typography, borders, and portrait quality.
- Autonomous activity is present through camera/action events, but motions still read as template loops rather than full body performance.

Required to pass the reference standard:
- Import production-grade VRM or FBX characters for female, male, and non-human robot roles.
- Use a paid or high-quality free apartment/loft Unity environment pack with PBR materials.
- Add real animation clips or IK-driven task animations for cooking, drawing, plant care, repair, and conversation.
- Replace prototype HUD with textured portrait assets, icons, and a polished layout.
- Use Unity Recorder/Cinemachine/URP or HDRP post-processing for native bloom, depth of field, and color grading.
