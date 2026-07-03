"""每日執行入口：python -m engine.run_daily --market tw|us

流程：更新價格快取 → 大盤燈號 → 突破篩選 → 基本面檢核 → 持股監控 → 儀表板 + Email。
"""
from __future__ import annotations

import argparse
import csv
import time
import traceback
from pathlib import Path

import pandas as pd
import yaml

from engine import datastore, notify, report, universe
from engine.scoring import build_scorecard
from engine.signals import fundamentals as fu
from engine.signals import market as mk
from engine.signals import new_high as nh
from engine.signals import sell as sl
from engine.spr import selling_pressure_ratio

ROOT = Path(__file__).resolve().parent.parent
MARKET_NAME = {"tw": "台股", "us": "美股"}


def load_config() -> dict:
    return yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))


def load_holdings(market: str) -> list[dict]:
    p = ROOT / "holdings.csv"
    if not p.exists():
        return []
    out = []
    with p.open(encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("market", "").strip().lower() != market:
                continue
            try:
                out.append(
                    {
                        "ticker": row["ticker"].strip(),
                        "name": row.get("name", "").strip() or row["ticker"].strip(),
                        "buy_price": float(row["buy_price"]),
                    }
                )
            except (KeyError, ValueError):
                print(f"[holdings] 略過格式錯誤的列：{row}")
    return out


def screen_breakouts(close: pd.DataFrame, names: dict[str, str], cfg: dict) -> list[dict]:
    """①②：今日收盤創 2 年新高，且反彈幅度/距上次高點合格的候選。"""
    lookback = cfg["breakout_lookback_days"]
    candidates = []
    last_row = close.iloc[-1]
    prior_max = close.iloc[:-1].rolling(lookback, min_periods=int(lookback * 0.8)).max().iloc[-1]
    hit = last_row[(last_row > prior_max) & last_row.notna() & prior_max.notna()]
    print(f"[screen] 今日創 {lookback} 日新高：{len(hit)} 檔")
    for ticker in hit.index:
        s = close[ticker].dropna()
        if len(s) < lookback + 20:
            continue  # 上市未滿 2 年，無法認定平穩期
        try:
            long_close = datastore.fetch_long_close(ticker)
            time.sleep(0.3)
        except Exception:
            long_close = s
        if len(long_close) > lookback and nh.years_since_last_peak(long_close) > 10:
            continue  # 上次高點超過 10 年，書中排除
        reb = nh.rebound_from_history(long_close if len(long_close) > len(s) else s)
        grade2 = nh.grade_rebound(reb["ratio"])
        if grade2 == "X":
            continue
        candidates.append(
            {
                "ticker": ticker,
                "name": names.get(ticker, ticker),
                "close": round(float(s.iloc[-1]), 2),
                "rebound": reb["ratio"],
                "rebound_grade": grade2,
                "base_quality": nh.base_quality(s),
            }
        )
    # 依平穩期品質排序，最多細查 N 檔（控制 API 用量與執行時間）
    candidates.sort(key=lambda c: c["base_quality"], reverse=True)
    return candidates[: cfg["max_candidates_per_day"]]


def enrich_fundamentals(market: str, cand: dict, cfg: dict, gauge: dict) -> dict:
    """③~⑨ 檢核，組成評分卡。"""
    if market == "tw":
        stock_id = cand["ticker"].split(".")[0]
        f = fu.tw_fundamentals(stock_id)
        pe = None
        if f.get("eps_ttm") and f["eps_ttm"] > 0:
            pe = cand["close"] / f["eps_ttm"]
    else:
        f = fu.us_fundamentals(cand["ticker"])
        pe = f.get("pe")

    items = {
        "1": ("O", f"收盤 {cand['close']:g} 創近 2 年新高"),
        "2": (
            cand["rebound_grade"],
            f"反彈幅度 {cand['rebound']:.0%}（目標≥60%），平穩期品質 {cand['base_quality']:.0%}"
            + "——建議自己看一眼月K線確認平穩期（書 p.72：無法純用程式認定）",
        ),
        "3": fu.grade_long_term_growth(f["annual_pretax"], cfg["long_term_growth"]),
        "4": fu.grade_recent_annual_growth(f["annual_pretax"], f["quarterly"], cfg["recent_growth"]),
        "5": fu.grade_quarterly_revenue(f["quarterly"], f["monthly_rev_yoy"], cfg["quarterly_revenue_growth"]),
        "6": fu.grade_quarterly_profit(f["quarterly"], cfg["quarterly_profit_growth"]),
        "8": fu.grade_pe(pe, cfg["pe_limit"]),
        "9": (
            {"green": "O", "yellow": "T", "red": "X"}.get(gauge["light"], "T"),
            gauge["reason"],
        ),
    }
    cand["scorecard"] = build_scorecard(items)
    return cand


def monitor_holdings(market: str, holdings: list[dict], cfg: dict) -> list[dict]:
    out = []
    for h in holdings:
        try:
            ohlcv = datastore.fetch_ohlcv(h["ticker"])
            if ohlcv.empty:
                print(f"[holdings] {h['ticker']} 無價格資料，略過")
                continue
            close = float(ohlcv["Close"].iloc[-1])
            spr_series = selling_pressure_ratio(ohlcv, window=cfg["spr_window"])
            spr = float(spr_series.iloc[-1]) if pd.notna(spr_series.iloc[-1]) else None
            if market == "tw":
                f = fu.tw_fundamentals(h["ticker"].split(".")[0])
            else:
                f = fu.us_fundamentals(h["ticker"])
            latest_yoy = fu.latest_quarter_pretax_yoy(f["quarterly"])
            result = sl.evaluate_holding(
                buy_price=h["buy_price"],
                close=close,
                latest_quarter_yoy=latest_yoy,
                spr=spr,
                stop_loss_pct=cfg["stop_loss_pct"],
                spr_threshold=cfg["spr_threshold"],
            )
            out.append({**h, "close": round(close, 2), "spr": spr, **result})
        except Exception:
            print(f"[holdings] {h['ticker']} 監控失敗：\n{traceback.format_exc()}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["tw", "us"], required=True)
    ap.add_argument("--no-email", action="store_true", help="測試用：不寄信")
    ap.add_argument("--limit", type=int, default=0, help="測試用：只掃前 N 檔")
    args = ap.parse_args()
    market = args.market
    cfg = load_config()

    # 1. Universe 與價格
    uni = universe.tw_universe() if market == "tw" else universe.us_universe()
    if args.limit:
        uni = uni.head(args.limit)
    names = dict(zip(uni["ticker"], uni["name"]))
    print(f"[main] {MARKET_NAME[market]} universe：{len(uni)} 檔")
    close = datastore.update_close(market, uni["ticker"].tolist())
    date_str = close.index.max().strftime("%Y-%m-%d")
    print(f"[main] 價格快取更新完成，最新日期 {date_str}")

    # 2. 大盤燈號（⑨）
    ratio = mk.new_high_ratio_series(close)
    top50_hits = mk.top50_recent_new_highs(close, cfg[f"{market}_top50"])
    gauge = mk.market_light(ratio, len(top50_hits))
    n_new_high = int((close.iloc[-1] > close.shift(1).rolling(nh.TRADING_DAYS_1Y, min_periods=120).max().iloc[-1]).sum())
    print(f"[main] 大盤燈號：{gauge['light']}（{gauge['reason']}）")

    # 3. 買進篩選（①②→③~⑨）
    raw_cands = screen_breakouts(close, names, cfg)
    buy_candidates = []
    for c in raw_cands:
        try:
            buy_candidates.append(enrich_fundamentals(market, c, cfg, gauge))
            time.sleep(cfg["fundamental_pause_sec"])
        except Exception:
            print(f"[screen] {c['ticker']} 基本面檢核失敗：\n{traceback.format_exc()}")
    # 淘汰硬性不合格者不寄信，但保留在儀表板供學習
    notified = [c for c in buy_candidates if not c["scorecard"]["verdict"].startswith("淘汰") and c["scorecard"]["score"] >= cfg["min_score_to_notify"]]

    # 4. 持股監控
    holdings = monitor_holdings(market, load_holdings(market), cfg)
    sell_alerts = [h for h in holdings if h["action"] != "HOLD"]

    # 5. 狀態、記錄、儀表板
    state = report.load_state()
    state[market] = {
        "date": date_str,
        "gauge": gauge,
        "ratio_history": [round(float(x), 5) if pd.notna(x) else None for x in ratio.tail(120)],
        "top50_hits": top50_hits,
        "n_new_high": n_new_high,
        "n_universe": int(close.iloc[-1].notna().sum()),
        "buy_candidates": buy_candidates,
        "holdings": holdings,
    }
    report.save_state(state)

    entries = [
        {"date": date_str, "market": MARKET_NAME[market], "type": "買進候選",
         "ticker": c["ticker"], "name": c["name"],
         "note": f"檢核 {c['scorecard']['score']}/100，{c['scorecard']['verdict']}"}
        for c in notified
    ] + [
        {"date": date_str, "market": MARKET_NAME[market],
         "type": "立即賣出" if h["action"] == "SELL_NOW" else "賣出訊號",
         "ticker": h["ticker"], "name": h["name"], "note": "；".join(h["reasons"])}
        for h in sell_alerts
    ]
    log = report.append_log(entries)
    report.render(state, log)

    # 6. Email
    if (notified or sell_alerts) and not args.no_email:
        light = gauge["light"]
        hint = {
            "green": f"大盤綠燈：可依計畫買進，單檔上限＝總資產（{cfg['total_capital']:,}）的 10% ＝ {cfg['total_capital'] * 0.1:,.0f}",
            "yellow": "大盤黃燈：書中建議減少單次購買量（例如打對折）",
            "red": "大盤紅燈：書中建議此時不進場，訊號僅供記錄",
        }[light]
        subject, body = notify.format_signal_email(
            MARKET_NAME[market], date_str, notified, sell_alerts, gauge,
            cfg["dashboard_url"], hint,
        )
        notify.send_email(subject, body)
    else:
        print("[main] 無需通知的新訊號" if not args.no_email else "[main] 測試模式，不寄信")
    print("[main] 完成")


if __name__ == "__main__":
    main()
