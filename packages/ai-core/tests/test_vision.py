"""Tests for the per-turn vision service (VLM description + honest degradation)."""

import base64

import pytest

from ai_core.services.vision import _detect_mime, build_vision_turn, describe_image


def test_detect_mime_jpeg_and_png():
    jpeg_b64 = base64.b64encode(b"\xff\xd8\xff\xe0rest").decode()
    png_b64 = base64.b64encode(b"\x89PNG\r\nrest").decode()
    assert _detect_mime(jpeg_b64) == "image/jpeg"
    assert _detect_mime(png_b64) == "image/png"
    assert _detect_mime("!!!not-base64!!!") == "image/jpeg"


def test_build_vision_turn_with_description():
    turn = build_vision_turn("这是什么？", "桌上有一只毛绒企鹅玩具。")
    assert "[摄像头看到的画面]" in turn
    assert "毛绒企鹅" in turn
    assert "这是什么？" in turn
    assert "不要编造" in turn


def test_build_vision_turn_capture_failed():
    turn = build_vision_turn("你看看这是什么", None)
    assert "[摄像头识别失败]" in turn
    assert "你看看这是什么" in turn
    assert "不要凭空猜测" in turn


@pytest.mark.asyncio
async def test_describe_image_degrades_without_key(monkeypatch):
    from ai_core.services import vision

    monkeypatch.setattr(vision.settings, "dashscope_api_key", "")
    assert await describe_image("QUJD") is None


@pytest.mark.asyncio
async def test_describe_image_rejects_oversized(monkeypatch):
    from ai_core.services import vision

    monkeypatch.setattr(vision.settings, "dashscope_api_key", "fake-key")
    assert await describe_image("A" * (vision.MAX_IMAGE_B64_LEN + 1)) is None
