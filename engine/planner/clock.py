"""Clock abstraction for the Character Runtime.

All planner code measures time in *total minutes* — a monotonically increasing
float that never wraps. Day-local lookups (day plans, HUD clocks) derive from
it via `day_minute()` / `day_index()`. Three concrete clocks:

  WallClock        real time, minutes since local midnight of the day it started
  SimulationClock  fully controlled; advance() or set(); used by tests & server
  GameClock        delegates to a host-provided callable (game engine time)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol, runtime_checkable

MINUTES_PER_DAY = 24 * 60


def day_minute(total_minutes: float) -> float:
    """Minute-of-day in [0, 1440)."""
    return total_minutes % MINUTES_PER_DAY


def day_index(total_minutes: float) -> int:
    """Which simulated day a total-minute timestamp falls in (day 0 based)."""
    return int(total_minutes // MINUTES_PER_DAY)


def clock_label(total_minutes: float) -> str:
    m = int(day_minute(total_minutes))
    return f"{m // 60:02d}:{m % 60:02d}"


@runtime_checkable
class Clock(Protocol):
    def now_minutes(self) -> float:
        """Monotonic total minutes since the clock's epoch (never wraps)."""


@dataclass
class SimulationClock:
    """Deterministic clock owned by whoever drives the simulation."""

    total_minutes: float = 0.0

    def now_minutes(self) -> float:
        return self.total_minutes

    def advance(self, minutes: float) -> float:
        if minutes < 0:
            raise ValueError("SimulationClock cannot move backwards")
        self.total_minutes += minutes
        return self.total_minutes

    def set(self, total_minutes: float) -> None:
        if total_minutes < self.total_minutes:
            raise ValueError("SimulationClock cannot move backwards")
        self.total_minutes = total_minutes


@dataclass
class WallClock:
    """Real time. Epoch = local midnight of the moment it was created, so
    now_minutes() is directly comparable with day-plan minutes on day 0 and
    keeps increasing across midnights (day 1 = 1440+...)."""

    _epoch: float = field(default_factory=lambda: _local_midnight_epoch())

    def now_minutes(self) -> float:
        return (time.time() - self._epoch) / 60.0


def _local_midnight_epoch() -> float:
    now = time.localtime()
    midnight = time.struct_time((
        now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0,
        now.tm_wday, now.tm_yday, now.tm_isdst,
    ))
    return time.mktime(midnight)


@dataclass
class GameClock:
    """Bridges a host engine's time source (e.g. Unity Time.time in seconds)."""

    source: Callable[[], float]                 # returns host time
    host_units_per_minute: float = 60.0         # seconds per minute by default
    offset_minutes: float = 0.0                 # where the host's zero maps to

    def now_minutes(self) -> float:
        return self.offset_minutes + self.source() / self.host_units_per_minute
