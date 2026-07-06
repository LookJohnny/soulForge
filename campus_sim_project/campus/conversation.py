from __future__ import annotations

import random

from campus.agent import Agent


class Conversation:
    """Simple conversation engine that can spread known events."""

    def __init__(self, random_seed: int | None = None) -> None:
        self.random = random.Random(random_seed)

    def run(self, first: Agent, second: Agent, time: str = "Day1 12:00") -> list[str]:
        logs: list[str] = []
        logs.extend(self._share_events(first, second, time))
        logs.extend(self._share_events(second, first, time))

        if not logs:
            line = f"{first.name} and {second.name} talked briefly at {first.location}."
            first.remember(time, line, 3, [second.name, "conversation"])
            second.remember(time, line, 3, [first.name, "conversation"])
            logs.append(line)

        return logs

    def _share_events(self, speaker: Agent, listener: Agent, time: str) -> list[str]:
        logs: list[str] = []
        for event in sorted(speaker.known_events - listener.known_events):
            relationship = speaker.relationships.get(listener.name, 5)
            should_share = relationship >= 4 or self.random.random() < 0.5
            if should_share:
                listener.known_events.add(event)
                line = f"{speaker.name} told {listener.name} about {event}."
                speaker.remember(time, line, 6, [listener.name, event, "conversation", "event"])
                listener.remember(time, line, 7, [speaker.name, event, "conversation", "event"])
                logs.append(line)
        return logs
