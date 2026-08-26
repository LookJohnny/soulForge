"""Tests for the structured LLM response parser — the choke point every
LLM reply passes through. Covers all parse paths: clean JSON, fenced JSON,
fix-ups, YAML-like fallback, concatenated fragments, and plain-text fallback."""

import json

from ai_core.services.response_parser import (
    PADValues,
    VoiceParams,
    parse_llm_response,
)


class TestCleanJson:
    def test_full_structured_response(self):
        raw = json.dumps(
            {
                "dialogue": "嗯，你好啊。",
                "action": "嘴角微微上扬",
                "thought": "又来了",
                "pad": {"p": 0.5, "a": 0.3, "d": 0.6},
                "voice": {"speed": 1.05, "pitch": 0.02, "tone": "teasing"},
                "stance": "teasing",
            },
            ensure_ascii=False,
        )
        resp = parse_llm_response(raw)
        assert resp.parsed_ok
        assert resp.dialogue == "嗯，你好啊。"
        assert resp.action == "嘴角微微上扬"
        assert resp.thought == "又来了"
        assert resp.pad.p == 0.5
        assert resp.voice.tone == "teasing"
        assert resp.stance == "teasing"

    def test_markdown_fenced_json(self):
        raw = '好的，以下是回复：\n```json\n{"dialogue": "在呢", "action": "抬头"}\n```'
        resp = parse_llm_response(raw)
        assert resp.parsed_ok
        assert resp.dialogue == "在呢"
        assert resp.action == "抬头"

    def test_json_with_preamble(self):
        raw = '这是我的回复 {"dialogue": "晚上好", "thought": "有点困"}'
        resp = parse_llm_response(raw)
        assert resp.parsed_ok
        assert resp.dialogue == "晚上好"

    def test_text_key_alias(self):
        resp = parse_llm_response('{"text": "你好", "action": ""}')
        assert resp.dialogue == "你好"


class TestSilentReplies:
    def test_empty_dialogue_with_action_is_valid(self):
        """被抱时蹭一下——dialogue 为空但 action 有值是合法回复。"""
        resp = parse_llm_response('{"dialogue": "", "action": "轻轻蹭了蹭"}')
        assert resp.parsed_ok
        assert resp.dialogue == ""
        assert resp.action == "轻轻蹭了蹭"

    def test_empty_dialogue_with_thought_is_valid(self):
        resp = parse_llm_response('{"dialogue": "", "thought": "……不想说话"}')
        assert resp.parsed_ok
        assert resp.thought == "……不想说话"

    def test_all_empty_falls_back_to_raw(self):
        resp = parse_llm_response('{"dialogue": "", "action": "", "thought": ""}')
        assert not resp.parsed_ok


class TestPadAndVoice:
    def test_pad_clamped_to_unit_range(self):
        resp = parse_llm_response('{"dialogue": "x", "pad": {"p": 5, "a": -3, "d": 0.2}}')
        assert resp.pad.p == 1.0
        assert resp.pad.a == -1.0
        assert resp.pad.d == 0.2

    def test_pad_as_list(self):
        resp = parse_llm_response('{"dialogue": "x", "pad": [0.1, 0.2, 0.3]}')
        assert (resp.pad.p, resp.pad.a, resp.pad.d) == (0.1, 0.2, 0.3)

    def test_pad_garbage_defaults_to_zero(self):
        resp = parse_llm_response('{"dialogue": "x", "pad": {"p": "high", "a": null}}')
        assert (resp.pad.p, resp.pad.a, resp.pad.d) == (0.0, 0.0, 0.0)

    def test_voice_speed_clamped(self):
        resp = parse_llm_response('{"dialogue": "x", "voice": {"speed": 9.9, "pitch": -1}}')
        assert resp.voice.speed == 1.3
        assert resp.voice.pitch == -0.15

    def test_voice_params_to_ssml_clamps(self):
        ssml = VoiceParams(speed=1.3, pitch=0.15, tone="whisper").to_ssml()
        assert 0.5 <= ssml["ssml_pitch"] <= 2.0
        assert 0.5 <= ssml["ssml_rate"] <= 2.0
        assert ssml["ssml_effect"] == "lolita"

    def test_pad_values_clamp(self):
        pad = PADValues(p=2.0, a=-2.0, d=0.5).clamp()
        assert (pad.p, pad.a, pad.d) == (1.0, -1.0, 0.5)


class TestFixups:
    def test_trailing_comma_fixed(self):
        resp = parse_llm_response('{"dialogue": "嗯", "action": "点头",}')
        assert resp.parsed_ok
        assert resp.dialogue == "嗯"

    def test_single_quotes_fixed(self):
        resp = parse_llm_response("{'dialogue': '好呀', 'action': '笑'}")
        assert resp.parsed_ok
        assert resp.dialogue == "好呀"


class TestFallbackChains:
    def test_yaml_like_format(self):
        raw = "今天过得怎么样？\nthought: 想知道她的心情\naction: 歪头\nstance: caring"
        resp = parse_llm_response(raw)
        assert resp.parsed_ok
        assert resp.dialogue == "今天过得怎么样？"
        assert resp.thought == "想知道她的心情"
        assert resp.stance == "caring"

    def test_concatenated_json_fragments(self):
        raw = '晚安啦{"action": "挥挥手"}{"pad": {"p": 0.4, "a": -0.2, "d": 0.3}}'
        resp = parse_llm_response(raw)
        assert resp.parsed_ok
        assert resp.dialogue == "晚安啦"
        assert resp.action == "挥挥手"
        assert resp.pad.p == 0.4

    def test_plain_text_fallback(self):
        resp = parse_llm_response("就是一句普通的话，没有任何结构。")
        assert not resp.parsed_ok
        assert "普通的话" in resp.dialogue

    def test_pad_only_subobject_not_mistaken_for_response(self):
        """裸 PAD 子对象不能被当成完整回复（没有 dialogue/action/thought 键）。"""
        resp = parse_llm_response('{"p": 0.1, "a": 0.2, "d": 0.3}')
        assert not resp.parsed_ok

    def test_empty_input(self):
        resp = parse_llm_response("")
        assert not resp.parsed_ok
        assert resp.dialogue == ""

    def test_raw_is_preserved(self):
        raw = '{"dialogue": "hi"}'
        assert parse_llm_response(raw).raw == raw


class TestStateChanges:
    def test_nested_state_changes(self):
        raw = json.dumps(
            {
                "dialogue": "嗯",
                "pad": {"p": 0.1, "a": 0, "d": 0},
                "state_changes": {
                    "affection": 2.6,
                    "trust": "1",
                    "respect": None,
                    "mood_cause": "你记得我的生日",
                },
            }
        )
        r = parse_llm_response(raw)
        assert r.parsed_ok
        assert r.state_changes == {"affection": 3, "trust": 1, "mood_cause": "你记得我的生日"}

    def test_flat_delta_keys(self):
        r = parse_llm_response('{"dialogue":"好","affection_delta":-2,"intimacy_delta":1}')
        assert r.state_changes == {"affection": -2, "intimacy": 1}

    def test_absent_is_none(self):
        assert parse_llm_response('{"dialogue":"好"}').state_changes is None
        assert parse_llm_response("纯文本回复").state_changes is None

    def test_garbage_values_dropped(self):
        r = parse_llm_response(
            '{"dialogue":"好","state_changes":{"affection":"many","mood_cause":42}}'
        )
        assert r.state_changes is None
