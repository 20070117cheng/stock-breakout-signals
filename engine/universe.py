"""掃描範圍：台股上市+上櫃全部、美股 S&P 500 + NASDAQ 100。"""
from __future__ import annotations

import io

import pandas as pd
import requests

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
_HEADERS = {"User-Agent": "Mozilla/5.0 (stock-breakout-signals)"}


def tw_universe() -> pd.DataFrame:
    """台股上市(twse)+上櫃(tpex)普通股。回傳欄位：ticker(yfinance格式)、stock_id、name。"""
    r = requests.get(FINMIND_URL, params={"dataset": "TaiwanStockInfo"}, timeout=60)
    r.raise_for_status()
    df = pd.DataFrame(r.json()["data"])
    df = df[df["type"].isin(["twse", "tpex"])]
    # 普通股：4 碼數字代號；排除 ETF(00 開頭)、特別股、權證等
    df = df[df["stock_id"].str.fullmatch(r"[1-9]\d{3}")]
    df = df.drop_duplicates(subset="stock_id")
    suffix = df["type"].map({"twse": ".TW", "tpex": ".TWO"})
    return pd.DataFrame(
        {
            "ticker": df["stock_id"] + suffix,
            "stock_id": df["stock_id"],
            "name": df["stock_name"],
            "industry": df.get("industry_category", pd.Series("", index=df.index)).fillna("未分類"),
        }
    ).reset_index(drop=True)


def us_universe() -> pd.DataFrame:
    """S&P 500 + NASDAQ 100（Wikipedia 成分表）。回傳欄位：ticker、name。"""
    frames = []
    sp = _read_wiki("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies")
    for t in sp:
        if {"Symbol", "Security"}.issubset(t.columns):
            cols = {"Symbol": "ticker", "Security": "name"}
            keep = ["Symbol", "Security"]
            if "GICS Sector" in t.columns:
                cols["GICS Sector"] = "industry"
                keep.append("GICS Sector")
            frames.append(t[keep].rename(columns=cols))
            break
    ndx = _read_wiki("https://en.wikipedia.org/wiki/Nasdaq-100")
    for t in ndx:
        cols = {str(c).lower(): c for c in t.columns}
        sym = cols.get("ticker") or cols.get("symbol")
        nm = cols.get("company")
        if sym and nm:
            frames.append(t[[sym, nm]].rename(columns={sym: "ticker", nm: "name"}))
            break
    df = pd.concat(frames, ignore_index=True).drop_duplicates(subset="ticker")
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)  # BRK.B → BRK-B
    if "industry" not in df.columns:
        df["industry"] = "未分類"
    df["industry"] = df["industry"].fillna("未分類")
    return df.reset_index(drop=True)


def _read_wiki(url: str) -> list[pd.DataFrame]:
    r = requests.get(url, headers=_HEADERS, timeout=60)
    r.raise_for_status()
    return pd.read_html(io.StringIO(r.text))
