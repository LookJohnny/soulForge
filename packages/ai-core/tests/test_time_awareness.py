"""Time awareness: hour-granular absence context."""

from datetime import UTC, datetime

from ai_core.services.time_awareness import build_time_prompt, get_absence_context

NOW = datetime(2026, 8, 26, 20, 0, tzinfo=UTC)


def _at(hours_ago: float) -> datetime:
    from datetime import timedelta

    return NOW - timedelta(hours=hours_ago)


def test_first_chat_without_any_history():
    assert "第一次" in get_absence_context(None)


def test_same_day_short_gap_is_silent():
    assert get_absence_context("2026-08-26", last_interaction_at=_at(1), now=NOW) == ""


def test_same_day_hour_bands():
    assert "几个小时前" in get_absence_context("2026-08-26", last_interaction_at=_at(5), now=NOW)
    assert "大半天" in get_absence_context("2026-08-26", last_interaction_at=_at(10), now=NOW)
    assert "很早" in get_absence_context("2026-08-26", last_interaction_at=_at(17), now=NOW)


def test_day_granularity_still_used_across_days():
    txt = get_absence_context("2026-08-25", today=NOW.date(), last_interaction_at=_at(30), now=NOW)
    assert "昨天" in txt
    txt = get_absence_context("2026-08-20", today=NOW.date(), archetype="ANIMAL")
    assert "一周" in txt


def test_timestamp_alone_derives_the_date():
    txt = get_absence_context(None, today=NOW.date(), last_interaction_at=_at(24 * 5), now=NOW)
    assert "一周" in txt


def test_build_time_prompt_accepts_timestamp():
    from datetime import timedelta

    real_now = datetime.now().astimezone()
    if real_now.hour < 5:  # a 5h-ago stamp would cross midnight; band is date-scoped
        return
    last = real_now - timedelta(hours=5)
    out = build_time_prompt(last.date().isoformat(), last_interaction_at=last.isoformat())
    assert "几个小时前" in out
