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
import yfinance as yf

from engine import ai_judge as aij, cross, datastore, extras, notify, paper as pp, report, universe
from engine.box import scan as boxscan
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


def fundamental_items(market: str, ticker: str, close_price: float, cfg: dict) -> dict:
    """檢核表③④⑤⑥⑧（財報＋本益比）——大漲候選與箱型交叉檢核共用。"""
    if market == "tw":
        stock_id = ticker.split(".")[0]
        f = fu.tw_fundamentals(stock_id)
        pe = None
        if f.get("eps_ttm") and f["eps_ttm"] > 0:
            pe = close_price / f["eps_ttm"]
    else:
        f = fu.us_fundamentals(ticker)
        pe = f.get("pe")
    return {
        "3": fu.grade_long_term_growth(f["annual_pretax"], cfg["long_term_growth"]),
        "4": fu.grade_recent_annual_growth(f["annual_pretax"], f["quarterly"], cfg["recent_growth"]),
        "5": fu.grade_quarterly_revenue(f["quarterly"], f["monthly_rev_yoy"], cfg["quarterly_revenue_growth"]),
        "6": fu.grade_quarterly_profit(f["quarterly"], cfg["quarterly_profit_growth"]),
        "8": fu.grade_pe(pe, cfg["pe_limit"]),
    }


def enrich_fundamentals(market: str, cand: dict, cfg: dict, gauge: dict) -> dict:
    """③~⑨ 檢核，組成評分卡。"""
    items = {
        "1": ("O", f"收盤 {cand['close']:g} 創近 2 年新高"),
        "2": (
            cand["rebound_grade"],
            f"反彈幅度 {cand['rebound']:.0%}（目標≥60%），平穩期品質 {cand['base_quality']:.0%}"
            + "——建議自己看一眼月K線確認平穩期（書 p.72：無法純用程式認定）",
        ),
        **fundamental_items(market, cand["ticker"], cand["close"], cfg),
        "9": (
            {"green": "O", "yellow": "T", "red": "X"}.get(gauge["light"], "T"),
            gauge["reason"],
        ),
    }
    cand["_items"] = items  # 保留原始評分，AI 判斷後重建評分卡用
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
            # p.228 輔助條件：收盤跌破近 N 日最低收盤價
            win = cfg.get("low_break_window", 20)
            closes = ohlcv["Close"]
            near_low = len(closes) > win and float(closes.iloc[-1]) <= float(closes.iloc[-(win + 1):-1].min())
            result = sl.evaluate_holding(
                buy_price=h["buy_price"],
                close=close,
                latest_quarter_yoy=latest_yoy,
                spr=spr,
                stop_loss_pct=cfg["stop_loss_pct"],
                spr_threshold=cfg["spr_threshold"],
                near_stop_new_low=near_low,
                stop_warn_pct=cfg.get("stop_warn_pct", 0.07),
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

    # 休市保護：最新資料日期和上次處理的一樣（假日/補假），代表沒有新交易日，
    # 直接結束——避免同一天的訊號重複寄信、虛擬操盤重複處理
    prev_date = (report.load_state().get(market) or {}).get("date")
    if prev_date == date_str:
        print(f"[main] {date_str} 已處理過（今日休市，無新資料），跳過本次執行")
        return

    # 資料覆蓋率保險絲：當日有效檔數過低（資料源限流）→ 讓執行失敗，
    # 備援排程稍後會自動重試；絕不用殘缺資料產生訊號
    valid_today = int(close.iloc[-1].notna().sum())
    if valid_today < len(uni) * 0.3:
        raise SystemExit(
            f"[main] 資料異常：{date_str} 僅 {valid_today}/{len(uni)} 檔有效價格"
            f"（可能被資料源限流），中止本次執行，等待備援排程重試"
        )

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
    # 3.5 AI 第⑦項判斷（僅對較強候選執行，控制免費額度；失敗自動退回人工模式）
    for c in buy_candidates:
        c["mech_verdict"] = c["scorecard"]["verdict"]  # 純機械結論（虛擬操盤依此，不受 AI 影響）
        c["mech_score"] = c["scorecard"]["score"]      # 純機械分數（虛擬操盤部位計算用）
    judged = 0
    for c in sorted(buy_candidates, key=lambda x: x["scorecard"]["score"], reverse=True):
        if judged >= cfg.get("max_ai_judgments_per_day", 8):
            break
        v = c["scorecard"]["verdict"]
        if v.startswith("淘汰") or v.startswith("偏弱"):
            continue
        ftext = "；".join(
            it["detail"] for it in c["scorecard"]["items"] if it["key"] in ("3", "4", "5", "6")
        )
        try:
            ai7 = aij.judge_candidate(market, c["ticker"], c["name"], ftext, cfg)
        except Exception:
            print(f"[ai_judge] {c['ticker']} 判斷異常，退回人工：\n{traceback.format_exc()}")
            ai7 = None
        if ai7:
            c["ai7"] = ai7
            c["scorecard"] = build_scorecard(c["_items"], ai7=ai7)
            judged += 1
            time.sleep(2)
    for c in buy_candidates:
        c.pop("_items", None)
    if judged:
        print(f"[ai_judge] 已完成 {judged} 檔 AI 第⑦項判斷")

    # 依檢核分數排序（儀表板與 Email 都由高至低呈現）
    buy_candidates.sort(key=lambda c: c["scorecard"]["score"], reverse=True)
    # 淘汰硬性不合格者不寄信，但保留在儀表板供學習
    notified = [c for c in buy_candidates if not c["scorecard"]["verdict"].startswith("淘汰") and c["scorecard"]["score"] >= cfg["min_score_to_notify"]]

    # 3.8 箱型策略掃描（自 stock-box-system 移植，台股＋美股；參數與原系統相同）
    box_candidates: list[dict] = []
    if cfg.get("box_enabled", True):
        try:
            box_candidates = boxscan.scan_box(
                close, names, lambda tk: datastore.fetch_ohlcv(tk, period="1y"), cfg
            )
        except Exception:
            print(f"[box] 掃描失敗（不影響主策略）：\n{traceback.format_exc()}")

    # 3.85 交叉檢核：大漲候選跑箱型檢核、箱型候選跑書中基本面檢核 → 綜合訊號
    high_3y = close.max()
    for c in buy_candidates:
        h3 = high_3y.get(c["ticker"])
        if h3 is None or pd.isna(h3):
            c["box_check"] = {"pass": False, "reason": "無 3 年高價資料"}
            continue
        try:
            ohlcv = datastore.fetch_ohlcv(c["ticker"], period="1y")
            c["box_check"] = cross.box_status(ohlcv, float(h3), cfg)
        except Exception:
            print(f"[cross] {c['ticker']} 箱型檢核失敗：\n{traceback.format_exc()}")
            c["box_check"] = {"pass": False, "reason": "資料抓取失敗"}
        time.sleep(0.3)
    fund_checked = 0
    max_fund = int(cfg.get("box_fundamental_max", 20))
    for b in box_candidates:
        if fund_checked >= max_fund:
            # 箱型清單依距高點排序，超出上限的當日不檢核（控制 API 用量）
            b["fund_check"] = {"pass": False, "summary": "未檢核（超出當日上限）", "skipped": True}
            continue
        try:
            b["fund_check"] = cross.fund_check_result(
                fundamental_items(market, b["ticker"], b["close"], cfg)
            )
            fund_checked += 1
            time.sleep(cfg["fundamental_pause_sec"])
        except Exception:
            print(f"[cross] {b['ticker']} 基本面檢核失敗：\n{traceback.format_exc()}")
            b["fund_check"] = {"pass": False, "summary": "檢核失敗（資料源異常）"}
    combo_candidates = cross.combine(buy_candidates, box_candidates)
    if combo_candidates:
        print(f"[cross] 綜合訊號（雙檢核通過）：{len(combo_candidates)} 檔")

    # 3.9 附加資訊：候選股走勢縮圖、產業聚集、行事曆
    for c in buy_candidates + box_candidates:
        if c["ticker"] in close.columns:
            c["spark"] = extras.downsample(close[c["ticker"]].tail(500))
    industry_of = dict(zip(uni["ticker"], uni.get("industry", pd.Series(dtype=str)).fillna("未分類")))
    industries = extras.industry_summary(close, industry_of, names)

    # 4. 持股監控
    holdings = monitor_holdings(market, load_holdings(market), cfg)
    sell_alerts = [h for h in holdings if h["action"] != "HOLD"]

    # 4.5 虛擬操盤（紙上交易，追蹤方法成效）
    paper = pp.load_paper(cfg)
    pm = paper[market]
    pending = [o["ticker"] for o in pm["pending_buys"] + pm["pending_sells"]]
    opens: dict[str, float] = {}
    if pending:
        try:
            odf = yf.download(pending, period="5d", progress=False, auto_adjust=True)["Open"]
            if isinstance(odf, pd.Series):
                odf = odf.to_frame(pending[0])
            opens = {t: float(odf[t].dropna().iloc[-1]) for t in odf.columns if odf[t].notna().any()}
        except Exception:
            print(f"[paper] 開盤價抓取失敗，排單保留至下次：\n{traceback.format_exc()}")
    paper_evals = monitor_holdings(
        market,
        [{"ticker": p["ticker"], "name": p["name"], "buy_price": p["buy_price"]} for p in pm["positions"]],
        cfg,
    )
    closes_last = {t: float(v) for t, v in close.iloc[-1].dropna().items()}
    executed = pp.run_paper_cycle(
        pm, market, date_str, opens, closes_last, notified, paper_evals, gauge["light"],
        max_gap=cfg.get("max_gap_from_signal", 0.05),
    )
    pp.save_paper(paper)
    if executed:
        print(f"[paper] 今日虛擬成交 {len(executed)} 筆")

    # 4.6 行事曆：持股＋虛擬持倉的財報/除權息事件（只查持有的，控制 API 用量）
    watch = {(h["ticker"], h["name"]) for h in holdings}
    watch |= {(p["ticker"], p["name"]) for p in pm["positions"]}
    try:
        calendar = extras.build_calendar(market, sorted(watch))
    except Exception:
        print(f"[calendar] 建立失敗：\n{traceback.format_exc()}")
        calendar = []

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
        "box_candidates": box_candidates,
        "combo_candidates": combo_candidates,
        "industries": industries,
        "calendar": calendar,
        "holdings": holdings,
        "paper": {
            "start_capital": pm["start_capital"],
            "cash": round(pm["cash"], 2),
            "equity": pm["equity_history"][-1]["equity"] if pm["equity_history"] else pm["start_capital"],
            "equity_history": pm["equity_history"][-160:],
            "positions": [
                {**p,
                 "pnl_pct": p["last_price"] / p["buy_price"] - 1,
                 "stop_price": round(p["buy_price"] * (1 - cfg["stop_loss_pct"]), 2)}
                for p in pm["positions"]
            ],
            "trades": pm["trades"][-20:],
            "n_trades": len(pm["trades"]),
            "pending_buys": [o["name"] for o in pm["pending_buys"]],
            "pending_sells": [o["ticker"] for o in pm["pending_sells"]],
        },
    }
    report.save_state(state)

    report.archive_scorecards(date_str, market, buy_candidates)
    entries = [
        {"date": date_str, "market": MARKET_NAME[market], "type": "買進候選",
         "ticker": c["ticker"], "name": c["name"],
         "note": f"檢核 {c['scorecard']['score']}/100，{c['scorecard']['verdict']}",
         "scorecard": c["scorecard"]}
        for c in notified
    ] + [
        {"date": date_str, "market": MARKET_NAME[market],
         "type": "立即賣出" if h["action"] == "SELL_NOW" else "賣出訊號",
         "ticker": h["ticker"], "name": h["name"], "note": "；".join(h["reasons"])}
        for h in sell_alerts
    ] + [
        {"date": date_str, "market": MARKET_NAME[market], "type": "箱型訊號",
         "ticker": c["ticker"], "name": c["name"],
         "note": f"{c['kd_state']}，距3年收盤高 {c['pct_of_high']}%（K {c['k']}／D {c['d']}）"}
        for c in box_candidates
    ] + [
        {"date": date_str, "market": MARKET_NAME[market], "type": "綜合訊號",
         "ticker": e["ticker"], "name": e["name"],
         "note": "雙策略檢核通過："
                 + (f"檢核 {e['score']}/100，" if e.get("score") is not None else "")
                 + f"{e['kd_state']}，距3年高 {e['pct_of_high']}%"}
        for e in combo_candidates
    ]
    log = report.append_log(entries)
    report.render(state, log)

    # 6. Email
    box_for_email = box_candidates if cfg.get("box_email", True) else []
    if (notified or sell_alerts or box_for_email or combo_candidates) and not args.no_email:
        light = gauge["light"]
        hint = {
            "green": f"大盤綠燈：可依計畫買進，單檔上限＝總資產（{cfg['total_capital']:,}）的 10% ＝ {cfg['total_capital'] * 0.1:,.0f}",
            "yellow": "大盤黃燈：書中建議減少單次購買量（例如打對折）",
            "red": "大盤紅燈：書中建議此時不進場，訊號僅供記錄",
        }[light]
        subject, body = notify.format_signal_email(
            MARKET_NAME[market], date_str, notified, sell_alerts, gauge,
            cfg["dashboard_url"], hint, box_candidates=box_for_email,
            combo_candidates=combo_candidates,
        )
        notify.send_email(subject, body)
    else:
        print("[main] 無需通知的新訊號" if not args.no_email else "[main] 測試模式，不寄信")
    print("[main] 完成")


if __name__ == "__main__":
    main()
