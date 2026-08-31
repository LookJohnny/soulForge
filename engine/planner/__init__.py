"""Compatibility shim: `engine.planner` moved to `soulforge_harness.runtime`.

The life-simulation runtime is now the open harness SDK
(packages/soulforge-harness). Every public name and every submodule path
(`engine.planner.models`, `engine.planner.llm_interface`, …) keeps working;
new code should import from `soulforge_harness.runtime` directly.
"""

import importlib
import pkgutil
import sys

import soulforge_harness.runtime as _rt
from soulforge_harness.runtime import *  # noqa: F401,F403
from soulforge_harness.runtime import __all__  # noqa: F401

# alias every runtime submodule under the old path so
# `from engine.planner.space import HOME` style imports stay valid
for _info in pkgutil.iter_modules(_rt.__path__):
    _mod = importlib.import_module(f"{_rt.__name__}.{_info.name}")
    sys.modules[f"{__name__}.{_info.name}"] = _mod
