"""賣壓比例（Selling Pressure Ratio, SPR）—《大漲的訊號》第四章第五節（p.201-215）。

以每日 OHLC 推估當日行進路徑，把路徑拆成買盤段（上漲）與賣壓段（下跌），
按漲跌幅比例分配當日成交量，得到「買進股數」與「賣出股數」。
SPR = 近 N 個營業日賣出股數總和 ÷ 買進股數總和；≥116~118% 視為賣出訊號。
"""
from __future__ import annotations

import pandas as pd


def daily_buy_sell_shares(
    prev_close: float,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> tuple[float, float]:
    """回傳 (買進股數, 賣出股數)。

    路徑（書 p.203）：
    - 陽線日（收 >= 開）：昨收 → 開 → 低 → 高 → 收
    - 陰線日（收 <  開）：昨收 → 開 → 高 → 低 → 收
    路徑中每一段上漲計入買盤幅度、下跌計入賣壓幅度，
    成交量按 買盤幅度:(買盤+賣壓) 比例分配。
    """
    if close >= open_:  # 陽線日
        path = [prev_close, open_, low, high, close]
    else:  # 陰線日
        path = [prev_close, open_, high, low, close]

    up = sum(b - a for a, b in zip(path, path[1:]) if b > a)
    down = sum(a - b for a, b in zip(path, path[1:]) if b < a)
    total = up + down
    if total <= 0:
        return 0.0, 0.0
    return volume * up / total, volume * down / total


def selling_pressure_ratio(ohlcv: pd.DataFrame, window: int = 20) -> pd.Series:
    """對 OHLCV DataFrame（欄位 Open/High/Low/Close/Volume）計算滾動 SPR。

    第一列僅作為「昨日收盤」基準，不計入買賣股數。
    回傳與輸入同索引的 Series（前段不足 window 者為 NaN）。
    """
    prev_close = ohlcv["Close"].shift(1)
    buys, sells = [], []
    for pc, o, h, l, c, v in zip(
        prev_close, ohlcv["Open"], ohlcv["High"], ohlcv["Low"], ohlcv["Close"], ohlcv["Volume"]
    ):
        if pd.isna(pc):
            buys.append(float("nan"))
            sells.append(float("nan"))
            continue
        b, s = daily_buy_sell_shares(pc, o, h, l, c, v)
        buys.append(b)
        sells.append(s)

    buy_s = pd.Series(buys, index=ohlcv.index)
    sell_s = pd.Series(sells, index=ohlcv.index)
    buy_sum = buy_s.rolling(window, min_periods=window).sum()
    sell_sum = sell_s.rolling(window, min_periods=window).sum()
    return sell_sum / buy_sum.replace(0, float("nan"))


def spr_sell_signal(spr_value: float, threshold: float = 1.17) -> bool:
    """SPR 達門檻（預設 117%，書 p.208 建議 116~118%）→ 賣出訊號。"""
    if spr_value is None or pd.isna(spr_value):
        return False
    return spr_value >= threshold
