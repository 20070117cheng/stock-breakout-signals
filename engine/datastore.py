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


def drop_broken_tail(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """資料品質保險絲：剔除尾端「幾乎整列缺值」的日子（資料源限流/故障）。

    回傳（清理後的表, 剔除列數）。寧可當天略過等重試，不可用殘缺資料矇眼掃描。
    """
    dropped = 0
    if len(df) > 25:
        baseline = df.iloc[-25:-5].notna().sum(axis=1).median()
        while len(df) > 1 and df.iloc[-1].notna().sum() < baseline * 0.4:
            bad = df.index[-1]
            print(f"[datastore] {bad.date()} 僅 {df.iloc[-1].notna().sum():.0f} 檔有效"
                  f"（正常約 {baseline:.0f}），判定資料源異常，剔除該日")
            df = df.iloc[:-1]
            dropped += 1
    return df, dropped


def update_close(market: str, tickers: list[str], full_years: int = 3) -> pd.DataFrame:
    """增量更新收盤價寬表；無快取時做完整回補。

    被資料源限流（當日資料幾乎全缺）時，在執行中等待數分鐘重試，
    最多三次——凌晨時段雲端主機常被限流，等待常常就解了。
    """
    DATA_DIR.mkdir(exist_ok=True)
    cached = load_close(market)
    if cached is not None and len(cached) > 0:
        known = [t for t in tickers if t in cached.columns]
        new = [t for t in tickers if t not in cached.columns]
        start = (cached.index.max() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        merged = cached
        for attempt in range(3):
            fresh = _download_close(known, start=start)
            candidate = pd.concat([cached[~cached.index.isin(fresh.index)], fresh]).sort_index()
            candidate, n_bad = drop_broken_tail(candidate)
            merged = candidate
            if n_bad == 0 or attempt == 2:
                break
            print(f"[datastore] 疑似被資料源限流，等 240 秒後重抓（第 {attempt + 2}/3 次）")
            time.sleep(240)
        if new:  # 名單新增的股票：補完整歷史
            print(f"[datastore] 新增 {len(new)} 檔，回補完整歷史")
            hist = _download_close(new, period=f"{full_years}y")
            merged = merged.join(hist, how="outer").sort_index()
        merged = merged.tail(KEEP_DAYS)
    else:
        merged = _download_close(tickers, period=f"{full_years}y").tail(KEEP_DAYS)
        merged, _ = drop_broken_tail(merged)

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
