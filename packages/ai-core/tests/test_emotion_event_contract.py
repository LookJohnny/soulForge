"""Wire contract for the streaming `emotion` SSE event.

The gateway (StreamChunk kind="emotion") and device clients rely on this
shape; guard it against accidental drift in hardware_mapper serialization.
"""

import json

from ai_core.services.hardware_mapper import pad_to_hardware
from ai_core.services.pad_model import PADState, pad_to_emotion


def test_emotion_event_payload_is_json_serializable():
    hw = pad_to_hardware(0.5, 0.3, 0.6)
    event = {
        "type": "emotion",
        "emotion": pad_to_emotion(PADState(p=0.5, a=0.3, d=0.6)),
        "pad": {"p": 0.5, "a": 0.3, "d": 0.6},
        "hardware": hw.to_dict(),
    }
    encoded = json.dumps(event, ensure_ascii=False)
    decoded = json.loads(encoded)
    assert decoded["type"] == "emotion"
    assert decoded["emotion"]
    assert set(decoded["pad"]) == {"p", "a", "d"}
    assert "led" in decoded["hardware"]
    assert "expression" in decoded["hardware"]["led"]
    assert "motor" in decoded["hardware"]


def test_hardware_expression_matches_discrete_emotion_vocabulary():
    from ai_core.services.emotion import EMOTIONS

    for p, a, d in [(0.8, 0.6, 0.5), (-0.6, -0.3, -0.2), (0.1, 0.9, 0.4), (0.0, 0.0, 0.0)]:
        hw = pad_to_hardware(p, a, d)
        assert hw.led.expression in EMOTIONS
