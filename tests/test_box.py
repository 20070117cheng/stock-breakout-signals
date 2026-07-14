# 箱型策略移植測試：KD 與 near_high 判斷需與原系統行為一致
import numpy as np
import pandas as pd
import pytest

from engine.box.indicators import calc_kd
from engine.box.scan import check_near_high


def _ohlcv(closes, highs=None, lows=None):
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "Open": closes,
        "High": highs if highs is not None else closes + 1,
        "Low": lows if lows is not None else closes - 1,
        "Close": closes,
        "Volume": [1000] * len(closes),
    }, index=idx)


def test_kd_formula_matches_tw_convention():
    # 恆定上漲 → RSV 高 → K 應高於 D（K 反應較快）
    df = pd.DataFrame({
        "high": np.linspace(101, 130, 30),
        "low": np.linspace(99, 128, 30),
        "close": np.linspace(100, 129, 30),
    })
    out = calc_kd(df.copy(), period=9)
    assert out["k"].iloc[-1] > out["d"].iloc[-1]
    assert out["k"].iloc[:7].isna().all()  # 暖身期 NaN（前 period-1 筆）


def test_kd_warmup_nan_then_values():
    df = pd.DataFrame({"high": [10.0] * 20, "low": [9.0] * 20, "close": [9.5] * 20})
    out = calc_kd(df.copy(), period=9)
    assert out["k"].iloc[7].item() != out["k"].iloc[7] or pd.isna(out["k"].iloc[7])  # 第8筆仍暖身
    assert pd.notna(out["k"].iloc[9])


def test_near_high_requires_price_near_3y_high():
    # 現價只有高點的 90% → 不合格（門檻 95%）
    closes = [100.0] * 40 + [90.0] * 30
    df = _ohlcv(closes)
    assert check_near_high(df, high_close_3y=100.0) is None


def test_near_high_with_golden_cross():
    # 貼近高點 + 先跌壓低 KD 再反彈，最後一天正好 K 上穿 D（剛金叉）
    closes = [100.0] * 50 + list(np.linspace(100, 93, 12)) + [93.5, 95.5]
    df = _ohlcv(closes)
    hit = check_near_high(df, high_close_3y=100.0, threshold_pct=95.0)
    # 現價 95.5 ≥ 95 門檻；昨 K<D、今 K≥D → 剛黃金交叉
    assert hit is not None
    assert hit["kd_state"] == "剛黃金交叉"


def test_near_high_rejects_kd_far_apart():
    # 貼近高點但 KD 高檔鈍化（K 遠大於 D 已久，非「剛」金叉）→ 不出訊號
    closes = list(np.linspace(80, 100, 70))  # 一路漲，K 一直在 D 上
    df = _ohlcv(closes)
    assert check_near_high(df, high_close_3y=100.0) is None


def test_data_too_short_rejected():
    df = _ohlcv([100.0] * 30)
    assert check_near_high(df, high_close_3y=100.0) is None
