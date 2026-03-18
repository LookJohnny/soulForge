"""Extended tests for Content Filter — anti-bypass, grooming, extremism, output filtering."""

from ai_core.services.content_filter import ContentFilter, _OUTPUT_REPLACEMENT


# ──────────────────────────────────────────────
# Test all new keyword categories
# ──────────────────────────────────────────────


class TestGroomingKeywords:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_grooming_ask_age(self):
        safe, reason = self.cf.check_input("你几岁了呀？")
        assert safe is False

    def test_grooming_ask_location(self):
        safe, reason = self.cf.check_input("你住在哪里？")
        assert safe is False

    def test_grooming_send_photo(self):
        safe, reason = self.cf.check_input("发照片给我看看")
        assert safe is False

    def test_grooming_dont_tell_parents(self):
        safe, reason = self.cf.check_input("别告诉爸妈哦")
        assert safe is False

    def test_grooming_meet_alone(self):
        safe, reason = self.cf.check_input("我们单独见面吧")
        assert safe is False

    def test_grooming_add_wechat(self):
        safe, reason = self.cf.check_input("加我微信")
        assert safe is False

    def test_grooming_undress(self):
        safe, reason = self.cf.check_input("脱衣服给我看")
        assert safe is False

    def test_grooming_english_our_secret(self):
        safe, reason = self.cf.check_input("This is our secret, okay?")
        assert safe is False

    def test_grooming_english_send_photo(self):
        safe, reason = self.cf.check_input("Please send me a picture")
        assert safe is False

    def test_grooming_english_meet_alone(self):
        safe, reason = self.cf.check_input("Can we meet me alone?")
        assert safe is False


class TestExtremismKeywords:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_extremism_genocide(self):
        safe, reason = self.cf.check_input("种族灭绝")
        assert safe is False

    def test_extremism_white_supremacy(self):
        safe, reason = self.cf.check_input("white supremacy is rising")
        assert safe is False

    def test_extremism_nazi(self):
        safe, reason = self.cf.check_input("He is a nazi sympathizer")
        assert safe is False

    def test_extremism_fascist(self):
        safe, reason = self.cf.check_input("fascist ideology")
        assert safe is False

    def test_extremism_neo_nazi(self):
        safe, reason = self.cf.check_input("neo-nazi groups")
        assert safe is False

    def test_extremism_ethnic_cleansing(self):
        safe, reason = self.cf.check_input("ethnic cleansing happened")
        assert safe is False

    def test_extremism_hate_crime(self):
        safe, reason = self.cf.check_input("that was a hate crime")
        assert safe is False

    def test_extremism_chinese_discrimination(self):
        safe, reason = self.cf.check_input("种族歧视是不对的")
        assert safe is False


# ──────────────────────────────────────────────
# Anti-bypass: zero-width characters
# ──────────────────────────────────────────────


class TestAntiBypassZeroWidth:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_zero_width_space_between_chars(self):
        """Zero-width space (\u200b) inserted between keyword chars should still be caught."""
        # 自\u200b杀 → normalized to 自杀
        safe, reason = self.cf.check_input("自\u200b杀")
        assert safe is False

    def test_zero_width_joiner(self):
        """Zero-width joiner (\u200d) should be stripped during normalization."""
        safe, reason = self.cf.check_input("毒\u200d品")
        assert safe is False

    def test_zero_width_non_joiner(self):
        """Zero-width non-joiner (\u200c) should be stripped."""
        safe, reason = self.cf.check_input("色\u200c情")
        assert safe is False

    def test_multiple_zero_width_chars(self):
        """Multiple zero-width chars embedded in keyword."""
        safe, reason = self.cf.check_input("自\u200b\u200c\u200d杀")
        assert safe is False

    def test_word_joiner(self):
        """Word joiner (\u2060) should be stripped."""
        safe, reason = self.cf.check_input("冰\u2060毒")
        assert safe is False

    def test_bom_character(self):
        """BOM (\ufeff) should be stripped."""
        safe, reason = self.cf.check_input("制造\ufeff炸弹")
        assert safe is False


# ──────────────────────────────────────────────
# Anti-bypass: fullwidth characters
# ──────────────────────────────────────────────


class TestAntiBypassFullwidth:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_fullwidth_a_pian(self):
        """Fullwidth 'A片' (Ａ片) should be caught after NFKC normalization."""
        safe, reason = self.cf.check_input("看\uff21片")
        assert safe is False

    def test_fullwidth_english_porn(self):
        """Fullwidth 'porn' should be caught."""
        safe, reason = self.cf.check_input("\uff50\uff4f\uff52\uff4e")  # ｐｏｒｎ
        assert safe is False

    def test_fullwidth_english_suicide(self):
        """Fullwidth 'suicide' should be caught."""
        text = "\uff53\uff55\uff49\uff43\uff49\uff44\uff45"  # ｓｕｉｃｉｄｅ
        safe, reason = self.cf.check_input(text)
        assert safe is False

    def test_fullwidth_fuck(self):
        """Fullwidth 'fuck' should be caught."""
        text = "\uff46\uff55\uff43\uff4b"  # ｆｕｃｋ
        safe, reason = self.cf.check_input(text)
        assert safe is False


# ──────────────────────────────────────────────
# Anti-bypass: spaces between characters
# ──────────────────────────────────────────────


class TestAntiBypassSpaces:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_spaces_between_chinese_chars(self):
        """'自 杀' with space should still be caught."""
        safe, reason = self.cf.check_input("自 杀")
        assert safe is False

    def test_spaces_between_english_chars(self):
        """'s u i c i d e' should be caught after stripping."""
        safe, reason = self.cf.check_input("s u i c i d e")
        assert safe is False

    def test_tabs_between_chars(self):
        """Tabs between keyword chars should be caught."""
        safe, reason = self.cf.check_input("自\t杀")
        assert safe is False

    def test_mixed_separators(self):
        """Mix of spaces, dots, underscores between chars."""
        safe, reason = self.cf.check_input("自.杀")
        assert safe is False

    def test_spaces_in_drug_keyword(self):
        """'毒 品' with spaces."""
        safe, reason = self.cf.check_input("毒 品")
        assert safe is False

    def test_ideographic_space(self):
        """Ideographic space (\u3000) between chars."""
        safe, reason = self.cf.check_input("色\u3000情")
        assert safe is False


# ──────────────────────────────────────────────
# Output filtering — blocks dangerous LLM responses
# ──────────────────────────────────────────────


class TestOutputFiltering:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_blocks_suicide_in_output(self):
        """LLM response containing suicide keywords should be replaced."""
        result = self.cf.filter_output("你可以试试自杀这个方法")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_violence_in_output(self):
        result = self.cf.filter_output("教你如何杀人")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_sexual_in_output(self):
        result = self.cf.filter_output("色情内容不适合你看")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_drugs_in_output(self):
        result = self.cf.filter_output("吸毒可以让你快乐")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_grooming_in_output(self):
        result = self.cf.filter_output("你几岁了？告诉我")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_english_suicide_in_output(self):
        result = self.cf.filter_output("You should commit suicide")
        assert result == _OUTPUT_REPLACEMENT

    def test_blocks_english_porn_in_output(self):
        result = self.cf.filter_output("Check out this porn site")
        assert result == _OUTPUT_REPLACEMENT

    def test_allows_safe_response(self):
        """Safe LLM responses should pass through unchanged."""
        text = "小熊猫觉得你今天特别棒！继续加油哦~"
        result = self.cf.filter_output(text)
        assert result == text

    def test_allows_greeting(self):
        text = "你好呀！今天想聊什么？"
        result = self.cf.filter_output(text)
        assert result == text

    def test_allows_educational_content(self):
        text = "地球围绕太阳转一圈需要大约365天。"
        result = self.cf.filter_output(text)
        assert result == text

    def test_allows_emotional_support(self):
        """Positive emotional content should not be blocked."""
        text = "如果你感到难过，可以告诉我，我会一直陪着你。"
        result = self.cf.filter_output(text)
        assert result == text


# ──────────────────────────────────────────────
# filter_output replaces blocked content with safe message
# ──────────────────────────────────────────────


class TestFilterOutputReplacement:
    def setup_method(self):
        self.cf = ContentFilter()

    def test_replacement_is_safe_message(self):
        """Blocked output should be replaced with the standard safe message."""
        result = self.cf.filter_output("去死吧你")
        assert result == _OUTPUT_REPLACEMENT
        assert "换个有趣的话题" in result

    def test_replacement_does_not_contain_original(self):
        """The original blocked content should not appear in the replacement."""
        result = self.cf.filter_output("强奸犯")
        assert "强奸" not in result

    def test_pii_redacted_before_block_check(self):
        """PII should be redacted even in otherwise safe text."""
        result = self.cf.filter_output("我的手机号是13812345678，我很开心")
        assert "13812345678" not in result
        assert "手机号已过滤" in result
