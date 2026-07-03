"""創新高價偵測與新高位置品質 —《大漲的訊號》第二章（p.60-95）、附錄一。

- 突破：收盤價創近 2 年（490 個交易日）新高（書 p.63：定義為 2~3 年，
  1 年 10 個月亦可接受，故取 2 年為基準）。
- 反彈幅度 =（突破價 − 谷底）/（歷史峰 − 谷底），目標 ≥60%（p.70 買股公式2）。
- 上次高點距今 >10 年 → 排除（p.73）。
- 平穩期：期間愈長、波動愈小愈好（p.66-67）；書中明言無法以明確數字定義，
  此處以 2 年變異係數近似為 0~1 品質分數，僅供排序參考。
"""
from __future__ import annotations

import pandas as pd

TRADING_DAYS_2Y = 490
TRADING_DAYS_1Y = 245


def detect_breakout(close: pd.Series, lookback: int = TRADING_DAYS_2Y) -> bool:
    """最後一日收盤是否突破先前 lookback 日的最高收盤。"""
    if len(close) < lookback + 1:
        return False
    window = close.iloc[-(lookback + 1):-1]
    return bool(close.iloc[-1] > window.max())


def rebound_ratio(peak: float, trough: float, breakout_price: float) -> float:
    """反彈幅度。突破價已達或超越歷史峰 → 1.0（史上新高）。"""
    if breakout_price >= peak:
        return 1.0
    decline = peak - trough
    if decline <= 0:
        return 1.0
    return (breakout_price - trough) / decline


def grade_rebound(ratio: float) -> str:
    """O=合格(≥60%)、T=勉強(45~60%，書中王將 48% 打△)、X=太弱。"""
    if ratio >= 0.60:
        return "O"
    if ratio >= 0.45:
        return "T"
    return "X"


def rebound_from_history(close: pd.Series, long_lookback: int = 245 * 8) -> dict:
    """從價格史推算反彈幅度：歷史峰（近 8 年，不含今日）→ 其後谷底 → 今日突破價。"""
    hist = close.iloc[-(long_lookback + 1):-1] if len(close) > long_lookback else close.iloc[:-1]
    if hist.empty:
        return {"ratio": 1.0, "peak": float(close.iloc[-1]), "trough": float(close.iloc[-1])}
    peak_pos = hist.idxmax()
    peak = float(hist.max())
    after_peak = hist.loc[peak_pos:]
    trough = float(after_peak.min()) if len(after_peak) > 1 else peak
    ratio = rebound_ratio(peak, trough, float(close.iloc[-1]))
    return {"ratio": ratio, "peak": peak, "trough": trough}


def years_since_last_peak(close: pd.Series) -> float:
    """不含今日的歷史最高價距今幾年（書 p.73：>10 年不考慮）。"""
    hist = close.iloc[:-1]
    peak_pos = hist.idxmax()
    days = (close.index[-1] - peak_pos).days
    return days / 365.25


def base_quality(close: pd.Series, window: int = TRADING_DAYS_2Y) -> float:
    """平穩期品質 0~1：以近 window 日（不含今日）變異係數映射，波動愈小分數愈高。

    近似指標——書中要求人工看線圖確認（p.72），此分數僅供候選排序。
    """
    base = close.iloc[-(window + 1):-1]
    if len(base) < 60 or base.mean() <= 0:
        return 0.0
    cv = float(base.std() / base.mean())
    # cv=0 → 1 分；cv≥0.5 → 0 分，線性映射
    return max(0.0, min(1.0, 1.0 - cv / 0.5))


def is_one_year_high(close: pd.Series, lookback: int = TRADING_DAYS_1Y) -> bool:
    """近一年新高（用於大盤「創新高股數量比」，書 p.88 用 1 年定義）。"""
    return detect_breakout(close, lookback=lookback)
