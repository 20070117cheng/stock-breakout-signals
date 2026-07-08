"""時光機回測：用歷史資料重演策略的技術面規則，統計勝率與報酬。

範圍與誠實限制（回測報告必附）：
- 只含價格類規則：①突破2年新高、②反彈幅度≥60%/上次高點<10年、⑨大盤燈號（紅燈不進場）、
  追高保護、停損8%、提前停損（7%+破20日低）、賣壓比例SPR≥117%
- 不含基本面③④⑤⑥⑧與AI⑦：免費資料無法還原「當日已知」的財報（避免前視偏差）
- 樣本為「目前仍上市」的股票（倖存者偏差，勝率略被高估）
- 成交假設與實盤系統相同：訊號隔日開盤進場、賣訊隔日開盤出場，含台股交易成本

用法：python -m engine.backtest --market tw --start 2022-01-01
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from engine import universe
from engine.signals.new_high import (
    TRADING_DAYS_1Y, TRADING_DAYS_2Y, rebound_ratio, grade_rebound, base_quality,
)
from engine.spr import selling_pressure_ratio

ROOT = Path(__file__).resolve().parent.parent
BT_DIR = ROOT / "data"

FEE = {"tw": 0.001425, "us": 0.0}
SELL_TAX = {"tw": 0.003, "us": 0.0}


# ---------- 單筆交易生命週期 ----------

def entry_price_with_gap(signal_close: float, next_open: float, max_gap: float = 0.05):
    """訊號隔日開盤進場；跳高逾 max_gap 放棄（回傳 None）。"""
    if next_open is None or next_open != next_open:
        return None
    if next_open > signal_close * (1 + max_gap):
        return None
    return next_open


def simulate_trade(ohlcv: pd.DataFrame, entry_idx: int, stop_pct: float = 0.08,
                   spr_threshold: float = 1.17, warn_pct: float = 0.07,
                   low_window: int = 20, max_bars: int = 500,
                   spr: pd.Series | None = None) -> dict:
    """從 entry_idx（進場日，以該日 Open 進場）逐日模擬到出場。

    賣出優先序（與實盤系統相同）：硬停損 → 提前停損（跌幅≥warn_pct 且破近20日低）→ SPR。
    賣訊在第 t 日收盤確認、第 t+1 日開盤出場；資料走完仍未出場 → 期末未平倉（以最後收盤結算）。
    spr 可傳入預先算好的序列（參數掃描時避免重複計算）。
    """
    entry = float(ohlcv["Open"].iloc[entry_idx])
    closes = ohlcv["Close"]
    opens = ohlcv["Open"]
    if spr is None:
        spr = selling_pressure_ratio(ohlcv, window=20)

    end = min(len(ohlcv) - 1, entry_idx + max_bars)
    for t in range(entry_idx, end):
        c = float(closes.iloc[t])
        reason = None
        if c <= entry * (1 - stop_pct):
            reason = "停損"
        elif c <= entry * (1 - warn_pct) and t >= low_window:
            if c <= float(closes.iloc[t - low_window:t].min()):
                reason = "提前停損"
        if reason is None and t > entry_idx:
            v = spr.iloc[t]
            if pd.notna(v) and v >= spr_threshold:
                reason = "賣壓比例"
        if reason:
            exit_price = float(opens.iloc[t + 1])
            return {"exit_reason": reason, "exit_price": exit_price,
                    "ret": exit_price / entry - 1, "days_held": t + 1 - entry_idx,
                    "entry": entry}
    last = float(closes.iloc[end])
    return {"exit_reason": "期末未平倉", "exit_price": last,
            "ret": last / entry - 1, "days_held": end - entry_idx, "entry": entry}


# ---------- 大盤燈號歷史序列 ----------

def light_series(close: pd.DataFrame) -> pd.Series:
    """每日紅黃綠燈（與實盤 market.py 同邏輯，向量化重算歷史）。"""
    rmax = close.shift(1).rolling(TRADING_DAYS_1Y, min_periods=TRADING_DAYS_1Y // 2).max()
    valid = close.notna() & rmax.notna()
    ratio = (close > rmax).sum(axis=1) / valid.sum(axis=1).astype(float).replace(0.0, np.nan)
    ratio = ratio.rolling(10, min_periods=1).mean()

    pct = ratio.rolling(245, min_periods=60).apply(lambda w: (w <= w[-1]).mean(), raw=True)
    trend_up = ratio > ratio.shift(21)
    light = pd.Series("yellow", index=ratio.index)
    light[(pct >= 0.60) & trend_up | (pct >= 0.75)] = "green"
    light[(ratio < 0.002) | ((pct <= 0.25) & ~trend_up)] = "red"
    return light


# ---------- 主回測 ----------

def run(market: str, start_signals: str, end_signals: str | None = None,
        max_gap: float = 0.05, verbose: bool = True, return_prepared: bool = False):
    uni = universe.tw_universe() if market == "tw" else universe.us_universe()
    names = dict(zip(uni["ticker"], uni["name"]))
    tickers = uni["ticker"].tolist()

    cache = BT_DIR / f"bt_close_{market}.parquet"
    if cache.exists():
        close = pd.read_parquet(cache)
    else:
        print(f"[bt] 下載 {len(tickers)} 檔 8 年收盤價（一次性，之後有快取）…")
        frames = []
        for i in range(0, len(tickers), 200):
            df = yf.download(tickers[i:i + 200], period="8y", progress=False,
                             auto_adjust=True, threads=True)["Close"]
            frames.append(df)
            time.sleep(1)
        close = pd.concat(frames, axis=1)
        close = close.loc[:, ~close.columns.duplicated()].sort_index()
        close.to_parquet(cache)
    close.index = pd.to_datetime(close.index)
    print(f"[bt] 收盤價矩陣：{close.shape[0]} 日 × {close.shape[1]} 檔")

    lights = light_series(close)

    # 訊號偵測：收盤突破前 490 日最高收盤
    rmax2 = close.shift(1).rolling(TRADING_DAYS_2Y, min_periods=int(TRADING_DAYS_2Y * 0.8)).max()
    breakout = close > rmax2
    lo = pd.Timestamp(start_signals)
    hi = pd.Timestamp(end_signals) if end_signals else close.index[-6]
    sig_days = breakout.loc[lo:hi]

    signals = []          # (date, ticker, signal_close)
    stats = {"red_skip": 0, "rebound_fail": 0, "stale_peak": 0}
    for day, row in sig_days.iterrows():
        hits = row[row.fillna(False)].index
        if len(hits) == 0:
            continue
        if lights.loc[day] == "red":
            stats["red_skip"] += len(hits)
            continue
        for tk in hits:
            s = close[tk].loc[:day].dropna()
            if len(s) < TRADING_DAYS_2Y + 20:
                continue
            hist = s.iloc[:-1]
            peak_pos = hist.idxmax()
            if (day - peak_pos).days > 3650:
                stats["stale_peak"] += 1
                continue
            trough = float(hist.loc[peak_pos:].min()) if len(hist.loc[peak_pos:]) > 1 else float(hist.max())
            r = rebound_ratio(float(hist.max()), trough, float(s.iloc[-1]))
            if grade_rebound(r) == "X":
                stats["rebound_fail"] += 1
                continue
            signals.append((day, tk, float(s.iloc[-1]), r, base_quality(s)))
    print(f"[bt] 原始訊號 {len(signals) + sum(stats.values())}，"
          f"紅燈略過 {stats['red_skip']}、反彈不足 {stats['rebound_fail']}、"
          f"高點逾10年 {stats['stale_peak']} → 有效訊號 {len(signals)}")

    # 同一檔股票 60 個交易日內只取第一個訊號（避免同一波段重複計算）
    signals.sort()
    dedup, last_seen = [], {}
    for day, tk, sc, r, bq in signals:
        if tk in last_seen and (day - last_seen[tk]).days < 90:
            continue
        last_seen[tk] = day
        dedup.append((day, tk, sc, r, bq))
    print(f"[bt] 去重後訊號 {len(dedup)}（同檔 90 天內只計首次突破）")

    # 下載訊號股完整 OHLCV（進出場與 SPR 用），存快取供參數掃描重複使用
    sig_tickers = sorted({tk for _, tk, *_ in dedup})
    ohlcv_cache = BT_DIR / f"bt_ohlcv_{market}.parquet"
    ohlcv_all: dict[str, pd.DataFrame] = {}
    if ohlcv_cache.exists():
        big = pd.read_parquet(ohlcv_cache)
        ohlcv_all = {tk: big[tk].dropna()
                     for tk in big.columns.get_level_values(0).unique() if tk in set(sig_tickers)}
    missing = [tk for tk in sig_tickers if tk not in ohlcv_all]
    if missing:
        print(f"[bt] 下載 {len(missing)} 檔訊號股 OHLCV…")
        for i in range(0, len(missing), 100):
            batch = missing[i:i + 100]
            raw = yf.download(batch, period="8y", progress=False, auto_adjust=True,
                              threads=True, group_by="ticker")
            for tk in batch:
                try:
                    df = raw[tk][["Open", "High", "Low", "Close", "Volume"]].dropna()
                    if len(df):
                        ohlcv_all[tk] = df
                except Exception:
                    pass
            time.sleep(1)
        pd.concat(ohlcv_all, axis=1).to_parquet(ohlcv_cache)

    # SPR 序列每檔只算一次（參數掃描時共用）
    print(f"[bt] 預計算 {len(ohlcv_all)} 檔 SPR…")
    spr_map = {tk: selling_pressure_ratio(df, window=20) for tk, df in ohlcv_all.items()}
    cost = FEE[market] * 2 + SELL_TAX[market]

    def simulate_all(stop_pct=0.08, spr_threshold=1.17, warn_pct=0.07, max_gap=0.05):
        trades, gap_skips = [], 0
        for day, tk, sig_close, r, bq in dedup:
            df = ohlcv_all.get(tk)
            if df is None:
                continue
            pos = df.index.searchsorted(day)
            if pos >= len(df) - 2 or df.index[pos] != day:
                continue
            entry_open = float(df["Open"].iloc[pos + 1])
            if entry_price_with_gap(sig_close, entry_open, max_gap) is None:
                gap_skips += 1
                continue
            tr = simulate_trade(df, entry_idx=pos + 1, stop_pct=stop_pct,
                                spr_threshold=spr_threshold, warn_pct=warn_pct,
                                spr=spr_map.get(tk))
            tr["ret"] -= cost  # 交易成本
            trades.append({"signal_date": day.date(), "ticker": tk,
                           "name": names.get(tk, tk), "light": lights.loc[day],
                           "rebound": r, "base_q": bq, **tr})
        return pd.DataFrame(trades), gap_skips

    if return_prepared:
        return {"simulate": lambda **kw: simulate_all(**kw)[0]}

    res, gap_skips = simulate_all(max_gap=max_gap)
    if verbose and len(res):
        _report(res, gap_skips, market)
    return res


def _report(res: pd.DataFrame, gap_skips: int, market: str) -> None:
    closed = res[res["exit_reason"] != "期末未平倉"]
    print("\n" + "=" * 62)
    print(f"回測結果（{market}，技術面規則，不含基本面篩選）")
    print("=" * 62)
    print(f"交易筆數 {len(res)}（另有 {gap_skips} 筆因跳高>5% 放棄）")
    print(f"勝率 {(res['ret'] > 0).mean():.1%}｜平均報酬 {res['ret'].mean():+.2%}｜"
          f"中位數 {res['ret'].median():+.2%}")
    wins, losses = res[res["ret"] > 0]["ret"], res[res["ret"] <= 0]["ret"]
    pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
    print(f"平均獲利 {wins.mean():+.2%}｜平均虧損 {losses.mean():+.2%}｜獲利因子 {pf:.2f}")
    print(f"最大單筆 {res['ret'].max():+.1%}／{res['ret'].min():+.1%}｜"
          f"平均持有 {res['days_held'].mean():.0f} 個交易日")
    print(f"未平倉 {len(res) - len(closed)} 筆（以期末價結算計入上述統計）")
    print("\n出場原因分布：")
    for k, g in res.groupby("exit_reason"):
        print(f"  {k:6s} {len(g):4d} 筆｜勝率 {(g['ret'] > 0).mean():.0%}｜平均 {g['ret'].mean():+.2%}")
    print("\n各年訊號表現（依訊號日）：")
    res2 = res.copy()
    res2["year"] = pd.to_datetime(res2["signal_date"]).dt.year
    for y, g in res2.groupby("year"):
        print(f"  {y}：{len(g):4d} 筆｜勝率 {(g['ret'] > 0).mean():.0%}｜平均 {g['ret'].mean():+.2%}")
    print("\n依訊號日燈號：")
    for k, g in res.groupby("light"):
        print(f"  {k:6s} {len(g):4d} 筆｜勝率 {(g['ret'] > 0).mean():.0%}｜平均 {g['ret'].mean():+.2%}")


# ---------- 參數敏感度掃描（測穩健，不是找最大） ----------

def sweep(market: str, start: str) -> None:
    """對書中參數做敏感度掃描＋樣本內/外驗證。"""
    res_all = run(market, start, verbose=False, return_prepared=True)
    trades_fn = res_all["simulate"]

    def stats(df: pd.DataFrame) -> str:
        if not len(df):
            return "無交易"
        wins = df[df["ret"] > 0]["ret"]
        losses = df[df["ret"] <= 0]["ret"]
        pf = wins.sum() / abs(losses.sum()) if len(losses) and losses.sum() != 0 else float("inf")
        return (f"{len(df):5d} 筆｜勝率 {(df['ret'] > 0).mean():5.1%}｜"
                f"平均 {df['ret'].mean():+6.2%}｜獲利因子 {pf:4.2f}")

    book = dict(stop_pct=0.08, spr_threshold=1.17, warn_pct=0.07, max_gap=0.05)
    print("\n===== 基準（書中參數）=====")
    base = trades_fn(**book)
    print("  " + stats(base))

    print("\n===== 敏感度：停損 %（其他固定書中值）=====")
    for v in (0.06, 0.07, 0.08, 0.09, 0.10, 0.12):
        print(f"  停損 {v:.0%}: " + stats(trades_fn(**{**book, "stop_pct": v, "warn_pct": max(0.0, v - 0.01)})))

    print("\n===== 敏感度：賣壓比例門檻 =====")
    for v in (1.10, 1.13, 1.15, 1.17, 1.19, 1.22, 1.25):
        print(f"  SPR {v:.0%}: " + stats(trades_fn(**{**book, "spr_threshold": v})))

    print("\n===== 敏感度：追高上限 =====")
    for v in (0.02, 0.03, 0.05, 0.08, 9.99):
        label = f"{v:.0%}" if v < 1 else "不設限"
        print(f"  跳高 {label}: " + stats(trades_fn(**{**book, "max_gap": v})))

    print("\n===== 樣本內（2022~2024）vs 樣本外（2025~）=====")
    full = trades_fn(**book)
    full["sd"] = pd.to_datetime(full["signal_date"])
    ins = full[full["sd"] < "2025-01-01"]
    outs = full[full["sd"] >= "2025-01-01"]
    print("  書中參數 樣本內: " + stats(ins))
    print("  書中參數 樣本外: " + stats(outs))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["tw", "us"], default="tw")
    ap.add_argument("--start", default="2022-01-01", help="訊號起始日")
    ap.add_argument("--end", default=None)
    ap.add_argument("--sweep", action="store_true", help="參數敏感度掃描")
    args = ap.parse_args()
    if args.sweep:
        sweep(args.market, args.start)
        return
    res = run(args.market, args.start, args.end)
    out = BT_DIR / f"backtest_{args.market}.csv"
    res.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n[bt] 逐筆明細已存 {out}")


if __name__ == "__main__":
    main()
