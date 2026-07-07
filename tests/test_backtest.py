# 回測引擎測試：單筆交易生命週期模擬
import numpy as np
import pandas as pd
import pytest

from engine.backtest import simulate_trade


def _ohlcv(closes, opens=None, highs=None, lows=None, vols=None):
    n = len(closes)
    idx = pd.bdate_range("2024-01-01", periods=n)
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({
        "Open": opens if opens is not None else closes,
        "High": highs if highs is not None else closes * 1.01,
        "Low": lows if lows is not None else closes * 0.99,
        "Close": closes,
        "Volume": vols if vols is not None else [1_000_000] * n,
    }, index=idx)


def test_stop_loss_exit():
    # 進場 100，第 5 天收盤跌破 92 → 隔日開盤出場
    closes = [100, 99, 97, 95, 91.5, 90, 89, 88]
    opens  = [100, 99, 97, 95, 92.0, 90.5, 89, 88]
    df = _ohlcv(closes, opens)
    tr = simulate_trade(df, entry_idx=0, stop_pct=0.08, spr_threshold=1.17)
    assert tr["exit_reason"] == "停損"
    assert tr["exit_price"] == pytest.approx(90.5)   # 觸發隔日的開盤價
    assert tr["ret"] == pytest.approx(90.5 / 100 - 1, abs=1e-6)


def test_winner_holds_to_end_when_no_signal():
    # 一路緩漲、無賣訊 → 期末以最後收盤結算，標記未平倉
    closes = list(np.linspace(100, 130, 40))
    df = _ohlcv(closes)
    tr = simulate_trade(df, entry_idx=0, stop_pct=0.08, spr_threshold=99.0)  # SPR 門檻設高=不觸發
    assert tr["exit_reason"] == "期末未平倉"
    assert tr["ret"] == pytest.approx(130 / 100 - 1, rel=1e-3)


def test_near_stop_with_20d_low_exit():
    # 跌 7.5%（未達8%）但破 20 日低 → 提前出場
    closes = [100] * 25 + [96, 94, 92.4] + [92, 91]
    opens  = [100] * 25 + [96, 94, 92.5] + [92.2, 91]
    df = _ohlcv(closes, opens)
    tr = simulate_trade(df, entry_idx=0, stop_pct=0.08, spr_threshold=99.0, warn_pct=0.07)
    assert tr["exit_reason"] in ("提前停損", "停損")
    assert tr["days_held"] <= 29


def test_entry_uses_next_open_and_gap_skip():
    from engine.backtest import entry_price_with_gap

    # 訊號日收盤 100，隔日開盤 104 → 可進場（<5%）
    assert entry_price_with_gap(signal_close=100, next_open=104, max_gap=0.05) == 104
    # 隔日開盤 106 → 跳高 6% 放棄
    assert entry_price_with_gap(signal_close=100, next_open=106, max_gap=0.05) is None
