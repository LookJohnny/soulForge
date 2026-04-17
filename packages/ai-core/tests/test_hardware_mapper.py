from ai_core.services.hardware_mapper import pad_to_hardware


def test_penguin_prefers_waddle_when_excited():
    result = pad_to_hardware(0.9, 0.8, 0.5, species="企鹅")
    assert result.motor.action == "waddle"


def test_doro_prefers_wiggle_when_excited():
    result = pad_to_hardware(0.9, 0.9, 0.5, species="doro")
    assert result.motor.action == "wiggle"


def test_generic_character_can_still_bounce():
    result = pad_to_hardware(0.9, 0.8, 0.5, species="兔子")
    assert result.motor.action == "bounce"
