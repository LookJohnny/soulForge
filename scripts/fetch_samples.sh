#!/bin/bash
# Download non-redistributable / large sample models for the humanoid adapter tests.
cd "$(dirname "$0")/.."
mkdir -p assets/vtubers/samples/mixamo
[ -f "assets/vtubers/samples/mixamo/Samba Dancing.fbx" ] || curl -L -o "assets/vtubers/samples/mixamo/Samba Dancing.fbx" \
  "https://raw.githubusercontent.com/mrdoob/three.js/dev/examples/models/fbx/Samba%20Dancing.fbx"
for f in CesiumMan RiggedFigure; do
  [ -f "assets/vtubers/samples/$f.glb" ] || curl -L -o "assets/vtubers/samples/$f.glb" \
    "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/$f/glTF-Binary/$f.glb"
done
ls -la assets/vtubers/samples assets/vtubers/samples/mixamo
