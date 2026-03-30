"""Time & date plugin — answers time/date questions without LLM."""

from datetime import datetime
from gateway.plugins import plugin

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@plugin(keywords=["几点", "时间", "what time", "现在几点"], name="时间查询")
def get_time(text: str) -> str:
    now = datetime.now()
    return f"现在是{now.hour}点{now.minute}分"


@plugin(keywords=["几号", "日期", "今天是", "what date", "星期几", "周几"], name="日期查询")
def get_date(text: str) -> str:
    now = datetime.now()
    weekday = WEEKDAYS[now.weekday()]
    return f"今天是{now.year}年{now.month}月{now.day}日，{weekday}"
