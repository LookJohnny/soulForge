"""Streaming TTS sentence splitter — splits Chinese/English text by sentence boundaries.

Designed for streaming TTS: each chunk is a complete sentence that can be
synthesized independently. Keeps delimiters attached to their sentences.
"""

import re

# Sentence boundary pattern:
#   Chinese: 。！？；  (and their fullwidth variants via NFKC)
#   English: . ! ? ;
#   Newline
#   Ellipsis: …… (Chinese) or ... (English)
#
# The pattern captures the delimiter so it stays attached to the sentence.
_SENTENCE_BOUNDARY = re.compile(
    r"((?:\.{3,}|……+)"  # Ellipsis: ... or ……
    r"|[。！？；\n]"  # Chinese sentence-enders + newline
    r"|[.!?;]"  # English sentence-enders
    r")"
)


def split_sentences(text: str) -> list[str]:
    """Split text into sentences at sentence boundaries.

    Rules:
    - Split on: 。！？；\\n and English . ! ? ;
    - Handle ellipsis: …… and ... are treated as single delimiters
    - Keep the delimiter attached to the sentence
    - Filter out empty / whitespace-only strings
    - Consecutive punctuation is grouped with the preceding sentence

    Args:
        text: Input text (Chinese, English, or mixed)

    Returns:
        List of sentences with delimiters attached
    """
    if not text or not text.strip():
        return []

    # Split while capturing delimiters
    parts = _SENTENCE_BOUNDARY.split(text)

    # Recombine: each sentence token is followed by its delimiter token
    sentences: list[str] = []
    i = 0
    while i < len(parts):
        chunk = parts[i]
        # Attach following delimiter(s) to this chunk
        while i + 1 < len(parts) and _SENTENCE_BOUNDARY.fullmatch(parts[i + 1]):
            chunk += parts[i + 1]
            i += 1
            # If the next part after a delimiter is empty, skip it
            # (happens with consecutive delimiters)
            if i + 1 < len(parts) and parts[i + 1] == "":
                i += 1
        i += 1

        # Strip and filter
        stripped = chunk.strip()
        if stripped:
            sentences.append(stripped)

    return sentences
