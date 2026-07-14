# 輔助功能測試：縮圖降採樣、產業聚集、法定行事曆
import datetime

import numpy as np
import pandas as pd

from engine.extras import downsample, industry_summary, tw_statutory_events


def test_downsample_keeps_endpoints():
    s = pd.Series(np.arange(500, dtype=float))
    out = downsample(s, n=120)
    assert len(out) == 120
    assert out[0] == 0.0 and out[-1] == 499.0


def test_downsample_short_series_passthrough():
    s = pd.Series([1.0, 2.0, np.nan, 3.0])
    assert downsample(s, n=120) == [1.0, 2.0, 3.0]


def test_industry_summary_counts_new_highs():
    n = 300
    idx = pd.bdate_range("2024-01-01", periods=n)
    a = np.linspace(50, 100, n)          # A 今天創一年新高
    b = np.concatenate([np.linspace(50, 100, n - 1), [80.0]])  # B 沒有
    c = np.linspace(10, 30, n)           # C 創新高（另一產業）
    close = pd.DataFrame({"A": a, "B": b, "C": c}, index=idx)
    out = industry_summary(close, {"A": "半導體", "B": "半導體", "C": "航運"},
                           {"A": "甲", "B": "乙", "C": "丙"})
    by_ind = {g["industry"]: g for g in out}
    assert by_ind["半導體"]["n_high"] == 1 and by_ind["半導體"]["total"] == 2
    assert "甲" in by_ind["半導體"]["names"]
    assert by_ind["航運"]["n_high"] == 1


def test_tw_statutory_events_upcoming_only():
    out = tw_statutory_events(datetime.date(2026, 7, 14))
    evs = {e["event"] for e in out}
    assert "第二季財報截止" in evs           # 8/14 在 90 天內
    assert all(e["date"] >= "2026-07-14" for e in out)
