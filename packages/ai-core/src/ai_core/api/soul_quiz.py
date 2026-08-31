"""灵魂问卷 API：拉题 → 提交答案 → 生成专属角色（入库、绑定设备、打包 .soul）。

题库与计分在 services/soul_quiz.py（纯函数）；这里负责：
- 画像写入 PROFILE 记忆层（prompt 会以"隐性长期画像"的方式引用，不直说来源）
- 角色 upsert 进 characters 表（复用 soul_packs.upsert_character_row，含缓存失效与设备绑定）
- 打一个含引擎人格（studio 载荷）与表情参数的 .soul，供 /live 安装进 configs/characters.json
"""

import base64
import json
import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ai_core.api.soul_packs import _get_brand_id, ensure_edge_voice, upsert_character_row
from ai_core.db import get_pool
from ai_core.services import soul_quiz
from ai_core.services.soul_pack_builder import SoulPackBuilder

router = APIRouter(prefix="/soul-quiz", tags=["soul-quiz"])
logger = structlog.get_logger()


@router.get("/questions")
async def get_questions():
    """题库（无需鉴权上下文之外的任何画像；独立 H5 可直接用）。"""
    return {"questions": soul_quiz.QUESTIONS, "version": 1}


@router.get("/status")
async def quiz_status(end_user_id: str | None = None):
    """这个用户测过没有（/live 首次引导判定）。"""
    if not end_user_id:
        return {"taken": False}
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT character_id, raw_source FROM profile_memories "
        "WHERE user_id = $1 AND key = 'quiz:profile' LIMIT 1",
        end_user_id,
    )
    if not row:
        return {"taken": False}
    raw = row["raw_source"]
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    return {
        "taken": True,
        "character_id": str(row["character_id"]) if row["character_id"] else None,
        "character_name": data.get("character_name"),
        "archetype_label": data.get("archetype_label"),
    }


class SubmitRequest(BaseModel):
    answers: dict[str, int] = Field(min_length=1)
    end_user_id: str | None = None
    bind_device: str | None = None  # e.g. "web_vrm-live"
    reroll: int = 0  # 换个名字再来一次


@router.post("/submit")
async def submit_quiz(req: SubmitRequest, request: Request):
    brand_id = _get_brand_id(request)
    try:
        profile = soul_quiz.score(req.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    bundle = soul_quiz.build_character(profile, seed=f"{req.end_user_id}:{req.reroll}")
    pool = await get_pool()

    character = dict(bundle["character"])
    character["personality"] = json.dumps(character["personality"])
    fields = {
        "name": character["name"],
        "archetype": character["archetype"],
        "species": character["species"],
        "backstory": character["backstory"],
        "relationship": character["relationship"],
        "personality": character["personality"],
        "catchphrases": character["catchphrases"],
        "suffix": None,
        "topics": character["topics"],
        "forbidden": character["forbidden"],
        "response_length": character["response_length"],
        "voice_speed": character["voice_speed"],
        "status": "PUBLISHED",
        "emotion_config": json.dumps(character["emotion_config"]),
    }
    try:
        character_id, updated = await upsert_character_row(
            pool, brand_id, fields, upsert_by_name=True, bind_device=req.bind_device
        )
    except Exception as e:
        logger.exception("soul_quiz.upsert_failed")
        raise HTTPException(status_code=500, detail="Failed to create character") from e

    try:
        await ensure_edge_voice(
            pool,
            character_id,
            bundle["voice"]["edge"]["voice"],
            f"{bundle['identity']['name']} · 问卷音色",
        )
    except Exception:
        logger.warning("soul_quiz.voice_profile_failed", exc_info=True)

    if req.end_user_id:
        await _store_profile(pool, req.end_user_id, character_id, profile, bundle)

    # .soul：character + 引擎人格（studio 载荷）+ 表情，供 /live 装进 configs/characters.json
    soul_blob = SoulPackBuilder().build(
        character_data=bundle["character"],
        voice_profile=bundle["voice"],
        embodiment=bundle["engine_entry"]["embodiment"],
        studio=bundle["engine_entry"],
        expression=bundle["expression"],
        author="soul-quiz",
        license_text="personal",
    )

    logger.info(
        "soul_quiz.generated",
        character_id=character_id,
        name=bundle["identity"]["name"],
        archetype=bundle["identity"]["archetype_label"],
        end_user_id=req.end_user_id,
    )
    return {
        "character_id": character_id,
        "updated": updated,
        "card": {
            "name": bundle["identity"]["name"],
            "archetype_label": bundle["identity"]["archetype_label"],
            "tagline": bundle["identity"]["tagline"],
            "color": bundle["identity"]["color"],
            "traits": bundle["engine_entry"]["traits"],
            "speech_style": bundle["engine_entry"]["speech_style"],
            "comfort_line": bundle["engine_entry"]["comfort_line"],
            "voice": bundle["voice"]["edge"],
            "pad": bundle["pad"],
            "behavior": bundle["behavior"],
            "dims": bundle["ai_dims"],
        },
        "engine_entry": bundle["engine_entry"],
        "expression": bundle["expression"],
        "soul_b64": base64.b64encode(soul_blob).decode(),
    }


async def _store_profile(pool, end_user_id, character_id, profile, bundle) -> None:
    """画像 → PROFILE 记忆层：一条原始档 + 两三条可被 prompt 引用的隐性画像句。"""
    dims = bundle["profile_dims"]
    sentences = [
        "用户"
        + (
            "偏内向，独处回血"
            if dims["E"] < 0.45
            else ("外向热络，喜欢有来有往" if dims["E"] > 0.6 else "内外均衡")
        )
        + ("，更想要安静的陪伴" if dims["CALM"] >= 0.5 else "，喜欢被带着玩起来"),
    ]
    if dims["ANX"] >= 0.55:
        sentences.append("用户被在意的人忽略时容易多想，需要及时的回应和确认")
    if dims["AVO"] >= 0.55:
        sentences.append("用户需要自己的空间，难受时倾向自己消化，别追问")
    if dims["DOM"] >= 0.6:
        sentences.append("用户有主见，讨厌被替他做决定")
    elif dims["DOM"] <= 0.4:
        sentences.append("用户在小决定上容易犹豫，适合直接给一个具体建议")
    rows = [
        (
            "quiz:profile",
            f"灵魂问卷画像（{bundle['identity']['archetype_label']}）",
            {
                "dims": dims,
                "prefs": profile["prefs"],
                "character_id": character_id,
                "character_name": bundle["identity"]["name"],
                "archetype_label": bundle["identity"]["archetype_label"],
            },
        )
    ]
    rows += [
        (f"quiz:insight:{i}", text, {"source": "soul_quiz"}) for i, text in enumerate(sentences)
    ]
    for key, content, raw in rows:
        try:
            await pool.execute(
                """INSERT INTO profile_memories
                       (id, user_id, character_id, key, content, raw_source, confidence_score,
                        sensitivity_level, permission_level, retrieval_weight, importance_score,
                        updated_at)
                   VALUES (gen_random_uuid(), $1, $2, $3, $4, $5::jsonb, 0.9,
                           'LOW', 'AUTO', 1.0, 7, now())
                   ON CONFLICT (user_id, character_id, key) DO UPDATE SET
                       content = EXCLUDED.content,
                       raw_source = EXCLUDED.raw_source,
                       updated_at = now()""",
                end_user_id,
                character_id,
                key,
                content,
                json.dumps(raw, ensure_ascii=False),
            )
        except Exception:
            logger.warning("soul_quiz.profile_store_failed", key=key, exc_info=True)


class ExportRequest(BaseModel):
    answers: dict[str, int] = Field(min_length=1)
    passphrase: str | None = None
    reroll: int = 0


@router.post("/export")
async def export_quiz_soul(req: ExportRequest):
    """答案直接换一个 .soul 下载（H5 传播钩子；不入库、不需要设备）。"""
    try:
        profile = soul_quiz.score(req.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    bundle = soul_quiz.build_character(profile, seed=uuid.uuid4().hex[:8] if req.reroll else "")
    blob = SoulPackBuilder().build(
        character_data=bundle["character"],
        voice_profile=bundle["voice"],
        embodiment=bundle["engine_entry"]["embodiment"],
        studio=bundle["engine_entry"],
        expression=bundle["expression"],
        author="soul-quiz",
        license_text="personal",
        passphrase=req.passphrase,
    )
    return {
        "soul_b64": base64.b64encode(blob).decode(),
        "name": bundle["identity"]["name"],
        "archetype_label": bundle["identity"]["archetype_label"],
    }
