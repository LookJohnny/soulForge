"""One cognitive decision through AI Core; the runtime remains a body scheduler."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import asdict

from soulforge_harness.runtime.llm_interface import BehaviorDecision, _compact_llm_value
from soulforge_harness.runtime.models import ImpactLevel


class AICoreBehaviorLLM:
    provider_name = "ai-core"

    def __init__(self, base_url: str, *, service_token: str, brand_id: str,
                 user_id: str, character_map: dict | None = None, timeout_s: float = 25):
        if not all((base_url, service_token, brand_id, user_id)):
            raise ValueError("unified cognition requires URL, service token, brand and user identity")
        self.base_url = base_url.rstrip("/")
        self.service_token = service_token
        self.brand_id = brand_id
        self.user_id = user_id
        self.character_map = character_map if character_map is not None else {}
        self.timeout_s = timeout_s
        self.model = "configured-in-ai-core"
        self.last_model = self.model
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def identity_for(self, agent_id: str, supplied: dict | None = None) -> dict:
        from soulforge_harness.runtime.identity import character_id_for_agent

        supplied = supplied or {}
        character_id = self.character_map.get(agent_id) or character_id_for_agent(self.brand_id, agent_id)
        if supplied.get("user_id", self.user_id) != self.user_id:
            raise ValueError("user does not belong to this runtime instance")
        if supplied.get("character_id", character_id) != character_id:
            raise ValueError("character identity does not match the projected agent")
        if supplied.get("agent_id", agent_id) != agent_id:
            raise ValueError("agent identity mismatch")
        return {"user_id": self.user_id, "character_id": str(character_id),
                "agent_id": agent_id, "body_id": supplied.get("body_id") or "runtime",
                "session_id": supplied.get("session_id") or f"{self.user_id}:{character_id}"}

    def decide(self, event, persona, world, current_template, current_interruptible):
        payload = event.payload if isinstance(event.payload, dict) else {}
        identity = self.identity_for(persona.agent_id, payload.get("identity"))
        event_data = asdict(event)
        event_data["kind"] = event.kind.value
        event_data["text"] = event.text[:4000]
        event_data["payload"] = _compact_llm_value({k: v for k, v in payload.items() if k != "identity"})
        data = {"identity": identity, "persona": _compact_llm_value(asdict(persona)),
                "world": world.context_for(persona.agent_id), "event": event_data,
                "current_template": current_template, "current_interruptible": current_interruptible,
                "available_actions": list(world.body_actions.get(persona.agent_id, []))[:40]}
        request = urllib.request.Request(
            f"{self.base_url}/cognition/decide", data=json.dumps(data, ensure_ascii=False).encode(),
            headers={"Content-Type": "application/json", "X-Service-Token": self.service_token,
                     "X-Brand-Id": self.brand_id},
        )
        with self.opener.open(request, timeout=self.timeout_s) as response:
            result = json.load(response)
        raw = dict(result["decision"])
        raw["impact"] = ImpactLevel(raw["impact"])
        fields = BehaviorDecision.__dataclass_fields__
        decision = BehaviorDecision(**{k: v for k, v in raw.items() if k in fields})
        decision.cognitive_state = result.get("authoritative_state") or {}
        decision.provider_status = result.get("provider_status") or {}
        self.last_model = decision.provider_status.get("model") or self.model
        return decision
