"""Incremental extraction of dialogue lines from a decision JSON being generated.

A decision is one JSON object; its ``dialogue`` array is what the user hears.
Waiting for the whole object made speech wait for every other field too (about
10 s on a local model, against 2-3 s for the first line). ``DialogueStream``
yields each dialogue element the moment its closing brace arrives, wherever the
array sits in the object.
"""

from __future__ import annotations

import json
import re

_KEY = re.compile(r'"dialogue"\s*:\s*\[')


class DialogueStream:
    def __init__(self) -> None:
        self.text = ""
        self._pos: int | None = None  # next element position, once the array opened
        self.closed = False  # the array's "]" has been seen
        self._decoder = json.JSONDecoder()

    def feed(self, chunk: str) -> list:
        """Append generated text; return the dialogue elements it completed."""
        self.text += chunk
        done: list = []
        if self.closed:
            return done
        if self._pos is None:
            match = _KEY.search(self.text)
            if match is None:
                return done
            self._pos = match.end()
        while True:
            i = self._pos
            while i < len(self.text) and self.text[i] in " \t\r\n,":
                i += 1
            if i >= len(self.text):
                break
            if self.text[i] == "]":
                self.closed = True
                break
            try:
                element, end = self._decoder.raw_decode(self.text, i)
            except json.JSONDecodeError:
                break  # incomplete: wait for more text
            done.append(element)
            self._pos = end
        return done


def stream_prefill(agent_id: str, *, expect_speech: bool) -> str:
    """How a streamed decision opens.

    Dialogue first so the first line is spoken while the rest is generated. A
    user turn also pins the speaker (the agent id) and starts the line's text;
    an autonomous turn only opens the array, so the character may stay silent."""
    if expect_speech:
        return '{"dialogue": [{"agent": ' + json.dumps(agent_id, ensure_ascii=False) + ', "text": "'
    return '{"dialogue": ['
