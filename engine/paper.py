"""虛擬操盤（紙上交易）——用書中規則自動模擬，追蹤方法成效。

規則對應：
- 買進：通過檢核的「強力候選」，訊號隔日開盤價成交（書第一章模擬同此假設）
- 部位：單筆 = 資產 10%（綠燈）/ 5%（黃燈）/ 紅燈不買（書 p.95：依行情強弱增減購買量）
- 賣出：與持股監控相同的三條件，訊號隔日開盤價成交
- 成本：台股手續費 0.1425%（買賣各一次）＋賣出證交稅 0.3%；美股以零手續費計
- 注意：檢核表第⑦項（人工判斷）在虛擬操盤中被跳過，因此成效可視為
  「不做功課、純機械執行」的保守下限。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAPER_PATH = ROOT / "data" / "paper.json"

FEE = {"tw": 0.001425, "us": 0.0}
SELL_TAX = {"tw": 0.003, "us": 0.0}
MAX_NEW_BUYS_PER_DAY = 3


def new_portfolio(capital: float) -> dict:
    return {
        "start_capital": capital,
        "cash": capital,
        "positions": [],
        "pending_buys": [],
        "pending_sells": [],
        "trades": [],
        "equity_history": [],
    }


def load_paper(cfg: dict) -> dict:
    if PAPER_PATH.exists():
        return json.loads(PAPER_PATH.read_text(encoding="utf-8"))
    return {
        "tw": new_portfolio(cfg.get("paper_capital_tw", 100_000)),
        "us": new_portfolio(cfg.get("paper_capital_us", 3_000)),
    }


def save_paper(paper: dict) -> None:
    PAPER_PATH.parent.mkdir(exist_ok=True)
    PAPER_PATH.write_text(json.dumps(paper, ensure_ascii=False, indent=1), encoding="utf-8")


def position_size_pct(light: str, score: int = 100) -> float:
    """部位 % ＝ 燈號基準（綠10%／黃5%／紅0）×（檢核分數/100）。

    書 p.95：依行情強弱增減購買量；分數係數把「訊號品質」納入，
    公式固定、每筆交易記錄都寫明，成效可回溯歸因。
    """
    base = {"green": 0.10, "yellow": 0.05}.get(light, 0.0)
    return base * max(0, min(100, score)) / 100


def _equity(pm: dict, prices: dict[str, float] | None = None) -> float:
    value = pm["cash"]
    for p in pm["positions"]:
        px = (prices or {}).get(p["ticker"], p.get("last_price", p["buy_price"]))
        value += p["shares"] * px
    return value


def execute_buy(pm: dict, market: str, ticker: str, name: str,
                open_price: float, date: str, light: str, score: int = 100) -> dict | None:
    """以開盤價買進。回傳成交記錄；不符合條件回傳 None。"""
    if open_price is None or open_price <= 0:
        return None
    if any(p["ticker"] == ticker for p in pm["positions"]):
        return None
    pct = position_size_pct(light, score)
    if pct == 0:
        return None
    budget = _equity(pm) * pct
    cost_rate = 1 + FEE[market]
    if budget * cost_rate > pm["cash"]:
        budget = pm["cash"] / cost_rate
    if budget < _equity(pm) * 0.02:  # 現金不足 2% 就不硬買
        return None
    shares = round(budget / open_price, 4)
    total = budget * cost_rate
    pm["cash"] -= total
    pm["positions"].append(
        {"ticker": ticker, "name": name, "shares": shares,
         "buy_price": open_price, "buy_date": date, "last_price": open_price}
    )
    light_txt = {"green": "綠", "yellow": "黃"}.get(light, light)
    trade = {"date": date, "action": "BUY", "ticker": ticker, "name": name,
             "price": open_price, "shares": shares, "amount": round(total, 2),
             "reason": f"買進訊號（{light_txt}燈基準 × 檢核{score}分 → 部位 {pct:.1%}）"}
    pm["trades"].append(trade)
    return trade


def execute_sell(pm: dict, market: str, ticker: str,
                 open_price: float, date: str, reason: str) -> dict | None:
    pos = next((p for p in pm["positions"] if p["ticker"] == ticker), None)
    if pos is None or open_price is None or open_price <= 0:
        return None
    proceeds = pos["shares"] * open_price * (1 - FEE[market] - SELL_TAX[market])
    pm["cash"] += proceeds
    pm["positions"].remove(pos)
    trade = {"date": date, "action": "SELL", "ticker": ticker, "name": pos["name"],
             "price": open_price, "shares": pos["shares"], "amount": round(proceeds, 2),
             "pnl_pct": open_price / pos["buy_price"] - 1, "reason": reason}
    pm["trades"].append(trade)
    return trade


def mark_to_market(pm: dict, prices: dict[str, float], date: str) -> float:
    """更新持倉現價並記錄當日總資產。"""
    for p in pm["positions"]:
        if p["ticker"] in prices and prices[p["ticker"]] == prices[p["ticker"]]:
            p["last_price"] = float(prices[p["ticker"]])
    equity = _equity(pm)
    hist = pm["equity_history"]
    if hist and hist[-1]["date"] == date:
        hist[-1]["equity"] = round(equity, 2)
    else:
        hist.append({"date": date, "equity": round(equity, 2)})
    pm["equity_history"] = hist[-500:]
    return equity


def run_paper_cycle(pm: dict, market: str, date: str,
                    opens: dict[str, float],
                    closes: dict[str, float],
                    candidates: list[dict],
                    holding_evals: list[dict],
                    light: str) -> list[dict]:
    """一次每日循環：執行昨日排單 → 依今日訊號排明日單 → 結算資產。

    opens：今日開盤價（執行昨日排單用）；closes：今日收盤價（結算用）。
    holding_evals：對 pm 持倉跑賣出三條件的結果（與持股監控同引擎）。
    回傳今日成交清單。
    """
    executed: list[dict] = []

    # 1. 先執行昨日排的賣單（停損優先於買進，保留現金）
    for order in pm["pending_sells"]:
        t = execute_sell(pm, market, order["ticker"], opens.get(order["ticker"]),
                         date, order["reason"])
        if t:
            executed.append(t)
    pm["pending_sells"] = []

    # 2. 執行昨日排的買單
    for order in pm["pending_buys"]:
        t = execute_buy(pm, market, order["ticker"], order["name"],
                        opens.get(order["ticker"]), date, order["light"],
                        score=order.get("score", 100))
        if t:
            executed.append(t)
    pm["pending_buys"] = []

    # 3. 依今日持倉訊號排明日賣單，並把檢查結果標在持倉上（儀表板顯示用）
    eval_map = {ev["ticker"]: ev for ev in holding_evals}
    for p in pm["positions"]:
        ev = eval_map.get(p["ticker"])
        p["status"] = ev["action"] if ev else "HOLD"
        p["status_note"] = "；".join(ev["reasons"]) if ev and ev["reasons"] else ""
    for ev in holding_evals:
        if ev["action"] in ("SELL_NOW", "SELL_SIGNAL") and ev["reasons"]:
            pm["pending_sells"].append(
                {"ticker": ev["ticker"], "reason": ev["reasons"][0]}
            )
            pos = next((p for p in pm["positions"] if p["ticker"] == ev["ticker"]), None)
            if pos:
                pos["status_note"] = "已排明日開盤賣出。" + pos["status_note"]

    # 4. 依今日買進候選排明日買單（強力候選才買，紅燈不排單）
    # 用純機械結論（mech_verdict）——虛擬操盤是「不含 AI、不做功課」的方法基準線
    if light != "red":
        strong = [c for c in candidates
                  if c.get("mech_verdict", c["scorecard"]["verdict"]).startswith("強力候選")]
        strong.sort(key=lambda c: c["scorecard"]["score"], reverse=True)
        held = {p["ticker"] for p in pm["positions"]}
        queued = 0
        for c in strong:
            if c["ticker"] in held or queued >= MAX_NEW_BUYS_PER_DAY:
                continue
            pm["pending_buys"].append(
                {"ticker": c["ticker"], "name": c["name"], "light": light,
                 "score": c["scorecard"]["score"]}
            )
            queued += 1

    # 5. 結算
    mark_to_market(pm, closes, date)
    return executed
