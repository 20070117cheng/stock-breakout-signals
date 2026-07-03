"""基本面檢核 ③④⑤⑥⑧ —《大漲的訊號》第三章。

台股：FinMind（稅前淨利 PreTaxIncome ≒ 書中「經常利益」、營收、月營收）
美股：yfinance（Pretax Income、Total Revenue、trailingPE）
只對通過價格篩選的候選股查詢，避開免費 API 限流。
"""
from __future__ import annotations

import os
import time

import pandas as pd
import requests
import yfinance as yf

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"


def _finmind(dataset: str, stock_id: str, start_date: str) -> pd.DataFrame:
    params = {"dataset": dataset, "data_id": stock_id, "start_date": start_date}
    token = os.environ.get("FINMIND_TOKEN", "")
    if token:
        params["token"] = token
    for attempt in range(3):
        r = requests.get(FINMIND_URL, params=params, timeout=60)
        if r.status_code == 200:
            data = r.json().get("data", [])
            return pd.DataFrame(data)
        time.sleep(20 * (attempt + 1))
    return pd.DataFrame()


def tw_fundamentals(stock_id: str) -> dict:
    """回傳 {annual_pretax: Series(年), quarterly: DataFrame(date, pretax, revenue), monthly_rev_yoy: [..], eps_ttm: float|None}"""
    start = f"{pd.Timestamp.now().year - 9}-01-01"
    fs = _finmind("TaiwanStockFinancialStatements", stock_id, start)
    out: dict = {"annual_pretax": None, "quarterly": None, "monthly_rev_yoy": [], "eps_ttm": None}
    if not fs.empty:
        piv = fs.pivot_table(index="date", columns="type", values="value", aggfunc="first")
        piv.index = pd.to_datetime(piv.index)
        q = pd.DataFrame(
            {
                "pretax": piv.get("PreTaxIncome"),
                "revenue": piv.get("Revenue"),
                "eps": piv.get("EPS"),
            }
        ).dropna(subset=["pretax"])
        out["quarterly"] = q
        annual = q["pretax"].groupby(q.index.year).sum()
        # 只保留完整年度（4 季）
        counts = q["pretax"].groupby(q.index.year).count()
        out["annual_pretax"] = annual[counts >= 4]
        if "eps" in q and q["eps"].notna().sum() >= 4:
            out["eps_ttm"] = float(q["eps"].dropna().tail(4).sum())
    # 月營收 YoY（近 4 個月）
    rev = _finmind("TaiwanStockMonthRevenue", stock_id, f"{pd.Timestamp.now().year - 2}-01-01")
    if not rev.empty and "revenue" in rev:
        rev["date"] = pd.to_datetime(rev["date"])
        rev = rev.sort_values("date").set_index("date")["revenue"]
        yoy = (rev / rev.shift(12) - 1).dropna()
        out["monthly_rev_yoy"] = [float(x) for x in yoy.tail(4)]
    return out


def us_fundamentals(ticker: str) -> dict:
    """回傳同 tw_fundamentals 結構（monthly_rev_yoy 為空；美股無月營收制度）。"""
    out: dict = {"annual_pretax": None, "quarterly": None, "monthly_rev_yoy": [], "eps_ttm": None, "pe": None}
    t = yf.Ticker(ticker)
    try:
        qis = t.quarterly_income_stmt
        if qis is not None and not qis.empty:
            q = pd.DataFrame(
                {
                    "pretax": qis.loc["Pretax Income"] if "Pretax Income" in qis.index else None,
                    "revenue": qis.loc["Total Revenue"] if "Total Revenue" in qis.index else None,
                }
            )
            q.index = pd.to_datetime(q.index)
            out["quarterly"] = q.sort_index().dropna(subset=["pretax"])
    except Exception:
        pass
    try:
        ais = t.income_stmt
        if ais is not None and not ais.empty and "Pretax Income" in ais.index:
            a = ais.loc["Pretax Income"]
            a.index = pd.to_datetime(a.index).year
            out["annual_pretax"] = a.sort_index()
    except Exception:
        pass
    try:
        out["pe"] = t.info.get("trailingPE")
    except Exception:
        pass
    return out


# ---------- 檢核表打分（O=合格 T=△勉強 X=不合格 N=無資料） ----------

def grade_long_term_growth(annual_pretax: pd.Series | None, threshold: float = 0.07) -> tuple[str, str]:
    """③ 過去 5~10 年獲利年成長平均 ≥7% 且穩定（書 p.104-109）。"""
    if annual_pretax is None or len(annual_pretax) < 3:
        return "N", "年度獲利資料不足"
    yoy = annual_pretax.pct_change().dropna()
    yoy = yoy[annual_pretax.shift(1).reindex(yoy.index) > 0]  # 基期為負不計成長率
    if len(yoy) < 2:
        return "N", "有效年成長樣本不足"
    avg = float(yoy.mean())
    positive_ratio = float((yoy > 0).mean())
    detail = f"近{len(annual_pretax)}年平均年成長 {avg:.0%}，成長年份占 {positive_ratio:.0%}"
    if avg >= threshold and positive_ratio >= 0.6:
        return "O", detail
    if avg >= threshold:
        return "T", detail + "（成長不夠穩定）"
    return "X", detail


def grade_recent_annual_growth(annual_pretax: pd.Series | None, quarterly: pd.DataFrame | None,
                               threshold: float = 0.20) -> tuple[str, str]:
    """④ 最近 1~2 年經常利益成長 ≥20%（書 p.110-122）。以 TTM 對前一年 TTM 為主。"""
    ttm_yoy = None
    if quarterly is not None and len(quarterly) >= 8:
        p = quarterly["pretax"]
        cur, prev = float(p.tail(4).sum()), float(p.iloc[-8:-4].sum())
        if prev > 0:
            ttm_yoy = cur / prev - 1
    if ttm_yoy is None and annual_pretax is not None and len(annual_pretax) >= 2:
        prev = float(annual_pretax.iloc[-2])
        if prev > 0:
            ttm_yoy = float(annual_pretax.iloc[-1]) / prev - 1
    if ttm_yoy is None:
        return "N", "資料不足"
    detail = f"近四季獲利年增 {ttm_yoy:.0%}"
    if ttm_yoy >= threshold:
        return "O", detail
    if ttm_yoy >= threshold * 0.75:
        return "T", detail + "（接近 20% 門檻）"
    return "X", detail


def _quarterly_yoy(quarterly: pd.DataFrame | None, col: str, n: int = 3) -> list[float]:
    if quarterly is None or len(quarterly) < 5 or col not in quarterly:
        return []
    s = quarterly[col].dropna()
    yoy = (s / s.shift(4) - 1).dropna()
    yoy = yoy[s.shift(4).reindex(yoy.index) > 0]
    return [float(x) for x in yoy.tail(n)]


def grade_quarterly_revenue(quarterly: pd.DataFrame | None, monthly_rev_yoy: list[float],
                            threshold: float = 0.10) -> tuple[str, str]:
    """⑤ 最近 2~3 季營收成長 ≥10%；台股輔以月營收（書 p.110-122）。"""
    vals = _quarterly_yoy(quarterly, "revenue", 3)
    src = "季營收"
    if not vals and monthly_rev_yoy:
        vals, src = monthly_rev_yoy[-3:], "月營收"
    if not vals:
        return "N", "營收資料不足"
    detail = f"近{len(vals)}期{src}年增 " + "、".join(f"{v:.0%}" for v in vals)
    ok = sum(v >= threshold for v in vals)
    if ok == len(vals):
        return "O", detail
    if ok >= len(vals) - 1 and vals[-1] >= threshold:
        return "T", detail
    return "X", detail


def grade_quarterly_profit(quarterly: pd.DataFrame | None, threshold: float = 0.20) -> tuple[str, str]:
    """⑥ 最近 2~3 季獲利成長 ≥20%（書 p.110-122）。"""
    vals = _quarterly_yoy(quarterly, "pretax", 3)
    if not vals:
        return "N", "季獲利資料不足"
    detail = f"近{len(vals)}季獲利年增 " + "、".join(f"{v:.0%}" for v in vals)
    ok = sum(v >= threshold for v in vals)
    if ok == len(vals):
        return "O", detail
    if ok >= len(vals) - 1 and vals[-1] >= threshold:
        return "T", detail
    return "X", detail


def grade_pe(pe: float | None, limit: float = 60.0) -> tuple[str, str]:
    """⑧ 本益比 <60 倍（書 p.147-153）。"""
    if pe is None or pe != pe or pe <= 0:
        return "N", "本益比無資料（可能虧損或無盈餘）"
    detail = f"本益比 {pe:.1f} 倍"
    return ("O", detail) if pe < limit else ("X", detail + "（≥60 倍，過熱）")


def latest_quarter_pretax_yoy(quarterly: pd.DataFrame | None) -> float | None:
    """持股監控用：最新一季稅前淨利 YoY。"""
    vals = _quarterly_yoy(quarterly, "pretax", 1)
    return vals[-1] if vals else None
