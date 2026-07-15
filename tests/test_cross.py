# -*- coding: utf-8 -*-
"""交叉檢核（engine/cross.py）：箱型×書中雙向檢核與綜合名單。"""
import numpy as np
import pandas as pd
import pytest

from engine import cross
from engine.box.scan import check_near_high

CFG = {"box_high_threshold_pct": 95.0, "box_kd_period": 9, "box_near_cross_gap": 2.0}


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    c = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "Open": c, "High": c * 1.01, "Low": c * 0.99, "Close": c,
        "Volume": [1000] * len(c),
    })


def _downtrend_then_pop(n: int = 80) -> list[float]:
    """先跌後急拉：尾端 K 由下往上穿 D（製造剛金叉情境）。"""
    down = list(np.linspace(100, 80, n - 3))
    return down + [88, 96, 100]


def _steady_uptrend(n: int = 60) -> list[float]:
    """緩漲後末段連漲 8 天：K 已在 D 上方一段時間，非剛交叉也非準備交叉。"""
    return list(np.linspace(60, 80, n)) + [80 + i * 2.5 for i in range(1, 9)]


class TestBoxStatus:
    def test_consistent_with_original_scan_rule(self):
        """pass 與否必須和原箱型判斷式 check_near_high 完全一致（判斷邏輯不可漂移）。"""
        for closes in (_downtrend_then_pop(), _steady_uptrend()):
            ohlcv = _ohlcv(closes)
            high3y = float(max(closes))
            st = cross.box_status(ohlcv, high3y, CFG)
            original = check_near_high(ohlcv.copy(), high3y,
                                       CFG["box_high_threshold_pct"],
                                       CFG["box_kd_period"], CFG["box_near_cross_gap"])
            assert st["pass"] == (original is not None)
            if original is not None:
                assert st["kd_state"] == original["kd_state"]

    def test_fail_below_price_threshold_gives_reason(self):
        closes = _downtrend_then_pop()
        ohlcv = _ohlcv(closes)
        high3y = float(max(closes)) * 1.2  # 現價遠低於 3 年高的 95%
        st = cross.box_status(ohlcv, high3y, CFG)
        assert st["pass"] is False
        assert "95" in st["reason"] and "距3年高" in st["reason"]

    def test_fail_kd_not_crossing_gives_reason(self):
        closes = _steady_uptrend()
        ohlcv = _ohlcv(closes)
        st = cross.box_status(ohlcv, float(max(closes)), CFG)
        assert st["pass"] is False
        assert "KD" in st["reason"]

    def test_insufficient_data(self):
        st = cross.box_status(_ohlcv([100] * 30), 100.0, CFG)
        assert st["pass"] is False
        assert "資料" in st["reason"]


class TestFundCheck:
    def test_pass_when_no_x(self):
        items = {"3": ("O", "a"), "4": ("T", "b"), "5": ("O", "c"),
                 "6": ("T", "d"), "8": ("O", "e")}
        fc = cross.fund_check_result(items)
        assert fc["pass"] is True
        assert "×" not in fc["summary"]
        assert "△" in fc["summary"] and "○" in fc["summary"]

    def test_fail_when_any_x(self):
        items = {"3": ("O", "a"), "4": ("X", "b"), "5": ("O", "c"),
                 "6": ("O", "d"), "8": ("O", "e")}
        fc = cross.fund_check_result(items)
        assert fc["pass"] is False
        assert "×" in fc["summary"]


def _buy(ticker, verdict="強力候選：…", score=85, box_pass=True):
    return {
        "ticker": ticker, "name": ticker, "close": 100.0,
        "scorecard": {"score": score, "verdict": verdict, "items": []},
        "box_check": {"pass": box_pass, "kd_state": "剛黃金交叉",
                      "pct_of_high": 99.0, "k": 60.0, "d": 55.0}
        if box_pass else {"pass": False, "reason": "KD 未交叉"},
    }


def _box(ticker, fund_pass=True):
    return {
        "ticker": ticker, "name": ticker, "close": 50.0,
        "high_close_3y": 51.0, "pct_of_high": 98.0,
        "k": 61.0, "d": 58.0, "kd_state": "剛黃金交叉",
        "fund_check": {"pass": fund_pass, "summary": "③○ ④△ ⑤○ ⑥○ ⑧○"}
        if fund_pass else {"pass": False, "summary": "③○ ④× ⑤○ ⑥○ ⑧○"},
    }


class TestCombine:
    def test_buy_candidate_needs_both_checks(self):
        combo = cross.combine([_buy("A"), _buy("B", box_pass=False)], [])
        assert [c["ticker"] for c in combo] == ["A"]

    def test_buy_candidate_excluded_when_verdict_weak(self):
        combo = cross.combine(
            [_buy("A", verdict="淘汰：關鍵項目不合格"),
             _buy("B", verdict="偏弱：獲利成長檢核不合格，觀望為宜")], [])
        assert combo == []

    def test_box_candidate_needs_fund_pass(self):
        combo = cross.combine([], [_box("C"), _box("D", fund_pass=False)])
        assert [c["ticker"] for c in combo] == ["C"]

    def test_dedupe_same_ticker(self):
        combo = cross.combine([_buy("A")], [_box("A")])
        assert len(combo) == 1
        assert set(combo[0]["sources"]) == {"breakout", "box"}

    def test_sorted_by_score_then_pct(self):
        combo = cross.combine(
            [_buy("A", score=70), _buy("B", score=90)],
            [_box("C")])  # 箱型來源無檢核分數，排最後
        assert [c["ticker"] for c in combo] == ["B", "A", "C"]

    def test_json_serializable(self):
        import json
        combo = cross.combine([_buy("A")], [_box("A"), _box("C")])
        json.dumps(combo, ensure_ascii=False)
