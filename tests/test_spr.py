# 賣壓比例（SPR）測試 — 基準為《大漲的訊號》p.203-208 的數值範例
import pandas as pd
import pytest

from engine.spr import daily_buy_sell_shares, selling_pressure_ratio


def test_yang_day_book_example():
    # 陽線日（p.205 圖表4-20）：昨收910 開915 低910 高925 收920，量12萬
    # 買盤幅度 20（910→915 加 910→925），賣壓幅度 10（915→910 加 925→920）
    buy, sell = daily_buy_sell_shares(
        prev_close=910, open_=915, high=925, low=910, close=920, volume=120_000
    )
    assert buy == pytest.approx(80_000)
    assert sell == pytest.approx(40_000)


def test_yin_day_book_example():
    # 陰線日（p.207 圖表4-21）：昨收920 開925 高930 低905 收910，量8萬
    # 買盤幅度 15（920→925、925→930、905→910），賣壓幅度 25（930→905）
    buy, sell = daily_buy_sell_shares(
        prev_close=920, open_=925, high=930, low=905, close=910, volume=80_000
    )
    assert buy == pytest.approx(30_000)
    assert sell == pytest.approx(50_000)


def test_two_day_spr_book_example():
    # p.208 圖表4-22：兩日合計 買11萬 賣9萬 → SPR = 9/11 ≈ 0.818
    df = pd.DataFrame(
        {
            "Open": [910, 915, 925],
            "High": [910, 925, 930],
            "Low": [910, 910, 905],
            "Close": [910, 920, 910],
            "Volume": [0, 120_000, 80_000],
        }
    )
    spr = selling_pressure_ratio(df, window=2)
    assert spr.iloc[-1] == pytest.approx(9 / 11, rel=1e-3)


def test_gap_open_counts_from_prev_close():
    # 開盤價與昨日收盤的落差計入當日買賣（p.203「說明」）
    # 昨收900 開920（跳空買盤20）高920 低910 收910 → 陰線日
    # 買盤: 900→920 = 20；賣壓: 920→910 = 10 ... 陰線日路徑: 開→高(0)、高→低(10)、低→收(0)
    buy, sell = daily_buy_sell_shares(
        prev_close=900, open_=920, high=920, low=910, close=910, volume=30_000
    )
    assert buy == pytest.approx(20_000)
    assert sell == pytest.approx(10_000)


def test_sell_signal_threshold():
    # SPR ≥ 1.17 → 賣出訊號（書 p.208：116~118% 之間，預設 117%）
    from engine.spr import spr_sell_signal

    assert spr_sell_signal(1.20, threshold=1.17) is True
    assert spr_sell_signal(1.10, threshold=1.17) is False


def test_flat_day_no_division_error():
    # 全日無波動：買賣皆 0，不可拋例外
    buy, sell = daily_buy_sell_shares(
        prev_close=100, open_=100, high=100, low=100, close=100, volume=50_000
    )
    assert buy == 0 and sell == 0
