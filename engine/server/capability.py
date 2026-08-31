"""Moved to soulforge_harness.protocol.capability (compatibility re-export)."""

import sys

from soulforge_harness.protocol import capability as _m

sys.modules[__name__] = _m
