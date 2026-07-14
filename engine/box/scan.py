# -*- coding: utf-8 -*-
"""箱型（KD）掃描——自 stock-box-system 移植，判斷邏輯逐行保留。

near_high 規則（與原系統 core/scanner.py 完全相同）：
1. 資料 ≥ 60 筆
2. 現價 ≥ 3年收盤高點 × high_threshold_pct/100（預設 95%）
3. KD(9) 剛金叉（昨 K<D、今 K≥D）或準備交叉（K≤D 且 D-K ≤ near_cross_gap）

資料層差異：原系統逐檔讀 SQLite；本系統先用全市場收盤價快取做第 2 條的
粗篩（省 API），只對入圍者抓 OHLCV 算 KD——第 2、3 條的判斷式不變。
"""
from __future__ import annotations

import time
from typing import Callable

import pandas as pd

from engine.box.indicators import calc_kd


def check_near_high(ohlcv: pd.DataFrame, high_close_3y: float,
                    threshold_pct: float = 95.0, kd_period: int = 9,
                    near_cross_gap: float = 2.0) -> dict | None:
    """單檔判斷（原 _check_near_high，欄位改接 yfinance 大寫命名）。"""
    if len(ohlcv) < 60:
        return None
    df = pd.DataFrame({
        "high": ohlcv["High"], "low": ohlcv["Low"], "close": ohlcv["Close"],
    })
    current_price = float(df["close"].iloc[-1])
    if current_price < high_close_3y * threshold_pct / 100.0:
        return None

    df = calc_kd(df, period=kd_period)
    current_k = float(df["k"].iloc[-1])
    current_d = float(df["d"].iloc[-1])
    prev_k = float(df["k"].iloc[-2])
    prev_d = float(df["d"].iloc[-2])
    if pd.isna(current_k) or pd.isna(prev_k):
        return None

    crossed_up = prev_k < prev_d and current_k >= current_d
    getting_close = (current_k <= current_d
                     and (current_d - current_k) <= near_cross_gap)
    if not (crossed_up or getting_close):
        return None
    return {"k": round(current_k, 2), "d": round(current_d, 2),
            "kd_state": "剛黃金交叉" if crossed_up else "準備交叉向上"}


def scan_box(close: pd.DataFrame, names: dict[str, str],
             fetch_ohlcv: Callable[[str], pd.DataFrame], cfg: dict,
             pause_sec: float = 0.3) -> list[dict]:
    """全市場箱型掃描：收盤快取粗篩 → 入圍者抓 OHLCV 精判。"""
    threshold_pct = float(cfg.get("box_high_threshold_pct", 95.0))
    kd_period = int(cfg.get("box_kd_period", 9))
    near_gap = float(cfg.get("box_near_cross_gap", 2.0))

    last = close.iloc[-1]
    high_3y = close.max()
    shortlist = [
        tk for tk in close.columns
        if pd.notna(last[tk]) and pd.notna(high_3y[tk])
        and close[tk].notna().sum() >= 60
        and last[tk] >= high_3y[tk] * threshold_pct / 100.0
    ]
    print(f"[box] 粗篩（現價達3年收盤高 {threshold_pct:.0f}%）：{len(shortlist)} 檔入圍")

    out = []
    for tk in shortlist:
        try:
            ohlcv = fetch_ohlcv(tk)
            if ohlcv.empty:
                continue
            hit = check_near_high(ohlcv, float(high_3y[tk]), threshold_pct,
                                  kd_period, near_gap)
            if hit:
                cur = float(ohlcv["Close"].iloc[-1])
                out.append({
                    "ticker": tk,
                    "name": names.get(tk, tk),
                    "close": round(cur, 2),
                    "high_close_3y": round(float(high_3y[tk]), 2),
                    "pct_of_high": round(cur / float(high_3y[tk]) * 100, 2),
                    **hit,
                })
        except Exception as e:
            print(f"[box] {tk} 計算失敗：{e}")
        time.sleep(pause_sec)
    print(f"[box] KD 精判後訊號：{len(out)} 檔")
    out.sort(key=lambda r: r["pct_of_high"], reverse=True)
    return out
