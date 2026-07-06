# 虛擬操盤測試 — 依書中規則：單筆 10% 資產、黃燈減半、紅燈不買、訊號隔日開盤成交
import pytest

from engine.paper import (
    position_size_pct,
    execute_buy,
    execute_sell,
    mark_to_market,
    new_portfolio,
)


def test_position_size_by_light():
    # 書 p.95：行情強增加購買量、弱則減少；紅燈不進場
    assert position_size_pct("green") == 0.10
    assert position_size_pct("yellow") == 0.05
    assert position_size_pct("red") == 0.0


def test_execute_buy_tw_with_costs():
    pm = new_portfolio(100_000)
    # 黃燈 5%：10 萬資產 → 5,000 元預算，開盤價 100 → 買進，含 0.1425% 手續費
    trade = execute_buy(pm, market="tw", ticker="9999.TW", name="測試",
                        open_price=100.0, date="2026-07-06", light="yellow")
    assert trade is not None
    assert pm["positions"][0]["shares"] == pytest.approx(5000 / 100, rel=0.01)
    spent = 100_000 - pm["cash"]
    assert spent == pytest.approx(5000 * 1.001425, rel=0.001)


def test_execute_buy_red_light_skipped():
    pm = new_portfolio(100_000)
    trade = execute_buy(pm, market="tw", ticker="9999.TW", name="測試",
                        open_price=100.0, date="2026-07-06", light="red")
    assert trade is None
    assert pm["cash"] == 100_000


def test_execute_buy_no_duplicate_position():
    pm = new_portfolio(100_000)
    execute_buy(pm, "tw", "9999.TW", "測試", 100.0, "2026-07-06", "green")
    dup = execute_buy(pm, "tw", "9999.TW", "測試", 100.0, "2026-07-07", "green")
    assert dup is None
    assert len(pm["positions"]) == 1


def test_execute_sell_tw_with_tax():
    pm = new_portfolio(100_000)
    execute_buy(pm, "tw", "9999.TW", "測試", 100.0, "2026-07-06", "green")
    cash_before = pm["cash"]
    shares = pm["positions"][0]["shares"]
    trade = execute_sell(pm, market="tw", ticker="9999.TW",
                         open_price=92.0, date="2026-07-10", reason="停損")
    # 賣出收入 = 92×股數×(1 - 0.1425%手續費 - 0.3%證交稅)
    expected = 92.0 * shares * (1 - 0.001425 - 0.003)
    assert pm["cash"] == pytest.approx(cash_before + expected, rel=0.001)
    assert pm["positions"] == []
    assert trade["pnl_pct"] == pytest.approx(92 / 100 - 1, abs=0.01)


def test_mark_to_market_equity():
    pm = new_portfolio(100_000)
    execute_buy(pm, "tw", "9999.TW", "測試", 100.0, "2026-07-06", "green")  # 一萬元部位
    equity = mark_to_market(pm, {"9999.TW": 110.0}, "2026-07-07")
    # 現金 + 部位市值（100股漲到110 → 未實現 +10%）
    assert equity == pytest.approx(pm["cash"] + 100 * 110, rel=0.01)
    assert pm["equity_history"][-1]["date"] == "2026-07-07"


def test_mark_to_market_same_day_overwrites():
    pm = new_portfolio(100_000)
    mark_to_market(pm, {}, "2026-07-07")
    mark_to_market(pm, {}, "2026-07-07")
    assert len(pm["equity_history"]) == 1


def test_run_paper_cycle_attaches_sell_status_and_queues_sell():
    from engine.paper import run_paper_cycle

    pm = new_portfolio(100_000)
    execute_buy(pm, "tw", "9999.TW", "測試", 100.0, "2026-07-06", "green")
    evals = [{"ticker": "9999.TW", "action": "SELL_NOW",
              "reasons": ["停損：現價 91 低於買價 100 達 9.0%（門檻 8%），立即賣出"]}]
    run_paper_cycle(pm, "tw", "2026-07-07", opens={}, closes={"9999.TW": 91.0},
                    candidates=[], holding_evals=evals, light="green")
    pos = pm["positions"][0]
    assert pos["status"] == "SELL_NOW"
    assert "已排明日開盤賣出" in pos["status_note"]
    assert pm["pending_sells"][0]["ticker"] == "9999.TW"


def test_position_size_scaled_by_score():
    # 部位 = 燈號基準 ×（檢核分數/100）
    assert position_size_pct("green", 96) == pytest.approx(0.096)
    assert position_size_pct("yellow", 78) == pytest.approx(0.039)
    assert position_size_pct("red", 100) == 0.0
    assert position_size_pct("green") == 0.10  # 未提供分數時視為滿分（相容舊排單）


def test_buy_records_signal_date():
    from engine.paper import run_paper_cycle

    pm = new_portfolio(100_000)
    cand = {"ticker": "9999.TW", "name": "測試", "mech_verdict": "強力候選：x",
            "scorecard": {"score": 90, "verdict": "強力候選：x"}, "mech_score": 90}
    # 第一天：排單（記下訊號日）
    run_paper_cycle(pm, "tw", "2026-07-06", opens={}, closes={},
                    candidates=[cand], holding_evals=[], light="green")
    assert pm["pending_buys"][0]["signal_date"] == "2026-07-06"
    # 第二天：成交（訊號日寫進成交記錄與持倉）
    run_paper_cycle(pm, "tw", "2026-07-07", opens={"9999.TW": 100.0}, closes={"9999.TW": 101.0},
                    candidates=[], holding_evals=[], light="green")
    assert pm["trades"][0]["signal_date"] == "2026-07-06"
    assert pm["positions"][0]["signal_date"] == "2026-07-06"
    assert "訊號日 2026-07-06" in pm["trades"][0]["reason"]


def test_gap_protection_skips_high_open():
    from engine.paper import run_paper_cycle

    pm = new_portfolio(100_000)
    pm["pending_buys"] = [{"ticker": "9999.TW", "name": "測試", "light": "green",
                           "score": 90, "signal_date": "2026-07-06", "signal_close": 100.0}]
    # 開盤 107 較訊號日收盤 100 跳高 7% > 5% 上限 → 放棄並記錄
    run_paper_cycle(pm, "tw", "2026-07-07", opens={"9999.TW": 107.0}, closes={},
                    candidates=[], holding_evals=[], light="green")
    assert pm["positions"] == []
    assert pm["trades"][-1]["action"] == "SKIP"
    assert "放棄追高" in pm["trades"][-1]["reason"]


def test_gap_protection_allows_small_gap():
    from engine.paper import run_paper_cycle

    pm = new_portfolio(100_000)
    pm["pending_buys"] = [{"ticker": "9999.TW", "name": "測試", "light": "green",
                           "score": 90, "signal_date": "2026-07-06", "signal_close": 100.0}]
    # 跳高 3% ≤ 5% → 正常買進
    run_paper_cycle(pm, "tw", "2026-07-07", opens={"9999.TW": 103.0}, closes={"9999.TW": 104.0},
                    candidates=[], holding_evals=[], light="green")
    assert len(pm["positions"]) == 1
    assert pm["trades"][-1]["action"] == "BUY"
