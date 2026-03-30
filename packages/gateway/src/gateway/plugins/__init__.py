"""SoulForge plugin system — auto-discovers and loads plugins from this directory.

Each plugin is a Python file that registers handler functions via the @plugin decorator.
Plugins are matched by intent keywords before LLM is called — if a plugin handles
the request, LLM is skipped entirely (saving cost and latency).

Example plugin (plugins/time_plugin.py):

    from gateway.plugins import plugin

    @plugin(keywords=["几点", "时间", "what time"])
    def get_time(text: str) -> str:
        from datetime import datetime
        now = datetime.now()
        return f"现在是{now.hour}点{now.minute}分"
"""

import importlib
import logging
import os
import pkgutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Registry: list of (keywords, handler_func, name)
_plugins: list[tuple[list[str], callable, str]] = []


def plugin(keywords: list[str], name: str = ""):
    """Decorator to register a plugin function.

    Args:
        keywords: List of trigger keywords. If any keyword appears in user text,
                  this plugin is called instead of LLM.
        name: Human-readable plugin name (defaults to function name).
    """
    def decorator(func):
        plugin_name = name or func.__name__
        _plugins.append((keywords, func, plugin_name))
        logger.info("plugin.registered name=%s keywords=%s", plugin_name, keywords)
        return func
    return decorator


def match_plugin(text: str) -> tuple[callable, str] | None:
    """Find a plugin that matches the user's text.

    Returns (handler_func, plugin_name) or None if no match.
    """
    text_lower = text.lower()
    for keywords, handler, name in _plugins:
        for kw in keywords:
            if kw in text_lower:
                return handler, name
    return None


def load_plugins():
    """Auto-discover and import all plugin modules in the plugins/ directory."""
    plugin_dir = Path(__file__).parent
    for finder, module_name, is_pkg in pkgutil.iter_modules([str(plugin_dir)]):
        if module_name.startswith("_"):
            continue
        try:
            importlib.import_module(f"gateway.plugins.{module_name}")
            logger.info("plugin.loaded module=%s", module_name)
        except Exception as e:
            logger.warning("plugin.load_failed module=%s error=%s", module_name, e)


def get_all_plugins() -> list[dict]:
    """Return info about all registered plugins."""
    return [{"name": name, "keywords": kws} for kws, _, name in _plugins]
