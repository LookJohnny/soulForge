"""Moved to soulforge_harness.protocol.frames (compatibility re-export)."""

import sys

from soulforge_harness.protocol import frames as _m

sys.modules[__name__] = _m
