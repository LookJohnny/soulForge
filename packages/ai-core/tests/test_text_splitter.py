"""Tests for the text splitter — sentence boundary detection for streaming TTS."""

from ai_core.services.text_splitter import split_sentences


# ──────────────────────────────────────────────
# Chinese sentence splitting
# ──────────────────────────────────────────────


class TestChineseSentenceSplitting:
    def test_split_on_period(self):
        result = split_sentences("你好。我是小熊。")
        assert len(result) == 2
        assert result[0] == "你好。"
        assert result[1] == "我是小熊。"

    def test_split_on_exclamation(self):
        result = split_sentences("太棒了！继续加油！")
        assert len(result) == 2
        assert result[0] == "太棒了！"
        assert result[1] == "继续加油！"

    def test_split_on_question(self):
        result = split_sentences("你好吗？我很好。")
        assert len(result) == 2
        assert result[0] == "你好吗？"
        assert result[1] == "我很好。"

    def test_split_on_semicolon(self):
        result = split_sentences("春天来了；花开了。")
        assert len(result) == 2
        assert result[0] == "春天来了；"
        assert result[1] == "花开了。"

    def test_mixed_chinese_punctuation(self):
        result = split_sentences("你好！今天天气真好。我们出去玩吧？好的；走吧。")
        assert len(result) == 5
        assert result[0] == "你好！"
        assert result[1] == "今天天气真好。"
        assert result[2] == "我们出去玩吧？"
        assert result[3] == "好的；"
        assert result[4] == "走吧。"


# ──────────────────────────────────────────────
# English sentence splitting
# ──────────────────────────────────────────────


class TestEnglishSentenceSplitting:
    def test_split_on_period(self):
        result = split_sentences("Hello. How are you.")
        assert len(result) == 2
        assert result[0] == "Hello."
        assert result[1] == "How are you."

    def test_split_on_exclamation(self):
        result = split_sentences("Great! Keep going!")
        assert len(result) == 2
        assert result[0] == "Great!"
        assert result[1] == "Keep going!"

    def test_split_on_question(self):
        result = split_sentences("How are you? I am fine.")
        assert len(result) == 2
        assert result[0] == "How are you?"
        assert result[1] == "I am fine."

    def test_split_on_semicolon(self):
        result = split_sentences("First part; second part.")
        assert len(result) == 2
        assert result[0] == "First part;"
        assert result[1] == "second part."


# ──────────────────────────────────────────────
# Mixed language
# ──────────────────────────────────────────────


class TestMixedLanguage:
    def test_chinese_and_english(self):
        result = split_sentences("你好！Hello. 再见。")
        assert len(result) == 3
        assert result[0] == "你好！"
        assert result[1] == "Hello."
        assert result[2] == "再见。"

    def test_mixed_punctuation_styles(self):
        result = split_sentences("这是中文。This is English!")
        assert len(result) == 2
        assert result[0] == "这是中文。"
        assert result[1] == "This is English!"


# ──────────────────────────────────────────────
# Ellipsis handling
# ──────────────────────────────────────────────


class TestEllipsis:
    def test_chinese_ellipsis(self):
        """Chinese ellipsis (……) should be treated as one delimiter."""
        result = split_sentences("嗯……好的。")
        assert len(result) == 2
        assert result[0] == "嗯……"
        assert result[1] == "好的。"

    def test_english_ellipsis(self):
        """English ellipsis (...) should be treated as one delimiter."""
        result = split_sentences("Well... Okay.")
        assert len(result) == 2
        assert result[0] == "Well..."
        assert result[1] == "Okay."

    def test_long_ellipsis(self):
        """Multiple dots should still work."""
        result = split_sentences("Hmm..... Right.")
        assert len(result) == 2
        assert "Hmm" in result[0]
        assert "Right." in result[1]


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_input(self):
        result = split_sentences("")
        assert result == []

    def test_whitespace_only(self):
        result = split_sentences("   ")
        assert result == []

    def test_none_like_empty(self):
        """None-like empty string."""
        result = split_sentences("")
        assert result == []

    def test_single_sentence_no_split(self):
        """Text without sentence-ending punctuation stays as one piece."""
        result = split_sentences("这是一句没有句号的话")
        assert len(result) == 1
        assert result[0] == "这是一句没有句号的话"

    def test_single_sentence_with_period(self):
        result = split_sentences("你好。")
        assert len(result) == 1
        assert result[0] == "你好。"

    def test_newline_splits(self):
        """Newlines should act as sentence boundaries."""
        result = split_sentences("第一行\n第二行")
        assert len(result) == 2

    def test_delimiter_attached_to_sentence(self):
        """Delimiters should remain attached to their sentence."""
        result = split_sentences("A. B! C?")
        for s in result:
            # Each sentence should end with its punctuation
            assert s[-1] in ".!?"

    def test_only_punctuation(self):
        """String of just punctuation should return something or empty."""
        result = split_sentences("。！？")
        # All are delimiters; may return empty list or combined string
        # The important thing is no crash
        assert isinstance(result, list)

    def test_consecutive_punctuation(self):
        """Consecutive punctuation like '!!' should not create empty splits."""
        result = split_sentences("太好了！！再来！")
        # Should not contain empty strings
        for s in result:
            assert s.strip() != ""
