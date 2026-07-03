"""⑨ 大盤上漲力道 —《大漲的訊號》第二章第六節（p.86-95）。

創新高股數量比 = 當日創「近一年新高」家數 ÷ 全市場家數。
書中明言沒有絕對門檻（p.91），本系統以「相對自身一年分布」的位置給紅黃綠燈，
並輔以市值前 50 大在近 3 個月內創兩年新高的家數（p.92-94）。
"""
from __future__ import annotations

import pandas as pd

from .new_high import TRADING_DAYS_1Y, TRADING_DAYS_2Y


def new_high_ratio_series(close: pd.DataFrame, lookback: int = TRADING_DAYS_1Y,
                          history_days: int = 250) -> pd.Series:
    """近 history_days 日的每日創新高股數量比（10 日平滑，書 p.89 以 10 日均值呈現）。"""
    rolling_max = close.shift(1).rolling(lookback, min_periods=lookback // 2).max()
    is_high = close > rolling_max
    valid = close.notna() & rolling_max.notna()
    ratio = is_high.sum(axis=1) / valid.sum(axis=1).astype(float).replace(0.0, float("nan"))
    ratio = ratio.tail(history_days)
    return ratio.rolling(10, min_periods=1).mean()


def top50_recent_new_highs(close: pd.DataFrame, top50: list[str], months: int = 3) -> list[str]:
    """前 50 大市值股中，近 N 個月內曾創兩年新高者。"""
    hits = []
    days = 21 * months
    for t in top50:
        if t not in close.columns:
            continue
        s = close[t].dropna()
        if len(s) < TRADING_DAYS_2Y + days:
            continue
        rolling_max = s.shift(1).rolling(TRADING_DAYS_2Y).max()
        recent = (s > rolling_max).tail(days)
        if recent.any():
            hits.append(t)
    return hits


def market_light(ratio: pd.Series, top50_hits: int) -> dict:
    """紅黃綠燈（啟發式，非書中固定公式）：
    - 綠：比率位於自身一年分布前 40% 且趨勢向上，或前 25%
    - 紅：比率位於後 25% 且趨勢向下，或接近 0
    - 黃：其餘
    前 50 大有創高者可把紅升級為黃（大型股帶動，書 p.92）。
    """
    r = ratio.dropna()
    if len(r) < 30:
        return {"light": "yellow", "reason": "資料不足，暫以黃燈處理", "ratio_now": None, "trend": "flat"}
    now = float(r.iloc[-1])
    pct_rank = float((r <= now).mean())
    trend_up = now > float(r.iloc[-21]) if len(r) >= 21 else False
    near_zero = now < 0.002

    if (pct_rank >= 0.60 and trend_up) or pct_rank >= 0.75:
        light = "green"
        reason = f"創新高股比率 {now:.1%}，位於近一年前 {1 - pct_rank:.0%} 強、趨勢{'向上' if trend_up else '持平'}"
    elif near_zero or (pct_rank <= 0.25 and not trend_up):
        light = "red"
        reason = f"創新高股比率僅 {now:.2%}，位於近一年後段且未回升——書中建議此時不進場"
    else:
        light = "yellow"
        reason = f"創新高股比率 {now:.1%}，上漲力道普通——書中建議減少單次購買量"

    if light == "red" and top50_hits >= 3:
        light = "yellow"
        reason += f"；但前50大已有 {top50_hits} 檔創高，大型股開始帶動"
    return {"light": light, "reason": reason, "ratio_now": now, "trend": "up" if trend_up else "down"}
