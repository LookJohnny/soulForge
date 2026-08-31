"""Moved to soulforge_harness.soul.quiz (compatibility re-export)."""

import sys

from soulforge_harness.soul import quiz as _m

sys.modules[__name__] = _m
