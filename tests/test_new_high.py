# 突破新高、反彈幅度、平穩期測試 — 基準為《大漲的訊號》第二章與附錄一
import numpy as np
import pandas as pd
import pytest

from engine.signals.new_high import (
    detect_breakout,
    rebound_ratio,
    base_quality,
    grade_rebound,
)


def _series(values):
    idx = pd.bdate_range("2020-01-01", periods=len(values))
    return pd.Series(values, index=idx, dtype=float)


def test_rebound_ratio_ohsho_example():
    # 王將食品（p.231）：峰 2195 → 谷 1070 → 突破價 1608
    # 反彈幅度 = (1608-1070)/(2195-1070) = 538/1125 ≈ 48%
    r = rebound_ratio(peak=2195, trough=1070, breakout_price=1608)
    assert r == pytest.approx(0.478, abs=0.005)


def test_rebound_ratio_ajis_example():
    # 愛捷是（p.70）：峰 2803 → 谷 668 → 突破價 2027
    # 反彈幅度 = 1359/2135 ≈ 64%
    r = rebound_ratio(peak=2803, trough=668, breakout_price=2027)
    assert r == pytest.approx(0.636, abs=0.005)


def test_rebound_at_all_time_high_is_full():
    # 創史上新高（突破價≥歷史峰）→ 反彈幅度視為 100%
    assert rebound_ratio(peak=100, trough=60, breakout_price=105) == 1.0


def test_grade_rebound_thresholds():
    assert grade_rebound(0.64) == "O"   # ≥60% → ○
    assert grade_rebound(0.48) == "T"   # 45~60% → △（王將案例書中打△）
    assert grade_rebound(0.30) == "X"   # 反彈太弱 → ×（COLOWIDE 30% 為書中反例 p.73）


def test_detect_breakout_true():
    # 前 490 日高點 100，今日收 101 → 突破
    prices = [90.0] * 200 + [100.0] + [92.0] * 289 + [101.0]
    close = _series(prices)
    assert detect_breakout(close, lookback=490) is True


def test_detect_breakout_false_below_high():
    prices = [90.0] * 200 + [100.0] + [92.0] * 289 + [99.5]
    close = _series(prices)
    assert detect_breakout(close, lookback=490) is False


def test_stale_high_over_10_years_excluded():
    # 上次高點在 10 年以上前 → 排除（書 p.73）
    from engine.signals.new_high import years_since_last_peak

    n = 260 * 12  # 12 年
    prices = [100.0] + [50.0] * (n - 2) + [101.0]
    close = _series(prices)
    assert years_since_last_peak(close) > 10


def test_base_quality_tight_base_scores_better():
    # 平穩期波動越小分數越好（書 p.66-67：震盪幅度愈小愈好）
    rng = np.random.default_rng(7)
    tight = _series(100 + rng.normal(0, 1, 500))
    loose = _series(100 + rng.normal(0, 18, 500))
    assert base_quality(tight) > base_quality(loose)
