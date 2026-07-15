# -*- coding: utf-8 -*-
"""雙策略交叉檢核。

- box_status：對「大漲訊號候選」跑箱型檢核——判斷條件與 engine/box/scan.py 的
  check_near_high 完全相同（現價 ≥ 3年收盤高 95%、KD(9) 剛金叉或準備交叉），
  差別只在未通過時回傳原因，供儀表板顯示。
- fund_check_result：對「箱型候選」跑書中基本面檢核——檢核表③④⑤⑥⑧，
  無 × 即通過。①②是突破專屬條件、⑦AI 有每日額度，皆不納入。
- combine：兩個檢核都通過的股票 → 綜合訊號（儀表板最上方區塊）。
"""
from __future__ import annotations

import pandas as pd

from engine.box.indicators import calc_kd

GRADE_SYMBOL = {"O": "○", "T": "△", "X": "×"}
CIRCLED = {"3": "③", "4": "④", "5": "⑤", "6": "⑥", "8": "⑧"}


def box_status(ohlcv: pd.DataFrame | None, high_close_3y: float, cfg: dict) -> dict:
    """箱型檢核（含未通過原因）。pass 的判定必須與 check_near_high 一致。"""
    threshold_pct = float(cfg.get("box_high_threshold_pct", 95.0))
    kd_period = int(cfg.get("box_kd_period", 9))
    near_gap = float(cfg.get("box_near_cross_gap", 2.0))

    if ohlcv is None or len(ohlcv) < 60:
        return {"pass": False, "reason": "資料不足 60 筆，無法算 KD"}
    df = pd.DataFrame({
        "high": ohlcv["High"], "low": ohlcv["Low"], "close": ohlcv["Close"],
    })
    current_price = float(df["close"].iloc[-1])
    pct = current_price / high_close_3y * 100.0
    if current_price < high_close_3y * threshold_pct / 100.0:
        return {"pass": False, "pct_of_high": round(pct, 2),
                "reason": f"距3年高 {pct:.1f}%，未達 {threshold_pct:.0f}% 門檻"}

    df = calc_kd(df, period=kd_period)
    current_k = float(df["k"].iloc[-1])
    current_d = float(df["d"].iloc[-1])
    prev_k = float(df["k"].iloc[-2])
    prev_d = float(df["d"].iloc[-2])
    if pd.isna(current_k) or pd.isna(prev_k):
        return {"pass": False, "pct_of_high": round(pct, 2), "reason": "KD 暖身中，無法判斷"}

    base = {"pct_of_high": round(pct, 2), "k": round(current_k, 2), "d": round(current_d, 2)}
    crossed_up = prev_k < prev_d and current_k >= current_d
    getting_close = (current_k <= current_d
                     and (current_d - current_k) <= near_gap)
    if crossed_up:
        return {"pass": True, "kd_state": "剛黃金交叉", **base}
    if getting_close:
        return {"pass": True, "kd_state": "準備交叉向上", **base}
    return {"pass": False, **base,
            "reason": f"KD 未在交叉點（K {base['k']}／D {base['d']}，非剛金叉也非準備交叉）"}


def fund_check_result(items: dict[str, tuple[str, str]]) -> dict:
    """書中基本面檢核結果彙整：③④⑤⑥⑧ 無 × 即通過。"""
    summary = " ".join(
        f"{CIRCLED.get(key, key)}{GRADE_SYMBOL.get(grade, grade)}"
        for key, (grade, _) in sorted(items.items())
    )
    ok = all(grade != "X" for grade, _ in items.values())
    return {"pass": ok, "summary": summary,
            "detail": [{"key": k, "grade": g, "text": t} for k, (g, t) in sorted(items.items())]}


def _buy_passes_book(cand: dict) -> bool:
    v = cand["scorecard"]["verdict"]
    return not (v.startswith("淘汰") or v.startswith("偏弱"))


def combine(buy_candidates: list[dict], box_candidates: list[dict]) -> list[dict]:
    """兩個檢核都通過的股票（來源去重合併），綜合區塊用。"""
    combo: dict[str, dict] = {}
    for c in buy_candidates:
        bc = c.get("box_check") or {}
        if bc.get("pass") and _buy_passes_book(c):
            combo[c["ticker"]] = {
                "ticker": c["ticker"], "name": c["name"], "close": c["close"],
                "score": c["scorecard"]["score"], "verdict": c["scorecard"]["verdict"],
                "kd_state": bc.get("kd_state"), "pct_of_high": bc.get("pct_of_high"),
                "k": bc.get("k"), "d": bc.get("d"),
                "sources": ["breakout"],
            }
    for b in box_candidates:
        fc = b.get("fund_check") or {}
        if not fc.get("pass"):
            continue
        entry = combo.get(b["ticker"])
        if entry is None:
            combo[b["ticker"]] = {
                "ticker": b["ticker"], "name": b["name"], "close": b["close"],
                "score": None, "verdict": None,
                "kd_state": b.get("kd_state"), "pct_of_high": b.get("pct_of_high"),
                "k": b.get("k"), "d": b.get("d"),
                "fund_summary": fc.get("summary"),
                "sources": ["box"],
            }
        else:
            entry["sources"].append("box")
            entry["fund_summary"] = fc.get("summary")
    out = list(combo.values())
    out.sort(key=lambda e: (
        -(e["score"] if e["score"] is not None else -1),
        -(e["pct_of_high"] or 0),
    ))
    return out
