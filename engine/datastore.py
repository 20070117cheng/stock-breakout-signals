"""價格快取：收盤價寬表 parquet（全 universe，3 年滾動），增量更新。

持股與候選股需要 OHLCV / 長期歷史時另行即時抓取（檔數少）。
"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import yfinance as yf

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
KEEP_DAYS = 245 * 3 + 40  # 3 年 + 緩衝（突破需 490 日 + 一年新高比需 245 日）
BATCH = 150


def cache_path(market: str) -> Path:
    return DATA_DIR / f"close_{market}.parquet"


def load_close(market: str) -> pd.DataFrame | None:
    p = cache_path(market)
    if p.exists():
        df = pd.read_parquet(p)
        df.index = pd.to_datetime(df.index)
        return df
    return None


def update_close(market: str, tickers: list[str], full_years: int = 3) -> pd.DataFrame:
    """增量更新收盤價寬表；無快取時做完整回補。"""
    DATA_DIR.mkdir(exist_ok=True)
    cached = load_close(market)
    if cached is not None and len(cached) > 0:
        known = [t for t in tickers if t in cached.columns]
        new = [t for t in tickers if t not in cached.columns]
        start = (cached.index.max() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        fresh = _download_close(known, start=start)
        merged = pd.concat([cached[~cached.index.isin(fresh.index)], fresh]).sort_index()
        if new:  # 名單新增的股票：補完整歷史
            print(f"[datastore] 新增 {len(new)} 檔，回補完整歷史")
            hist = _download_close(new, period=f"{full_years}y")
            merged = merged.join(hist, how="outer").sort_index()
        merged = merged.tail(KEEP_DAYS)
    else:
        merged = _download_close(tickers, period=f"{full_years}y").tail(KEEP_DAYS)
    merged.to_parquet(cache_path(market))
    return merged


def _download_close(tickers: list[str], start: str | None = None, period: str | None = None) -> pd.DataFrame:
    frames = []
    for i in range(0, len(tickers), BATCH):
        batch = tickers[i : i + BATCH]
        for attempt in range(3):
            try:
                kw = {"start": start} if start else {"period": period}
                df = yf.download(
                    batch, progress=False, auto_adjust=True, threads=True, **kw
                )["Close"]
                if isinstance(df, pd.Series):
                    df = df.to_frame(batch[0])
                frames.append(df)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(15 * (attempt + 1))
        time.sleep(1)
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    out.index = pd.to_datetime(out.index)
    return out.sort_index()


def fetch_ohlcv(ticker: str, period: str = "6mo") -> pd.DataFrame:
    """單檔 OHLCV（持股 SPR 計算用）。"""
    df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def fetch_long_close(ticker: str, years: int = 9) -> pd.Series:
    """單檔長期收盤（反彈幅度/距上次高點年數用）。"""
    df = yf.Ticker(ticker).history(period=f"{years}y", auto_adjust=True)
    return df["Close"].dropna()
