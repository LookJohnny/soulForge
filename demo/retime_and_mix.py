"""Audio-first retiming: measure the real fish clips, rewrite beat windows so
subtitles/talk-animation/camera match the voice EXACTLY, then remix the track.

Run AFTER `synthesize --skip-mux --skip-fit` and BEFORE rendering:
    uv run python demo/retime_and_mix.py
Outputs: updated dinner_timeline.json (+voice_events), retimed SRT, voice_mix.m4a
"""

from __future__ import annotations

import glob
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMELINE = ROOT / "demo/vtuber_life_web/dinner_timeline.json"
VOICE_EVENTS = ROOT / "demo/vtuber_life_web/dinner_voice_events.json"
WORK = ROOT / "outputs/webgl/dinner_voice"
GAP = 0.45           # breathing room between lines
TAIL = 0.25         # subtitle lingers this long after the voice stops



def dur(path: str) -> float:
    return float(subprocess.check_output(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", path]))


def main() -> None:
    timeline = json.loads(TIMELINE.read_text("utf-8"))
    beats = timeline["beats"]
    spoken = [b for b in beats if b["text"]]
    clips = sorted(glob.glob(str(WORK / "clip_*[0-9].wav")))
    assert len(clips) == len(spoken), f"{len(clips)} clips vs {len(spoken)} spoken beats"

    durations = [dur(c) for c in clips]
    prev_end = 0.0
    for beat, clip_dur in zip(spoken, durations):
        start = max(beat["start"], prev_end + GAP)
        beat["start"] = round(start, 2)
        beat["end"] = round(start + clip_dur + TAIL, 2)
        beat["audio_dur"] = round(clip_dur, 2)
        prev_end = start + clip_dur

    # 片长自适应：语音结束 + 1.9s 收尾表演，向上取 0.5s
    import math
    TOTAL = max(30.0, math.ceil((prev_end + TAIL + 1.9) * 2) / 2)
    timeline["meta"]["duration_s"] = TOTAL
    finale = [b for b in beats if not b["text"]]
    if finale:
        finale[0]["start"] = round(prev_end + TAIL + 0.1, 2)
        finale[0]["end"] = TOTAL

    # events keep their designed lead-in: user事件在 beat3 前 1.2s，植物事件在 beat5 前 0.6s
    ev = timeline.get("events", [])
    if len(ev) >= 1:
        ev[0]["t"] = round(spoken[2]["start"] - 1.2, 2)
    if len(ev) >= 2:
        ev[1]["t"] = round(spoken[4]["start"] - 0.6, 2)
    for embedded, e in zip([b for b in beats if b.get("event")], ev):
        embedded["event"]["t"] = e["t"]

    TIMELINE.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), "utf-8")

    # voice events (records) + retimed SRT + remix
    voice_events = json.loads(VOICE_EVENTS.read_text("utf-8"))
    for entry, beat in zip(voice_events["events"], spoken):
        entry["time"] = beat["start"]
    VOICE_EVENTS.write_text(json.dumps(voice_events, ensure_ascii=False, indent=2), "utf-8")

    srt_lines = []
    for i, (beat, d) in enumerate(zip(spoken, durations), 1):
        def ts(x): return f"00:00:{int(x):02d},{int((x % 1) * 1000):03d}"
        srt_lines.append(f"{i}\n{ts(beat['start'])} --> {ts(beat['start'] + d)}\n"
                         f"{timeline['agents'][0]['name'] if False else ''}"
                         f"{beat['text']}\n")
    (WORK / "vtuber_life_voiceover.srt").write_text("\n".join(srt_lines), "utf-8")

    # remix at the new offsets
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", str(TOTAL),
           "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    for clip in clips:
        cmd += ["-i", clip]
    delays = ";".join(
        f"[{i+1}:a]adelay={int(b['start']*1000)}|{int(b['start']*1000)},volume=1.05[a{i}]"
        for i, b in enumerate(spoken))
    inputs = "[0:a]" + "".join(f"[a{i}]" for i in range(len(spoken)))
    filt = (f"{delays};{inputs}amix=inputs={len(spoken)+1}:duration=longest:normalize=0,"
            "loudnorm=I=-16:LRA=11:TP=-1.5[a]")
    cmd += ["-filter_complex", filt, "-map", "[a]", "-t", str(TOTAL),
            "-c:a", "aac", "-b:a", "192k", str(WORK / "voice_mix.m4a")]
    subprocess.run(cmd, check=True)

    for beat, d in zip(spoken, durations):
        print(f"  {beat['start']:5.2f}-{beat['end']:5.2f} 音频={d:4.2f}s  {beat['text'][:14]}")
    print(f"retimed: 片长={TOTAL}s，字幕窗口=语音时长+0.25s，全部对齐")


if __name__ == "__main__":
    main()
