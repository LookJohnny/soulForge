"""soulforge-harness — portable AI personality infrastructure.

Quickstart::

    from soulforge_harness import Soul, Harness

    soul = Soul.load("luna.soul")            # or Soul.from_quiz(answers)
    h = Harness(soul)                        # OPENAI/DEEPSEEK env, or pass llm=
    print(h.chat("我今天加班到八点，有点累"))
    print(h.relationship["stage"], h.pad)

The facade keeps a full personality loop per turn: persona system prompt →
LLM → relationship axes update (five-axis staged model) → PAD mood update →
rolling memory. Heavier hosts (life simulation, embodiment protocol server)
live in `soulforge_harness.runtime` / `.protocol`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from soulforge_harness.persona import pad as pad_math
from soulforge_harness.persona import relationship as rel
from soulforge_harness.soul import quiz as soul_quiz
from soulforge_harness.soul.pack import SoulPackBuilder

__version__ = "0.1.0"
__all__ = ["Soul", "Harness", "SoulPackBuilder", "__version__"]


class Soul:
    """A character's whole identity: personality, voice, embodiment, expression."""

    def __init__(self, data: dict[str, Any]):
        self.character: dict[str, Any] = data.get("character") or {}
        self.voice: dict[str, Any] = data.get("voice_profile") or {}
        self.embodiment: dict[str, Any] = data.get("embodiment") or {}
        self.expression: dict[str, Any] = data.get("expression") or {}
        self.studio: dict[str, Any] = data.get("studio") or {}
        self.manifest: dict[str, Any] = data.get("manifest") or {}
        self.model_bytes: bytes | None = data.get("model_bytes")

    # -- io -----------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path, passphrase: str | None = None) -> "Soul":
        data = SoulPackBuilder().read(Path(path).read_bytes(), passphrase=passphrase)
        return cls(data)

    def save(self, path: str | Path, passphrase: str | None = None) -> Path:
        blob = SoulPackBuilder().build(
            character_data=self.character,
            voice_profile=self.voice or None,
            embodiment=self.embodiment or None,
            model_bytes=self.model_bytes,
            expression=self.expression or None,
            studio=self.studio or None,
            soul_id=self.manifest.get("soul_id"),
            passphrase=passphrase,
        )
        p = Path(path)
        p.write_bytes(blob)
        return p

    @classmethod
    def from_quiz(cls, answers: dict[str, int], seed: str = "") -> "Soul":
        """Generate a matched companion from soul-quiz answers (23 questions)."""
        bundle = soul_quiz.build_character(soul_quiz.score(answers), seed=seed)
        return cls(
            {
                "character": bundle["character"],
                "voice_profile": bundle["voice"],
                "embodiment": bundle["engine_entry"].get("embodiment") or {},
                "expression": bundle["expression"],
                "studio": bundle["engine_entry"],
            }
        )

    # -- convenience --------------------------------------------------------
    @property
    def name(self) -> str:
        return self.character.get("name", "unnamed")

    @property
    def pad_baseline(self) -> pad_math.PADState:
        base = self.expression.get("pad_baseline")
        if isinstance(base, dict):
            return pad_math.PADState(
                base.get("p", 0), base.get("a", 0), base.get("d", 0)
            ).clamp()
        return pad_math.personality_to_baseline(self._personality())

    def _personality(self) -> dict:
        p = self.character.get("personality") or {}
        return p if isinstance(p, dict) else {}

    def system_prompt(
        self, relationship_state: dict | None = None, mood: str = ""
    ) -> str:
        c = self.character
        parts = [f"你是{self.name}。{c.get('backstory', '')}"]
        traits = self._personality().get("traits") or self.studio.get("traits")
        if traits:
            parts.append(f"性格：{'、'.join(traits)}。")
        style = self.studio.get("speech_style") or self._personality().get(
            "speech_style"
        )
        if style:
            parts.append(f"说话方式:{style}。")
        if c.get("catchphrases"):
            parts.append(f"你常说：{'；'.join(c['catchphrases'][:3])}")
        if c.get("forbidden"):
            parts.append(f"永远不要谈论：{'、'.join(c['forbidden'])}。")
        if relationship_state is not None:
            parts.append(rel.describe_for_prompt(relationship_state))
        if mood:
            parts.append(f"你此刻的心情：{mood}。")
        parts.append("回复用中文，一到三句，像真实的同伴，不要客套，不要自称 AI 模型。")
        return "\n".join(p for p in parts if p)


def _env_llm() -> Callable[[list[dict]], str]:
    """OPENAI-compatible chat completion from env (DEEPSEEK_API_KEY or OPENAI_API_KEY)."""
    key = os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "no LLM configured: pass llm=callable(messages)->str, "
            "or set DEEPSEEK_API_KEY / OPENAI_API_KEY"
        )
    base = os.environ.get(
        "HARNESS_LLM_BASE_URL",
        "https://api.deepseek.com/v1"
        if os.environ.get("DEEPSEEK_API_KEY")
        else "https://api.openai.com/v1",
    ).rstrip("/")
    model = os.environ.get(
        "HARNESS_LLM_MODEL",
        "deepseek-chat" if os.environ.get("DEEPSEEK_API_KEY") else "gpt-4o-mini",
    )

    def call(messages: list[dict]) -> str:
        body = json.dumps(
            {"model": model, "messages": messages, "temperature": 0.7}
        ).encode()
        req = urllib.request.Request(
            f"{base}/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=60) as resp:
            return json.load(resp)["choices"][0]["message"]["content"].strip()

    return call


class Harness:
    """The personality loop around any chat LLM: one soul, persistent inner state."""

    def __init__(
        self,
        soul: Soul,
        llm: Callable[[list[dict]], str] | None = None,
        history_turns: int = 12,
    ):
        self.soul = soul
        self._llm = llm or _env_llm()
        self.history: list[dict] = []
        self.history_turns = history_turns
        self.relationship: dict = rel.default_state()
        self.relationship["first_interaction_at"] = datetime.now(UTC).isoformat()
        self.pad = soul.pad_baseline
        self.memories: list[str] = []

    # -- the loop -----------------------------------------------------------
    def chat(self, text: str, user_mood: str | None = None) -> str:
        rel.apply_time_decay(self.relationship)
        mood_word = pad_math.pad_to_emotion(self.pad)
        system = self.soul.system_prompt(self.relationship, mood=mood_word)
        if self.memories:
            system += "\n你记得的关于用户的事：" + "；".join(self.memories[-8:])
        messages = (
            [{"role": "system", "content": system}]
            + self.history[-self.history_turns * 2 :]
            + [{"role": "user", "content": text}]
        )
        reply = self._llm(messages)
        self._auto_remember(text)
        self.history += [
            {"role": "user", "content": text},
            {"role": "assistant", "content": reply},
        ]
        # relationship: heuristic baseline impact for this turn
        deltas = rel.baseline_impact(
            self.relationship, user_mood=user_mood, user_text=text
        )
        rel.apply_deltas(self.relationship, deltas)
        self.relationship["total_interactions"] = (
            self.relationship.get("total_interactions", 0) + 1
        )
        self.relationship["last_interaction_at"] = datetime.now(UTC).isoformat()
        self.relationship["stage"] = rel.compute_stage(self.relationship)
        # mood: personality-aware transition (user mood pulls, baseline anchors)
        self.pad = pad_math.transition_pad(
            self.pad,
            user_mood_pad=pad_math.USER_MOOD_PAD.get(user_mood or ""),
            baseline=self.soul.pad_baseline,
            relationship_stage=self.relationship.get("stage"),
        )
        return reply

    _MEMORY_CUES = (
        "我叫",
        "叫我",
        "我喜欢",
        "我最喜欢",
        "我讨厌",
        "我不喜欢",
        "我最讨厌",
        "记住",
        "我住在",
        "我的生日",
        "我在做",
        "我的工作",
    )

    def _auto_remember(self, text: str) -> None:
        """Naive declaration capture — the SDK's built-in floor. Hosts with a
        real memory service (ai-core's five layers) replace this loop entirely;
        the facade keeps self-declarations so a bare Harness passes 30-turn
        recall probes without any backend."""
        for sentence in text.replace("，", "。").split("。"):
            sentence = sentence.strip()
            if sentence and any(cue in sentence for cue in self._MEMORY_CUES):
                if sentence not in self.memories:
                    self.memories.append(sentence)
        del self.memories[:-32]

    def remember(self, fact: str) -> None:
        """Explicit long-term memory (the SDK keeps extraction to the host)."""
        self.memories.append(fact.strip())

    @property
    def stage(self) -> str:
        return self.relationship.get("stage", "STRANGER")

    # -- life simulation ----------------------------------------------------
    def life_runtime(self, world=None, llm=None):
        """A CompanionRuntime living this soul's engine persona (studio payload)."""
        from soulforge_harness.runtime import CompanionRuntime, Persona, WorldState

        entry = self.soul.studio or {}
        persona = Persona(
            agent_id=entry.get("id", self.soul.name),
            name=self.soul.name,
            archetype=entry.get("archetype", "default"),
            traits=list(entry.get("traits", [])),
            energy=float(entry.get("energy", 0.7)),
            relationships=dict(entry.get("relationships", {"user": 0.6})),
            daily_goals=list(entry.get("daily_goals", [])),
            meta={
                k: v for k, v in entry.items() if k not in ("id", "name", "archetype")
            },
        )
        return CompanionRuntime([persona], world or WorldState(), llm=llm)
