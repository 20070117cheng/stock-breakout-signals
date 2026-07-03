"""持股賣出監控 —《大漲的訊號》第四章「三種情況出現，你該立刻賣股」。

1. 停損：收盤 ≤ 買價×(1−8%) → SELL_NOW（p.215：最重要規則）
2. 基本面：最新一季稅前淨利 YoY <20% → SELL_NOW（p.192）
3. 技術面：SPR ≥117% → SELL_SIGNAL（p.211：未必立刻賣，可視情況）
"""
from __future__ import annotations


def check_stop_loss(buy_price: float, close: float, pct: float = 0.08) -> bool:
    return close <= buy_price * (1 - pct)


def check_fundamental_sell(latest_quarter_yoy: float | None) -> bool:
    """最新一季獲利成長 <20% → 賣出。無資料時不觸發（避免誤報）。"""
    if latest_quarter_yoy is None:
        return False
    return latest_quarter_yoy < 0.20


def evaluate_holding(
    buy_price: float,
    close: float,
    latest_quarter_yoy: float | None,
    spr: float | None,
    stop_loss_pct: float = 0.08,
    spr_threshold: float = 1.17,
) -> dict:
    """回傳 {"action": HOLD|SELL_SIGNAL|SELL_NOW, "reasons": [...], "pnl_pct": float}。"""
    from engine.spr import spr_sell_signal

    reasons: list[str] = []
    action = "HOLD"

    if check_stop_loss(buy_price, close, stop_loss_pct):
        reasons.append(
            f"停損：現價 {close:g} 低於買價 {buy_price:g} 達 "
            f"{(1 - close / buy_price):.1%}（門檻 {stop_loss_pct:.0%}），立即賣出"
        )
        action = "SELL_NOW"

    if check_fundamental_sell(latest_quarter_yoy):
        reasons.append(
            f"基本面惡化：最新一季獲利年增 {latest_quarter_yoy:.0%} < 20%，賣出"
        )
        action = "SELL_NOW"

    if spr is not None and spr_sell_signal(spr, spr_threshold):
        reasons.append(
            f"技術面：賣壓比例 {spr:.0%} ≥ {spr_threshold:.0%}，股價可能已達中長期高點"
        )
        if action == "HOLD":
            action = "SELL_SIGNAL"

    # 停損優先呈現
    reasons.sort(key=lambda r: 0 if r.startswith("停損") else (1 if r.startswith("基本面") else 2))
    return {
        "action": action,
        "reasons": reasons,
        "pnl_pct": close / buy_price - 1,
    }
