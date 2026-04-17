"""TTS per-request context helpers.

Keeps the 4-arg dance of feeding character config (species / personality /
voice_clone_ref_id / audio_clips) to the provider in one place so callers
can't forget fields or drift out of sync.
"""

from __future__ import annotations


def prepare_for_character(tts, prompt_result: dict) -> None:
    """Seed the TTS provider with this turn's character context.

    Safe to call even if the active provider doesn't expose
    ``set_character_context`` (only Fish Audio does today). The Fish Audio
    provider stores context in an asyncio ContextVar so concurrent
    requests don't step on each other.
    """
    provider = getattr(tts, "_provider", None)
    if provider is None or not hasattr(provider, "set_character_context"):
        return
    provider.set_character_context(
        species=prompt_result.get("_species", ""),
        personality=prompt_result.get("personality"),
        voice_clone_ref_id=prompt_result.get("_voice_clone_ref_id"),
        audio_clips=prompt_result.get("_audio_clips"),
    )
