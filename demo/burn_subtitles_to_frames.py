from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DEFAULT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def main() -> None:
    parser = argparse.ArgumentParser(description="Burn SRT subtitles into a PNG frame sequence.")
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--srt", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--fps", type=float, default=12)
    parser.add_argument("--font", default=DEFAULT_FONT)
    args = parser.parse_args()

    frames_dir = Path(args.frames_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subtitles = parse_srt(Path(args.srt).read_text(encoding="utf-8"))

    font = ImageFont.truetype(args.font, 32)
    small_font = ImageFont.truetype(args.font, 24)

    for frame_path in sorted(frames_dir.glob("frame_*.png")):
        frame_index = int(frame_path.stem.split("_")[-1])
        timestamp = frame_index / args.fps
        active = find_active_subtitle(subtitles, timestamp)

        with Image.open(frame_path).convert("RGBA") as image:
            if active:
                draw_subtitle(image, active, font, small_font)
            image.convert("RGB").save(out_dir / frame_path.name, quality=95)


def parse_srt(text: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        timing = lines[1]
        match = re.match(r"(.+?)\s+-->\s+(.+)", timing)
        if not match:
            continue
        entries.append(
            {
                "start": parse_time(match.group(1)),
                "end": parse_time(match.group(2)),
                "text": " ".join(lines[2:]),
            }
        )
    return entries


def parse_time(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, milliseconds = rest.split(",")
    return (
        int(hours) * 3600
        + int(minutes) * 60
        + int(seconds)
        + int(milliseconds) / 1000.0
    )


def find_active_subtitle(subtitles: list[dict[str, object]], timestamp: float) -> str | None:
    for subtitle in subtitles:
        if float(subtitle["start"]) <= timestamp <= float(subtitle["end"]):
            return str(subtitle["text"])
    return None


def draw_subtitle(image: Image.Image, text: str, font: ImageFont.FreeTypeFont, small_font: ImageFont.FreeTypeFont) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    width, height = image.size

    speaker, line = split_speaker(text)
    wrapped = wrap_text(draw, line, font, int(width * 0.74))
    text_lines = [speaker] + wrapped
    line_heights = [text_bbox(draw, speaker, small_font)[3]] + [text_bbox(draw, row, font)[3] for row in wrapped]
    box_height = sum(line_heights) + 42 + max(0, len(text_lines) - 1) * 6
    box_width = int(width * 0.76)
    x = int((width - box_width) / 2)
    y = height - box_height - 34

    draw.rounded_rectangle((x, y, x + box_width, y + box_height), radius=18, fill=(5, 8, 14, 210), outline=(90, 210, 255, 150), width=2)

    cursor_y = y + 18
    draw.text((x + 28, cursor_y), speaker, font=small_font, fill=(90, 190, 255, 255))
    cursor_y += line_heights[0] + 8
    for row in wrapped:
        draw.text((x + 28, cursor_y), row, font=font, fill=(245, 248, 255, 255))
        cursor_y += text_bbox(draw, row, font)[3] + 6


def split_speaker(text: str) -> tuple[str, str]:
    if ":" in text:
        speaker, line = text.split(":", 1)
        return speaker.strip(), line.strip()
    return "SoulForge", text.strip()


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    rows: list[str] = []
    current = ""
    for char in text:
        candidate = current + char
        if text_bbox(draw, candidate, font)[2] <= max_width or not current:
            current = candidate
        else:
            rows.append(current)
            current = char
    if current:
        rows.append(current)
    return rows


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return left, top, right - left, bottom - top


if __name__ == "__main__":
    main()
