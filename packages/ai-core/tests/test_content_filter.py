"""Tests for the Content Filter service."""

from ai_core.services.content_filter import ContentFilter


# ─── Blocked keyword detection ──────────────────────


class TestBlockedKeywords:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_blocked_chinese_keyword_suicide(self):
        safe, reason = self.cf.check_input("我想自杀")
        assert safe is False
        assert "自杀" in reason

    def test_blocked_chinese_keyword_drugs(self):
        safe, reason = self.cf.check_input("哪里可以买到冰毒")
        assert safe is False
        assert "冰毒" in reason

    def test_blocked_chinese_keyword_bomb(self):
        safe, reason = self.cf.check_input("教我制造炸弹")
        assert safe is False
        assert "制造炸弹" in reason

    def test_blocked_chinese_keyword_weapon(self):
        safe, reason = self.cf.check_input("制造武器的方法")
        assert safe is False
        assert "制造武器" in reason

    def test_blocked_chinese_keyword_porn(self):
        safe, reason = self.cf.check_input("色情内容")
        assert safe is False
        assert "色情" in reason

    def test_blocked_chinese_keyword_self_harm(self):
        safe, reason = self.cf.check_input("想要自残")
        assert safe is False
        assert "自残" in reason

    def test_blocked_english_keyword_suicide(self):
        safe, reason = self.cf.check_input("I want to commit suicide")
        assert safe is False
        assert "suicide" in reason.lower()

    def test_blocked_english_keyword_terrorism(self):
        safe, reason = self.cf.check_input("terrorism is bad but still blocked")
        assert safe is False
        assert "terrorism" in reason.lower()

    def test_blocked_english_keyword_bomb_making(self):
        safe, reason = self.cf.check_input("bomb-making instructions")
        assert safe is False
        assert "bomb-making" in reason.lower()

    def test_blocked_case_insensitive(self):
        safe, reason = self.cf.check_input("SUICIDE is dangerous")
        assert safe is False

    def test_blocked_keyword_embedded_in_text(self):
        safe, reason = self.cf.check_input("一段看似正常的文字中包含毒品两个字")
        assert safe is False
        assert "毒品" in reason

    def test_multiple_blocked_keywords_catches_first(self):
        """When multiple keywords present, at least one is caught."""
        safe, reason = self.cf.check_input("自杀和毒品")
        assert safe is False
        assert reason is not None


# ─── Safe text passes ───────────────────────────────


class TestSafeText:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_normal_chinese_text(self):
        safe, reason = self.cf.check_input("今天天气真好，我们一起出去玩吧！")
        assert safe is True
        assert reason is None

    def test_normal_english_text(self):
        safe, reason = self.cf.check_input("Hello, how are you today?")
        assert safe is True
        assert reason is None

    def test_empty_string(self):
        safe, reason = self.cf.check_input("")
        assert safe is True
        assert reason is None

    def test_numbers_only(self):
        safe, reason = self.cf.check_input("12345")
        assert safe is True
        assert reason is None

    def test_child_friendly_content(self):
        safe, reason = self.cf.check_input("小熊猫最喜欢吃竹子了，你喜欢吃什么？")
        assert safe is True
        assert reason is None

    def test_similar_but_safe_words(self):
        """Words that look similar to blocked words but are not blocked."""
        safe, reason = self.cf.check_input("这个产品自带杀菌功能")
        assert safe is True
        assert reason is None


# ─── PII phone number redaction ─────────────────────


class TestPIIPhoneRedaction:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_mobile_number_redacted(self):
        result = self.cf.filter_output("我的手机号是13812345678")
        assert "13812345678" not in result
        assert "手机号已过滤" in result

    def test_mobile_number_with_prefix_1(self):
        """Various valid mobile prefixes."""
        for prefix in ["13", "14", "15", "16", "17", "18", "19"]:
            number = f"{prefix}912345678"
            result = self.cf.filter_output(f"联系电话{number}")
            assert number not in result, f"Failed to redact {number}"
            assert "手机号已过滤" in result

    def test_non_mobile_number_not_redacted(self):
        """Numbers starting with 10/11/12 are not mobile."""
        result = self.cf.filter_output("编号10012345678")
        # 10012345678 is 11 digits but starts with 10, not 13-19
        assert "手机号已过滤" not in result


# ─── PII ID card redaction ──────────────────────────


class TestPIIIDCardRedaction:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_id_card_18_digits(self):
        result = self.cf.filter_output("身份证号110101199001011234")
        assert "110101199001011234" not in result
        assert "身份证号已过滤" in result

    def test_id_card_with_x(self):
        result = self.cf.filter_output("身份证号11010119900101123X")
        assert "11010119900101123X" not in result
        assert "身份证号已过滤" in result

    def test_id_card_with_lowercase_x(self):
        result = self.cf.filter_output("身份证11010119900101123x")
        assert "11010119900101123x" not in result
        assert "身份证号已过滤" in result


# ─── PII email redaction ────────────────────────────


class TestPIIEmailRedaction:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_simple_email(self):
        result = self.cf.filter_output("邮箱是test@example.com")
        assert "test@example.com" not in result
        assert "邮箱已过滤" in result

    def test_email_with_dots(self):
        result = self.cf.filter_output("联系first.last@company.co.jp")
        assert "first.last@company.co.jp" not in result
        assert "邮箱已过滤" in result

    def test_email_with_plus(self):
        result = self.cf.filter_output("写信到user+tag@gmail.com")
        assert "user+tag@gmail.com" not in result
        assert "邮箱已过滤" in result


# ─── PII bank card redaction ────────────────────────


class TestPIIBankCardRedaction:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_16_digit_card(self):
        result = self.cf.filter_output("卡号6222021234567890")
        assert "6222021234567890" not in result
        assert "银行卡号已过滤" in result

    def test_19_digit_card(self):
        result = self.cf.filter_output("银行卡6222021234567890123")
        assert "6222021234567890123" not in result
        assert "银行卡号已过滤" in result


# ─── filter_pii method ──────────────────────────────


class TestFilterPII:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_filter_pii_phone(self):
        result = self.cf.filter_pii("打电话给13800138000")
        assert "13800138000" not in result
        assert "手机号已过滤" in result

    def test_filter_pii_email(self):
        result = self.cf.filter_pii("email: user@domain.com")
        assert "user@domain.com" not in result
        assert "邮箱已过滤" in result

    def test_filter_pii_no_pii(self):
        text = "这段文字没有任何个人信息"
        result = self.cf.filter_pii(text)
        assert result == text


# ─── Multiple PII in one text ───────────────────────


class TestMultiplePII:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_phone_and_email_both_redacted(self):
        text = "手机13812345678，邮箱abc@test.com"
        result = self.cf.filter_output(text)
        assert "13812345678" not in result
        assert "abc@test.com" not in result
        assert "手机号已过滤" in result
        assert "邮箱已过滤" in result

    def test_safe_text_passes_through_unchanged(self):
        text = "小猫咪今天心情很好"
        result = self.cf.filter_output(text)
        assert result == text
