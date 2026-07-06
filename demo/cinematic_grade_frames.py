from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply a lightweight cinematic grade to PNG frames.")
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--contrast", type=float, default=1.18)
    parser.add_argument("--saturation", type=float, default=1.16)
    parser.add_argument("--brightness", type=float, default=0.94)
    parser.add_argument("--bloom", type=float, default=0.28)
    parser.add_argument("--vignette", type=float, default=0.42)
    args = parser.parse_args()

    frames_dir = Path(args.frames_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for old_frame in out_dir.glob("frame_*.png"):
        old_frame.unlink()

    for frame_path in sorted(frames_dir.glob("frame_*.png")):
        with Image.open(frame_path).convert("RGB") as image:
            graded = grade_frame(
                image,
                contrast=args.contrast,
                saturation=args.saturation,
                brightness=args.brightness,
                bloom_strength=args.bloom,
                vignette_strength=args.vignette,
            )
            graded.save(out_dir / frame_path.name, quality=95)


def grade_frame(
    image: Image.Image,
    contrast: float,
    saturation: float,
    brightness: float,
    bloom_strength: float,
    vignette_strength: float,
) -> Image.Image:
    image = ImageEnhance.Contrast(image).enhance(contrast)
    image = ImageEnhance.Color(image).enhance(saturation)
    image = ImageEnhance.Brightness(image).enhance(brightness)

    image = split_tone(image)
    image = add_bloom(image, bloom_strength)
    image = add_vignette(image, vignette_strength)
    return image


def split_tone(image: Image.Image) -> Image.Image:
    luma = image.convert("L")
    shadow_mask = luma.point(lambda value: int(max(0, 128 - value) / 128 * 46))
    highlight_mask = luma.point(lambda value: int(max(0, value - 150) / 105 * 42))
    cool = Image.new("RGB", image.size, (0, 28, 70))
    warm = Image.new("RGB", image.size, (255, 155, 64))
    image = Image.composite(ImageChops.screen(image, cool), image, shadow_mask)
    image = Image.composite(ImageChops.screen(image, warm), image, highlight_mask)
    return image


def add_bloom(image: Image.Image, strength: float) -> Image.Image:
    gray = image.convert("L")
    mask = gray.point(lambda value: max(0, (value - 132) * 2))
    glow = Image.composite(image, Image.new("RGB", image.size, (0, 0, 0)), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=10))
    return ImageChops.screen(image, ImageEnhance.Brightness(glow).enhance(strength))


def add_vignette(image: Image.Image, strength: float) -> Image.Image:
    mask = vignette_mask(image.size, strength)
    dark = ImageEnhance.Brightness(image).enhance(0.52)
    return Image.composite(image, dark, mask)


_VIGNETTE_CACHE: dict[tuple[tuple[int, int], float], Image.Image] = {}


def vignette_mask(size: tuple[int, int], strength: float) -> Image.Image:
    cached = _VIGNETTE_CACHE.get((size, strength))
    if cached is not None:
        return cached

    width, height = size
    cx = width * 0.52
    cy = height * 0.48
    max_distance = math.sqrt(cx * cx + cy * cy)
    mask = Image.new("L", size, 255)
    pixels = mask.load()
    for y in range(height):
        for x in range(width):
            distance = math.sqrt((x - cx) ** 2 + (y - cy) ** 2) / max_distance
            factor = 1.0 - strength * max(0.0, distance - 0.22) ** 1.45
            pixels[x, y] = int(255 * max(0.48, min(1.0, factor)))
    _VIGNETTE_CACHE[(size, strength)] = mask
    return mask


if __name__ == "__main__":
    main()
