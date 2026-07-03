# 賣出三條件測試 —《大漲的訊號》第四章
import pandas as pd
import pytest

from engine.signals.sell import check_stop_loss, check_fundamental_sell, evaluate_holding


def test_stop_loss_triggers_at_8_percent():
    # 買價 100，收盤 92 → 觸發（書 p.215：低於買價 8% 立刻賣）
    assert check_stop_loss(buy_price=100, close=92.0, pct=0.08) is True
    assert check_stop_loss(buy_price=100, close=92.5, pct=0.08) is False


def test_fundamental_sell_below_20_percent_growth():
    # 最新一季稅前淨利 YoY <20% → 賣出（書 p.192：即使財測上修，未達20%就賣）
    assert check_fundamental_sell(latest_quarter_yoy=0.19) is True
    assert check_fundamental_sell(latest_quarter_yoy=0.20) is False
    assert check_fundamental_sell(latest_quarter_yoy=None) is False  # 無資料不誤報


def test_evaluate_holding_priority():
    # 停損優先於其他訊號（緊急度最高）
    result = evaluate_holding(
        buy_price=100,
        close=90.0,
        latest_quarter_yoy=0.10,
        spr=1.20,
        stop_loss_pct=0.08,
        spr_threshold=1.17,
    )
    assert result["action"] == "SELL_NOW"
    assert "停損" in result["reasons"][0]
    assert len(result["reasons"]) == 3  # 三個訊號都要列出


def test_evaluate_holding_healthy():
    result = evaluate_holding(
        buy_price=100,
        close=110.0,
        latest_quarter_yoy=0.35,
        spr=0.95,
        stop_loss_pct=0.08,
        spr_threshold=1.17,
    )
    assert result["action"] == "HOLD"
    assert result["reasons"] == []


def test_evaluate_holding_spr_only_is_watch():
    # 只有 SPR 訊號 → 技術面賣訊（書 p.211：未必要立刻賣，可視情況）
    result = evaluate_holding(
        buy_price=100,
        close=130.0,
        latest_quarter_yoy=0.30,
        spr=1.18,
        stop_loss_pct=0.08,
        spr_threshold=1.17,
    )
    assert result["action"] == "SELL_SIGNAL"
