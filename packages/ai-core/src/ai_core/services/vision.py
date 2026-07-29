"""Camera-frame description via VLM (dashscope compatible-mode, qwen-vl).

One-shot, per-turn vision for the voice pipeline: a device captures a frame
when the user asks "看看这是什么", the frame is described here, and the
description is injected into the LLM turn as visual context. Failures always
degrade to a text marker — the pipeline never blocks or raises on vision.

This is deliberately lighter than engine/perception (frame gating, fusion,
attestation); it serves the commercial gateway path only.
"""

import base64

import httpx
import structlog

from ai_core.config import settings

logger = structlog.get_logger()

VLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
VLM_MODEL = "qwen-vl-plus"
VLM_TIMEOUT_S = 12.0
MAX_IMAGE_B64_LEN = 8_000_000  # ~6MB raw

# Utterances that ask to look through the device camera. The gateway keeps an
# equivalent list for its text path (gateway/server.py VISION_TRIGGERS); this
# one covers turns whose ASR happens inside ai-core, where only we see the text.
VISION_TRIGGERS = (
    "看看这",
    "看看我",
    "看一下这",
    "看一眼",
    "这是什么",
    "这个是什么",
    "我拿的是什么",
    "我手里",
    "你看到了什么",
    "你能看到",
    "前面有什么",
    "帮我看看",
    "识别一下",
    "猜猜这是什么",
)


def is_vision_trigger(text: str) -> bool:
    t = (text or "").replace(" ", "")
    return any(k in t for k in VISION_TRIGGERS)


_DESCRIBE_PROMPT = (
    "用中文简要描述这张照片里的主要物体和场景，两到三句话。"
    "只描述确实可见的内容，不确定的就说不确定，不要猜测品牌或文字以外的细节。"
    "如果画面里有清晰可读的文字，把文字也念出来。"
)


def _detect_mime(image_b64: str) -> str:
    try:
        head = base64.b64decode(image_b64[:16] + "==")
    except Exception:
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    return "image/jpeg"


async def describe_image(image_b64: str) -> str | None:
    """Return a short Chinese description of the frame, or None on any failure."""
    api_key = settings.dashscope_api_key
    if not api_key or not image_b64 or len(image_b64) > MAX_IMAGE_B64_LEN:
        return None
    mime = _detect_mime(image_b64)
    payload = {
        "model": VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{image_b64}"},
                    },
                    {"type": "text", "text": _DESCRIBE_PROMPT},
                ],
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=VLM_TIMEOUT_S) as client:
            resp = await client.post(
                f"{VLM_BASE_URL}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            desc = resp.json()["choices"][0]["message"]["content"].strip()
            logger.info("vision.describe_ok", desc=desc[:80])
            return desc or None
    except Exception as e:
        logger.warning("vision.describe_failed", error=str(e))
        return None


def build_vision_turn(user_text: str, description: str | None) -> str:
    """Wrap the user's utterance with visual context and honesty constraints.

    Mirrors the discipline that worked well on the weizhi robot: the model may
    only relay what the description contains, and must admit failure honestly
    instead of inventing objects.
    """
    if description:
        return (
            f"[摄像头看到的画面] {description}\n"
            f"用户刚才说：{user_text}\n"
            "请基于上面的画面描述自然地回应用户，只谈描述里确实提到的内容，"
            "不要编造描述之外的细节。"
        )
    return (
        f"[摄像头识别失败] 刚才拍照或识别出错了。\n"
        f"用户刚才说：{user_text}\n"
        "请如实告诉用户你现在看不清楚/没看到，让他再试一次，绝对不要凭空猜测你看到了什么。"
    )
