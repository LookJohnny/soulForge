"""Moved to soulforge_harness.runtime.attestation (compatibility re-export)."""

from soulforge_harness.runtime.attestation import *  # noqa: F401,F403
import soulforge_harness.runtime.attestation as _m
import sys

sys.modules[__name__] = _m
