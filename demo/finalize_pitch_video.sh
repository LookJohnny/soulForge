#!/bin/bash
# Post-production (audio-first pipeline):
#   前置：generate → synthesize --skip-mux --skip-fit → retime_and_mix → render
#   本脚本：grade → mux(已重排的 voice_mix + srt) → music → deliverables
set -euo pipefail
cd "$(dirname "$0")/.."

FRAMES=outputs/webgl/dinner_pitch_frames
MASTER=outputs/webgl/dinner_pitch_master.mp4
FINAL=outputs/webgl/dinner_pitch_final.mp4
VOICE=outputs/webgl/dinner_voice/voice_mix.m4a
SRT=outputs/webgl/dinner_voice/vtuber_life_voiceover.srt
MUSIC=assets/audio/wholesome_kevin_macleod.ogg
DUR=$(python3 -c "import json;print(json.load(open('demo/vtuber_life_web/dinner_timeline.json'))['meta']['duration_s'])")
FADE_ST=$(python3 -c "print($DUR-4.0)")

echo "[1/4] grade + encode master (${DUR}s)"
ffmpeg -y -v error -framerate 24 -i "$FRAMES/frame_%06d.png" -vf "\
eq=contrast=1.05:saturation=1.07,\
colorbalance=rs=.02:rm=.012:bs=-.014:bm=-.008,\
vignette=angle=PI/4.8,\
noise=alls=3:allf=t+u,\
unsharp=5:5:0.3" \
  -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p "$MASTER"

echo "[2/4] mux retimed voice + subtitles"
ffmpeg -y -v error -i "$MASTER" -i "$VOICE" -i "$SRT" \
  -map 0:v -map 1:a -map 2:s -c:v copy -c:a copy -c:s mov_text \
  -metadata:s:s:0 language=chi outputs/webgl/dinner_pitch_voiced.mp4

echo "[3/4] music bed (Wholesome — Kevin MacLeod, CC BY 4.0)"
ffmpeg -y -v error -i outputs/webgl/dinner_pitch_voiced.mp4 -ss 1.2 -i "$MUSIC" -filter_complex "\
[1:a]atrim=0:$DUR,volume=0.13,afade=t=in:d=2.2,afade=t=out:st=$FADE_ST:d=4.0[m];\
[0:a][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[a]" \
  -map 0:v -map "[a]" -map 0:s? -c:v copy -c:a aac -b:a 192k -c:s mov_text "$FINAL"

echo "[4/4] contact sheet + keyframes"
N=$(python3 -c "print(int($DUR*24//10))")
ffmpeg -y -v error -i "$FINAL" -vf "select='not(mod(n,$N))',scale=480:270,tile=5x2" -frames:v 1 \
  outputs/webgl/dinner_pitch_contact_sheet.jpg
mkdir -p outputs/webgl/dinner_pitch_keyframes
KFS=$(python3 -c "
d=$DUR
pts=[0.5]+[round(d*f,1) for f in (0.08,0.2,0.33,0.45,0.58,0.7,0.82,0.92)]+[round(d-1.2,1)]
print(' '.join(str(p) for p in pts))")
for t in $KFS; do
  ffmpeg -y -v error -ss "$t" -i "$FINAL" -frames:v 1 "outputs/webgl/dinner_pitch_keyframes/kf_$t.png"
done
ffprobe -v quiet -show_entries format=duration,size -of default=noprint_wrappers=1 "$FINAL"
echo "DONE -> $FINAL"
