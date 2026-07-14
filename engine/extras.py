"""輔助功能：候選股走勢縮圖資料、產業聚集統計、行事曆。"""
from __future__ import annotations

import datetime

import pandas as pd

from engine.signals.new_high import TRADING_DAYS_1Y


def downsample(series: pd.Series, n: int = 120) -> list[float]:
    """收盤序列降採樣成 n 點（儀表板 SVG 縮圖用）。"""
    s = series.dropna()
    if len(s) == 0:
        return []
    if len(s) <= n:
        return [round(float(v), 3) for v in s]
    idx = [int(i * (len(s) - 1) / (n - 1)) for i in range(n)]
    return [round(float(s.iloc[i]), 3) for i in idx]


def industry_summary(close: pd.DataFrame, industry_of: dict[str, str],
                     names: dict[str, str], top: int = 12) -> list[dict]:
    """今日各產業「創一年新高」家數統計（書：領導股集中在明星產業）。"""
    rmax = close.shift(1).rolling(TRADING_DAYS_1Y, min_periods=TRADING_DAYS_1Y // 2).max()
    last = close.iloc[-1]
    prior = rmax.iloc[-1]
    hit = last[(last > prior) & last.notna() & prior.notna()].index

    groups: dict[str, dict] = {}
    for tk in close.columns:
        ind = industry_of.get(tk) or "未分類"
        g = groups.setdefault(ind, {"industry": ind, "total": 0, "n_high": 0, "names": []})
        if pd.notna(last.get(tk)):
            g["total"] += 1
        if tk in hit:
            g["n_high"] += 1
            g["names"].append(names.get(tk, tk))
    out = [g for g in groups.values() if g["n_high"] > 0]
    out.sort(key=lambda g: g["n_high"], reverse=True)
    for g in out:
        g["names"] = g["names"][:10]
    return out[:top]


def tw_statutory_events(today: datetime.date) -> list[dict]:
    """台股法定公告時點（全市場適用）。"""
    year = today.year
    fixed = [
        (datetime.date(year, 3, 31), "年報公布截止"),
        (datetime.date(year, 5, 15), "第一季財報截止"),
        (datetime.date(year, 8, 14), "第二季財報截止"),
        (datetime.date(year, 11, 14), "第三季財報截止"),
        (datetime.date(year + 1, 3, 31), "年報公布截止"),
    ]
    # 下一個月營收公布日（每月 10 日前）
    rev = datetime.date(year, today.month, 10)
    if rev < today:
        rev = (datetime.date(year, today.month, 28) + datetime.timedelta(days=13)).replace(day=10)
    fixed.append((rev, "上月營收公布截止"))
    out = [{"date": d.isoformat(), "market": "台股", "ticker": "—", "name": "全市場",
            "event": ev} for d, ev in fixed if today <= d <= today + datetime.timedelta(days=90)]
    return out


def build_calendar(market: str, watch: list[tuple[str, str]],
                   today: datetime.date | None = None) -> list[dict]:
    """為持股／虛擬持倉建立事件行事曆（財報日、除權息）。

    watch: [(ticker, name), ...]（只查你持有的，控制 API 用量）
    """
    today = today or datetime.date.today()
    events: list[dict] = []
    mkt_name = "台股" if market == "tw" else "美股"

    for ticker, name in watch:
        try:
            if market == "us":
                import yfinance as yf
                cal = yf.Ticker(ticker).calendar or {}
                for d in (cal.get("Earnings Date") or [])[:1]:
                    d = d if isinstance(d, datetime.date) else pd.to_datetime(d).date()
                    if d >= today:
                        events.append({"date": d.isoformat(), "market": mkt_name,
                                       "ticker": ticker, "name": name, "event": "財報公布"})
            else:
                from engine.signals.fundamentals import _finmind
                div = _finmind("TaiwanStockDividend", ticker.split(".")[0],
                               f"{today.year}-01-01")
                if not div.empty:
                    row = div.iloc[-1]
                    for col, ev in (("CashExDividendTradingDate", "除息"),
                                    ("StockExDividendTradingDate", "除權")):
                        v = str(row.get(col, "") or "")
                        if len(v) == 10 and v >= today.isoformat():
                            events.append({"date": v, "market": mkt_name,
                                           "ticker": ticker, "name": name, "event": ev})
        except Exception as e:
            print(f"[calendar] {ticker} 查詢失敗：{e}")

    if market == "tw":
        events += tw_statutory_events(today)
    events.sort(key=lambda e: e["date"])
    return events
