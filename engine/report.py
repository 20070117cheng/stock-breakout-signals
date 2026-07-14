"""產生 GitHub Pages 儀表板（docs/index.html）——單檔、無外部依賴、無 emoji、分頁式。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
LOG_PATH = ROOT / "data" / "signals_log.json"
HTML_PATH = ROOT / "docs" / "index.html"

LIGHT = {
    "green": ("綠燈｜行情強", "#16a34a"),
    "yellow": ("黃燈｜行情普通", "#ca8a04"),
    "red": ("紅燈｜行情弱", "#dc2626"),
}
ACTION_LABEL = {
    "SELL_NOW": ("立即賣出", "#dc2626"),
    "SELL_SIGNAL": ("賣出訊號", "#ea580c"),
    "HOLD": ("續抱", "#16a34a"),
}


def _dot(color: str) -> str:
    return f'<span class="dot" style="background:{color}"></span>'


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def append_log(entries: list[dict]) -> list[dict]:
    log = json.loads(LOG_PATH.read_text(encoding="utf-8")) if LOG_PATH.exists() else []
    log.extend(entries)
    log = log[-300:]
    LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    return log


ARCHIVE_PATH = ROOT / "data" / "scorecards.json"
GRADE_SYMBOL = {"O": "○", "T": "△", "X": "×"}


def _archive_index() -> dict:
    """檢核表存檔索引：(訊號日, 代號) → 存檔項目。"""
    if not ARCHIVE_PATH.exists():
        return {}
    arch = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
    return {(e["date"], e["ticker"]): e for e in arch}


def archive_scorecards(date: str, market: str, candidates: list[dict]) -> None:
    """把當日所有候選股的完整檢核表永久存檔（滾動保留 5000 筆），供日後績效複盤。"""
    arch = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8")) if ARCHIVE_PATH.exists() else []
    existing = {(e["date"], e["ticker"]) for e in arch}
    for c in candidates:
        if (date, c["ticker"]) in existing:
            continue
        ai = c.get("ai7")
        arch.append(
            {
                "date": date,
                "market": market,
                "ticker": c["ticker"],
                "name": c["name"],
                "close": c["close"],
                "rebound": round(c.get("rebound", 0), 3),
                "base_quality": round(c.get("base_quality", 0), 3),
                "scorecard": c["scorecard"],
                "ai7": {"grade": ai["grade"], "one_line": ai["one_line"]} if ai else None,
            }
        )
    arch = arch[-5000:]
    ARCHIVE_PATH.parent.mkdir(exist_ok=True)
    ARCHIVE_PATH.write_text(json.dumps(arch, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[archive] 檢核表存檔共 {len(arch)} 筆")


def _sparkline(values: list[float], color: str = "#2563eb", w: int = 240, h: int = 48) -> str:
    vals = [v for v in values if v is not None and v == v] if values else []
    if len(vals) < 2:
        return ""
    mn, mx = min(vals), max(vals)
    rng = (mx - mn) or 1e-9
    pts = " ".join(
        f"{i * w / (len(vals) - 1):.1f},{h - 4 - (v - mn) / rng * (h - 8):.1f}"
        for i, v in enumerate(vals)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}">'
        f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/></svg>'
    )


def _market_card(name: str, m: dict | None) -> str:
    if not m:
        return f'<div class="card"><h3>{name}</h3><p>尚無資料（等第一次排程執行）</p></div>'
    label, color = LIGHT.get(m["gauge"]["light"], LIGHT["yellow"])
    ratio = m["gauge"].get("ratio_now")
    ratio_txt = f"{ratio:.2%}" if ratio is not None else "—"
    spark = _sparkline(m.get("ratio_history", []), color)
    top50 = m.get("top50_hits", [])
    return f"""<div class="card">
  <h3>{name} <span style="color:{color}">{_dot(color)} {label}</span></h3>
  <p class="big">創新高股比率：<b>{ratio_txt}</b></p>
  {spark}
  <p>{m['gauge']['reason']}</p>
  <p class="muted">前50大市值股近3個月創兩年新高：{len(top50)} 檔{('（' + '、'.join(top50[:8]) + ('…' if len(top50) > 8 else '') + '）') if top50 else ''}</p>
  <p class="muted">資料日期：{m.get('date', '—')}｜今日創一年新高：{m.get('n_new_high', 0)} 檔 / 掃描 {m.get('n_universe', 0)} 檔</p>
</div>"""


def _scorecard_table(sc: dict) -> str:
    rows = []
    for it in sc["items"]:
        star = "★" if it["starred"] else ""
        sym = "人工" if it["grade"] == "M" else it["symbol"]
        rows.append(
            f"<tr><td>{star}</td><td>{it['name']}</td>"
            f"<td class='sym'>{sym}</td><td class='muted'>{it['detail']}</td></tr>"
        )
    return (
        "<table class='check'><thead><tr><th></th><th>檢核項目</th><th>結果</th><th>說明</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _ai_block(ai7: dict | None) -> str:
    if not ai7:
        return ""
    grade_txt = {"O": "看好（○）", "T": "存疑（△）", "X": "不看好（×）"}.get(ai7["grade"], "—")
    srcs = "".join(
        f"<li><a href='{s['link']}' target='_blank' rel='noopener'>{s['title']}</a>"
        f"<span class='muted'>（{s['source']}，{s['date']}）</span></li>"
        for s in ai7.get("sources", [])
    ) or "<li class='muted'>未引用特定新聞（僅依營運數字判斷）</li>"
    return f"""<div class="aibox">
  <p><b>AI 第⑦項判斷：{grade_txt}</b>——{ai7['one_line']}</p>
  <p><b>推理過程：</b>{ai7.get('analysis', '')}</p>
  <p><b>主要風險：</b>{ai7.get('risks', '')}</p>
  <p><b>引用來源（點連結自行查證）：</b></p>
  <ul>{srcs}</ul>
  <p class="muted">模型：{ai7.get('model', '')}｜判斷時間：{ai7.get('judged_at', '')}｜
  AI 只讀取上列公開資訊，可能出錯——買進前請自行複核，特別是去看公司法說會（書 p.131-146）。</p>
</div>"""


def _candidates_section(state: dict) -> str:
    entries = []
    for mkt_key, mkt_name in [("tw", "台股"), ("us", "美股")]:
        m = state.get(mkt_key) or {}
        for c in m.get("buy_candidates", []):
            entries.append((c["scorecard"]["score"], mkt_name, m.get("date", ""), c))
    entries.sort(key=lambda e: e[0], reverse=True)  # 檢核分數高者排前
    cards = []
    for score, mkt_name, date, c in entries:
        sc = c["scorecard"]
        cards.append(f"""<details class="card cand">
  <summary><b>{sc['score']}/100</b>｜{mkt_name}｜<b>{c['name']}（{c['ticker']}）</b>
    收盤 {c['close']:g} — {sc['verdict']}</summary>
  {_scorecard_table(sc)}
  {_ai_block(c.get('ai7'))}
  <p class="muted">反彈幅度 {c.get('rebound', 0):.0%}｜平穩期品質 {c.get('base_quality', 0):.0%}｜訊號日 {date}</p>
</details>""")
    if not cards:
        return "<p class='empty'>今日沒有通過篩選的突破新高候選股。書中提醒：下跌行情裡本來就不會出現創新高股，沒訊號就空手等待（p.87）。</p>"
    return "\n".join(cards)


def _box_section(state: dict) -> str:
    rows = []
    for mkt_key, mkt_name in [("tw", "台股"), ("us", "美股")]:
        m = state.get(mkt_key) or {}
        for c in m.get("box_candidates", []):
            rows.append(
                f"<tr><td>{mkt_name}</td><td><b>{c['name']}</b><br class='m'>{c['ticker']}</td>"
                f"<td>{c['close']:g}</td><td>{c['high_close_3y']:g}</td>"
                f"<td>{c['pct_of_high']:.1f}%</td><td>{c['k']:g} / {c['d']:g}</td>"
                f"<td><b>{c['kd_state']}</b></td></tr>"
            )
    if not rows:
        return ("<p class='empty'>今日沒有箱型訊號（貼近 3 年高點且 KD 剛金叉／將金叉的股票）。"
                "沒訊號空手等待即可。</p>")
    return (
        "<table><thead><tr><th>市場</th><th>股票</th><th>現價</th><th>3年收盤高</th>"
        "<th>距高點</th><th>K / D</th><th>KD 狀態</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def _holdings_section(state: dict) -> str:
    rows = []
    for mkt_key, mkt_name in [("tw", "台股"), ("us", "美股")]:
        m = state.get(mkt_key) or {}
        for h in m.get("holdings", []):
            label, color = ACTION_LABEL.get(h["action"], ACTION_LABEL["HOLD"])
            reasons = "<br>".join(h["reasons"]) if h["reasons"] else "三項賣出檢查皆未觸發"
            spr = f"{h['spr']:.0%}" if h.get("spr") else "—"
            rows.append(
                f"<tr><td>{mkt_name}</td><td><b>{h['name']}</b><br class='m'>{h['ticker']}</td>"
                f"<td>{h['buy_price']:g}</td><td>{h['close']:g}</td>"
                f"<td style='color:{'#16a34a' if h['pnl_pct'] >= 0 else '#dc2626'}'>{h['pnl_pct']:+.1%}</td>"
                f"<td>{spr}</td><td style='color:{color};font-weight:700'>{label}</td>"
                f"<td class='muted'>{reasons}</td></tr>"
            )
    if not rows:
        return "<p class='empty'>尚未登錄持股。買進後請到 GitHub 編輯 <code>holdings.csv</code>，系統就會每天幫你檢查停損、基本面與賣壓比例。</p>"
    return (
        "<table><thead><tr><th>市場</th><th>股票</th><th>買價</th><th>現價</th>"
        "<th>損益</th><th>賣壓比例</th><th>狀態</th><th>說明</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


def _paper_card(name: str, currency: str, p: dict | None) -> str:
    if not p:
        return f'<div class="card"><h3>{name}</h3><p>尚無資料（等下一次排程執行後開始模擬）</p></div>'
    equity = p["equity"]
    ret = equity / p["start_capital"] - 1
    ret_color = "#16a34a" if ret >= 0 else "#dc2626"
    spark = _sparkline([e["equity"] for e in p.get("equity_history", [])], ret_color)
    def _pos_row(q: dict) -> str:
        label, color = ACTION_LABEL.get(q.get("status", "HOLD"), ACTION_LABEL["HOLD"])
        note = f"<br><span class='muted'>{q['status_note']}</span>" if q.get("status_note") else ""
        stop = f"{q['stop_price']:g}" if q.get("stop_price") else "—"
        return (
            f"<tr><td><b>{q['name']}</b><br class='m'>{q['ticker']}</td>"
            f"<td>{q['buy_date']}</td><td>{q['buy_price']:g}</td>"
            f"<td style='color:#dc2626'>{stop}</td><td>{q['last_price']:g}</td>"
            f"<td style='color:{'#16a34a' if q['pnl_pct'] >= 0 else '#dc2626'}'>{q['pnl_pct']:+.1%}</td>"
            f"<td style='color:{color};font-weight:700'>{label}{note}</td></tr>"
        )

    pos_rows = "".join(_pos_row(q) for q in p.get("positions", [])) or \
        "<tr><td colspan='7' class='muted'>目前空手（等待強力候選訊號）</td></tr>"
    action_txt = {"BUY": "買進", "SELL": "賣出", "SKIP": "放棄追高"}
    trade_rows = "".join(
        f"<tr><td>{t['date']}</td><td>{action_txt.get(t['action'], t['action'])}</td>"
        f"<td><b>{t['name']}</b></td><td>{t['price']:g}</td>"
        f"<td>{('%+.1f%%' % (t['pnl_pct'] * 100)) if 'pnl_pct' in t else '—'}</td>"
        f"<td class='muted'>{t['reason']}</td></tr>"
        for t in reversed(p.get("trades", []))
    ) or "<tr><td colspan='6' class='muted'>尚無成交記錄</td></tr>"

    # 買入理由：從檢核表存檔撈出每檔持倉「訊號日」的完整檢核表
    idx = _archive_index()
    reason_blocks = []
    for q in p.get("positions", []):
        sd = q.get("signal_date", "")
        e = idx.get((sd, q["ticker"])) if sd else None
        if e:
            sc = e["scorecard"]
            ai = e.get("ai7")
            ai_line = (f"<p class='muted'>AI 第⑦項（參考）：{GRADE_SYMBOL.get(ai['grade'], ai['grade'])}——{ai['one_line']}</p>"
                       if ai else "")
            reason_blocks.append(f"""<details class="cand">
  <summary>買入理由：<b>{q['name']}</b>｜訊號日 {sd} 檢核 <b>{sc['score']}/100</b> — {sc['verdict']}</summary>
  <p class='muted'>為何選這檔：訊號日收盤 {e['close']:g} 突破 2 年新高（反彈幅度 {e.get('rebound', 0):.0%}），
  基本面檢核為「強力候選」，依當日檢核分數排序入選（每日最多 3 檔），隔日開盤機械式買進。</p>
  {_scorecard_table(sc)}{ai_line}</details>""")
        elif sd:
            reason_blocks.append(f"<p class='muted'>{q['name']}：訊號日 {sd} 的檢核表未在存檔中（存檔功能上線前的訊號）。</p>")
    reasons_html = (
        "<h4>買入理由（點開看訊號日的完整檢核表）</h4>" + "\n".join(reason_blocks)
        if reason_blocks else ""
    )
    pending = ""
    if p.get("pending_buys") or p.get("pending_sells"):
        pb = "、".join(p["pending_buys"]) or "無"
        ps = "、".join(p["pending_sells"]) or "無"
        pending = f"<p class='muted'>明日開盤排單——買進：{pb}｜賣出：{ps}</p>"
    return f"""<div class="card">
  <h3>{name}</h3>
  <p class="big">總資產：<b>{equity:,.0f} {currency}</b>
     <span style="color:{ret_color};font-weight:700">（{ret:+.2%}）</span></p>
  <p class="muted">起始 {p['start_capital']:,.0f}｜現金 {p['cash']:,.0f}｜累計成交 {p.get('n_trades', 0)} 筆</p>
  {spark}
  {pending}
  <h4>持倉（賣出三條件每天自動檢查）</h4>
  <table><thead><tr><th>股票</th><th>買進日</th><th>買價</th><th>停損價</th><th>現價</th><th>損益</th><th>賣出檢查</th></tr></thead>
  <tbody>{pos_rows}</tbody></table>
  {reasons_html}
  <h4>近期成交（賣出會顯示在這裡，含損益與原因）</h4>
  <table><thead><tr><th>日期</th><th>動作</th><th>股票</th><th>成交價</th><th>損益</th><th>原因</th></tr></thead>
  <tbody>{trade_rows}</tbody></table>
</div>"""


def _log_section(log: list[dict]) -> str:
    if not log:
        return "<p class='empty'>尚無訊號記錄。</p>"
    rows = []
    for e in reversed(log[-60:]):
        if e.get("scorecard"):
            detail = (
                f"<details><summary class='muted'>{e['note']}（點開看訊號日檢核表）</summary>"
                f"{_scorecard_table(e['scorecard'])}</details>"
            )
        else:
            detail = f"<span class='muted'>{e['note']}</span>"
        rows.append(
            f"<tr><td>{e['date']}</td><td>{e['market']}</td><td>{e['type']}</td>"
            f"<td><b>{e['name']}（{e['ticker']}）</b></td><td>{detail}</td></tr>"
        )
    return (
        "<table><thead><tr><th>日期</th><th>市場</th><th>訊號</th><th>股票</th><th>說明</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def render(state: dict, log: list[dict]) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    g, y, r = "#16a34a", "#ca8a04", "#dc2626"
    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>大漲訊號儀表板</title>
<style>
:root {{ font-family: "Microsoft JhengHei", "PingFang TC", system-ui, sans-serif; }}
body {{ margin: 0; background: #f1f5f9; color: #0f172a; }}
header {{ background: #0f172a; color: #fff; padding: 20px 16px; }}
header h1 {{ margin: 0 0 4px; font-size: 22px; }}
header p {{ margin: 0; color: #94a3b8; font-size: 13px; }}
main {{ max-width: 1000px; margin: 0 auto; padding: 16px; }}
h2 {{ font-size: 18px; border-left: 4px solid #2563eb; padding-left: 10px; margin: 28px 0 12px; }}
h4 {{ margin: 16px 0 8px; font-size: 14px; color: #475569; }}
.card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
.big {{ font-size: 17px; margin: 6px 0; }}
.muted {{ color: #64748b; font-size: 13px; }}
.empty {{ background: #fff; border-radius: 12px; padding: 20px; color: #64748b; }}
.dot {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; margin-right: 2px; vertical-align: baseline; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; font-size: 14px; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
th {{ background: #f8fafc; font-size: 13px; color: #475569; }}
.check td.sym {{ font-size: 15px; text-align: center; }}
details.cand summary {{ cursor: pointer; font-size: 15px; line-height: 1.6; }}
.help {{ background: #eff6ff; border-radius: 12px; padding: 14px 16px; font-size: 14px; line-height: 1.8; }}
.aibox {{ background: #fefce8; border: 1px solid #fde047; border-radius: 10px; padding: 12px 14px;
  margin-top: 10px; font-size: 14px; line-height: 1.7; }}
.aibox ul {{ margin: 4px 0; padding-left: 20px; }}
.formrow {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }}
.formrow input, .formrow select {{ padding: 8px 10px; border: 1px solid #cbd5e1; border-radius: 8px;
  font-size: 14px; font-family: inherit; flex: 1 1 120px; min-width: 0; }}
.btn {{ padding: 8px 16px; border: 0; border-radius: 8px; background: #2563eb; color: #fff;
  font-size: 14px; font-family: inherit; cursor: pointer; flex: 0 0 auto; }}
.btn-red {{ background: #dc2626; }}
.tag {{ display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 12px;
  font-weight: 700; white-space: nowrap; line-height: 1.6; }}
.tag-book {{ background: #dcfce7; color: #15803d; }}
.tag-sys {{ background: #fef9c3; color: #a16207; }}
.tag-ai {{ background: #ede9fe; color: #6d28d9; }}
footer {{ text-align: center; color: #94a3b8; font-size: 12px; padding: 24px; }}
.tabs {{ position: sticky; top: 0; z-index: 10; display: flex; gap: 4px; background: #0f172a;
  padding: 8px 12px; overflow-x: auto; -webkit-overflow-scrolling: touch; }}
.tabs button {{ flex-shrink: 0; border: 0; border-radius: 999px; padding: 8px 16px; font-size: 14px;
  background: #1e293b; color: #cbd5e1; cursor: pointer; font-family: inherit; }}
.tabs button.active {{ background: #2563eb; color: #fff; font-weight: 700; }}
.tab {{ display: none; }}
.tab.active {{ display: block; }}
@media (max-width: 640px) {{ th, td {{ padding: 6px; font-size: 12px; }} .tabs button {{ padding: 8px 12px; font-size: 13px; }} }}
</style>
</head>
<body>
<header>
  <h1>大漲訊號儀表板</h1>
  <p>依《大漲的訊號》創新高價投資法自動掃描台股（上市+上櫃）與美股（S&P 500 + NASDAQ 100）｜更新：{now}</p>
</header>
<nav class="tabs">
  <button data-tab="market" class="active">大盤燈號</button>
  <button data-tab="buy">買進候選</button>
  <button data-tab="box">箱型訊號</button>
  <button data-tab="hold">持股監控</button>
  <button data-tab="paper">虛擬操盤</button>
  <button data-tab="log">訊號記錄</button>
  <button data-tab="learn">方法教學</button>
</nav>
<main>

<section id="tab-market" class="tab active">
<h2>今天可以進場嗎？（大盤上漲力道）</h2>
<div class="grid">
{_market_card("台股", state.get("tw"))}
{_market_card("美股", state.get("us"))}
</div>
<div class="help">{_dot(g)} 綠燈＝創新高股多、行情強，可依計畫買進（單檔上限＝總資產 10%）｜
{_dot(y)} 黃燈＝力道普通，減量操作｜{_dot(r)} 紅燈＝創新高股稀少，書中建議空手等待。
判斷依據：全市場「創一年新高家數比率」與前 50 大市值股動向（書第二章第六節）。<br>
<b>誠實標註：</b>書中只給質性原則（比率高＝漲勢強、低＝弱），並明言「沒有一個必漲的基準點、套公式很危險」（p.91），
要求投資人自行比對比率的歷史走勢。燈號是本系統把「比對歷史」自動化的近似（位置＝現值在近一年中的相對高低；
趨勢＝現值 vs 約一個月前），僅供快速參考——上方那條比率走勢線才是書中真正要你看的東西：
比率在爬升、前 50 大開始創高，就是書中的行情轉強格局（p.90 的領先訊號）。</div>

<h2>資料來源</h2>
<table>
<thead><tr><th>資料</th><th>來源</th><th>用途</th><th>更新頻率</th></tr></thead>
<tbody>
<tr><td>股價（台股＋美股）</td>
    <td><a href="https://finance.yahoo.com" target="_blank" rel="noopener">Yahoo Finance</a>（yfinance）</td>
    <td>突破新高偵測、大盤燈號、停損監控、賣壓比例、虛擬操盤成交價</td><td>每個交易日收盤後</td></tr>
<tr><td>台股公司清單</td>
    <td><a href="https://finmindtrade.com" target="_blank" rel="noopener">FinMind</a></td>
    <td>掃描範圍（上市＋上櫃全部普通股）</td><td>每次執行</td></tr>
<tr><td>台股財報（稅前淨利、營收、EPS）</td>
    <td><a href="https://finmindtrade.com" target="_blank" rel="noopener">FinMind</a>
        （原始來源：<a href="https://mops.twse.com.tw" target="_blank" rel="noopener">公開資訊觀測站</a>）</td>
    <td>檢核表③④⑤⑥⑧、持股基本面監控</td><td>候選股出現時查詢</td></tr>
<tr><td>台股月營收</td>
    <td><a href="https://finmindtrade.com" target="_blank" rel="noopener">FinMind</a></td>
    <td>檢核表⑤（營收動能輔助）</td><td>候選股出現時查詢</td></tr>
<tr><td>美股財報與本益比</td>
    <td><a href="https://finance.yahoo.com" target="_blank" rel="noopener">Yahoo Finance</a>（yfinance）</td>
    <td>檢核表③④⑤⑥⑧、持股基本面監控</td><td>候選股出現時查詢</td></tr>
<tr><td>美股成分股清單</td>
    <td><a href="https://en.wikipedia.org/wiki/List_of_S%26P_500_companies" target="_blank" rel="noopener">Wikipedia S&amp;P 500</a>、
        <a href="https://en.wikipedia.org/wiki/Nasdaq-100" target="_blank" rel="noopener">Wikipedia Nasdaq-100</a></td>
    <td>掃描範圍</td><td>每次執行</td></tr>
<tr><td>個股新聞</td>
    <td><a href="https://news.google.com" target="_blank" rel="noopener">Google News</a></td>
    <td>AI 第⑦項判斷的證據（各評分卡內附引用連結）</td><td>AI 判斷時查詢</td></tr>
<tr><td>AI 模型</td>
    <td><a href="https://ai.google.dev" target="_blank" rel="noopener">Google Gemini API</a></td>
    <td>檢核表第⑦項參考意見（推理過程顯示於評分卡）</td><td>每日最多 8 檔</td></tr>
<tr><td>系統程式碼與執行紀錄</td>
    <td><a href="https://github.com/20070117cheng/stock-breakout-signals" target="_blank" rel="noopener">GitHub（本專案）</a></td>
    <td>所有規則與計算公開可查，Actions 頁可看每次執行過程</td><td>—</td></tr>
</tbody>
</table>
<p class="muted">所有資料源皆為免費公開資料，可能有延遲或錯漏；關鍵決策前建議至券商軟體或
<a href="https://mops.twse.com.tw" target="_blank" rel="noopener">公開資訊觀測站</a>複核原始數字。</p>
</section>

<section id="tab-buy" class="tab">
<h2>買進候選（今日突破 2 年新高＋基本面檢核）</h2>
{_candidates_section(state)}
<div class="help">每張評分卡對應書中附錄一的 9 項檢核表（★＝書中標示的重要項目）。
<b>第⑦項未來獲利判斷</b>：設定 AI 金鑰後，系統會自動蒐集新聞與營運數字請 AI 判斷，
並在評分卡下方的黃色區塊完整顯示「推理過程＋引用來源」——AI 是參考意見，買進前請點來源連結自行查證，
行有餘力再看公司法說會（書 p.131-146：成長理由要能一句話說清楚，聽到景氣發言就淘汰）。<br>
<b>為什麼只列「今日」的訊號？</b>訊號的定義是「收盤價」創 2 年新高，收盤後才能確認；買進時機就是隔天開盤（機械式操作）。
過幾天才追買，進場價偏離訊號價，8% 停損的風險設計就失效了。錯過的訊號請放掉，去「訊號記錄」分頁複盤即可。</div>
</section>

<section id="tab-box" class="tab">
<h2>箱型訊號（KD 金叉＋貼近 3 年高，台股＋美股）</h2>
{_box_section(state)}
<div class="help"><b>這是你原本「箱型系統」的訊號引擎</b>，已原封移植到這裡（判斷邏輯逐行相同）：
現價 ≥ 3 年收盤高點的 95%，且 KD(9) 剛黃金交叉（昨 K&lt;D、今 K≥D）或準備交叉（D−K ≤ 2）。<br>
出場規則沿用你的設定：<b>移動停利 10%／固定停損 3%</b>（下一階段會連同專屬虛擬帳戶一起接上，
與大漲訊號策略同台比較成效）。<br>
<b>與「買進候選」的差別</b>：箱型看的是「貼近高點＋KD 翻多」的短波段節奏，不檢查基本面；
大漲訊號看的是「突破新高＋獲利加速」的長波段。兩者訊號重疊時，代表技術面共振，值得優先研究。<br>
箱型訊號會寫進每日 Email（同一封信的「箱型訊號」段），不想收改 config 的 <code>box_email</code>。</div>
</section>

<section id="tab-hold" class="tab">
<h2>持股監控（賣出三條件）</h2>
{_holdings_section(state)}

<div class="card">
<h4>快速登錄（送出後約 1 分鐘自動寫入，下次掃描開始監控）</h4>
<div class="formrow">
  <select id="f-mkt">
    <option value=".TW">台股上市</option>
    <option value=".TWO">台股上櫃</option>
    <option value="">美股</option>
  </select>
  <input id="f-ticker" placeholder="代號（如 2330 或 AAPL）">
  <input id="f-name" placeholder="名稱（可留白）">
  <input id="f-price" type="number" step="any" placeholder="買價">
  <input id="f-date" type="date">
  <button class="btn" onclick="regBuy()">登錄買進</button>
</div>
<div class="formrow">
  <input id="f-sell" placeholder="要移除的代號（如 2330.TW）">
  <button class="btn btn-red" onclick="regSell()">登錄賣出（移除監控）</button>
</div>
<p class="muted">送出後會開啟 GitHub 頁面（需登入你的帳號），按綠色「Create」即完成；
系統會自動寫入並回覆確認。也可以直接
<a href="https://github.com/20070117cheng/stock-breakout-signals/edit/main/holdings.csv" target="_blank" rel="noopener">手動編輯 holdings.csv</a>。</p>
</div>
<div class="help"><b style="color:{r}">立即賣出</b>＝觸發停損（跌破買價 8%，賣股公式4）或基本面惡化（單季獲利年增 &lt;20%），書中要求不猶豫、不攤平｜
<b style="color:#ea580c">賣出訊號</b>＝賣壓比例 SPR ≥ 117%（股價可能到中長期高點，可觀察後從容賣出，書 p.211），
或跌幅已達 7% 且跌破近 20 日最低價（書 p.228：此時即可提前停損）。<br>
買進股票後，到 GitHub 編輯 <code>holdings.csv</code> 加一行（格式：<code>tw,2330.TW,台積電,980,2026-07-01</code>），
賣出後刪掉該行。</div>
</section>

<section id="tab-paper" class="tab">
<h2>虛擬操盤（系統自動模擬，追蹤方法成效）</h2>
<div class="grid">
{_paper_card("台股虛擬帳戶", "元", (state.get("tw") or {}).get("paper"))}
{_paper_card("美股虛擬帳戶", "美元", (state.get("us") or {}).get("paper"))}
</div>
<div class="help"><b>模擬規則（書中框架＋固定公式）：</b>只買「強力候選」訊號，訊號隔日開盤價成交；
<b>部位 % ＝ 燈號基準（綠 10%／黃 5%／紅不買）×（檢核分數 ÷ 100）</b>——訊號越強壓越多、
行情越弱壓越少，每筆成交記錄都寫明計算；賣出依三條件，同樣隔日開盤成交；
台股計入手續費 0.1425% 與賣出證交稅 0.3%；
<b>追高保護</b>：開盤較訊號日收盤跳高逾 5% 就放棄該筆買單並記錄（系統選項，源自歐尼爾不追高原則）。<br>
<b>進出場理由完整可查</b>：每檔持倉下方「買入理由」可展開訊號日的完整檢核表；
賣出時成交記錄寫明觸發的是停損／基本面／賣壓比例哪一條。<br>
<b>誠實提醒：</b>虛擬操盤跳過了檢核表第⑦項（人工判斷未來獲利），等於「完全不做功課」的機械執行，
成效可視為此方法的保守下限；你實際操作時做了⑦的篩選，理論上應該比它好。
虛擬帳戶的錢和你的真實持股完全無關。</div>
</section>

<section id="tab-log" class="tab">
<h2>近期訊號記錄</h2>
{_log_section(log)}
<div class="help">保留近 300 筆訊號供複盤。練習方法：回頭看每個買進候選後來的走勢，驗證「訊號＋檢核表」的勝率，
這是書中說累積投資實力最快的方式（p.74：每天分析走勢圖是最有效的學習）。</div>
</section>

<section id="tab-learn" class="tab">
<h2>新手三分鐘看懂這套方法</h2>
<div class="help">
出處：林則行《大漲的訊號》（大是文化）。核心邏輯一句話：<b>「選擇股價創新高的股票，分析今後能否持續大幅成長」（p.17）</b>，
選股關鍵是「新高價」＋「成長」，配合絕不賠錢的賣出紀律。<br>
<b>1. 只買創新高的股票</b>：突破 2~3 年高價代表公司進入新時代，之前要有長而平穩的整理期（能量累積）。<br>
<b>2. 基本面要加速</b>：長期獲利年均 ≥7%、近年 ≥20%、近幾季營收 ≥10% 且獲利 ≥20%，本益比 &lt;60 倍。<br>
<b>3. 絕不賠大錢</b>：跌破買價 8% 無條件停損；單季獲利年增掉到 20% 以下就賣；賣壓比例出現訊號代表高點近了。<br>
<b>4. 看大盤臉色</b>：創新高股愈多行情愈強；紅燈時系統自然找不到訊號，空手就是策略。<br>
<b>5. 資金控管</b>：單檔不超過總資產 10%，行情弱就再減量。
</div>

<h2>標記說明</h2>
<div class="help">
<span class="tag tag-book">書中原文</span> 規則和數字直接出自書中，附頁數可對證。<br>
<span class="tag tag-sys">系統近似</span> 書中要求人工看圖或綜合判斷、沒給公式，系統為了自動化設計的替代演算法——用前請理解差異。<br>
<span class="tag tag-ai">AI 輔助</span> 由 Gemini 模型依書中標準給參考意見，推理過程與來源公開，最終判斷仍在你。
</div>

<h2>買進：九項檢核表（書附錄一 p.229-238）</h2>
<table>
<thead><tr><th>項目</th><th>書中規則（出處）</th><th>本系統的做法</th><th>性質</th></tr></thead>
<tbody>
<tr><td>① 創新高價</td>
    <td>突破近 2~3 年高價才算「創新高」，突破平穩期進入暴漲期（第二章第一、四節）；1 年 10 個月也可接受（p.73）</td>
    <td>收盤價 &gt; 前 490 個交易日（約 2 年）最高收盤價，每天全市場掃描</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>② 新高價位置</td>
    <td>反彈幅度＝(突破價−谷底)÷(前峰−谷底)，須達六成以上（買股公式2，p.70）；平穩期愈長、波動愈小愈好（p.66-67）；上次高點超過 10 年不考慮（p.73）</td>
    <td>反彈幅度自動計算（≥60%＝○、45~60%＝△、更低淘汰）；10 年規則自動排除；平穩期書中明言「無法用明確數字定義」（p.73），系統以 2 年價格變異係數換算 0~100% 品質分數輔助排序，仍建議自己看一眼月 K 線</td>
    <td><span class="tag tag-book">書中原文</span><br><span class="tag tag-sys">平穩期為系統近似</span></td></tr>
<tr><td>③ 長期獲利穩健</td>
    <td>過去 5~10 年經常利益年成長率 7% 以上且穩定（第三章第二節，p.104-109）</td>
    <td>稅前淨利年成長平均 ≥7% 且多數年份為正。台股用 FinMind 財報（最多 9 年）；美股資料源只有 4 年（已知限制）。「經常利益」是日本會計科目，系統以「稅前淨利」對應</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>④ 近 1~2 年獲利加速</td>
    <td>最近 1~2 年經常利益成長率 20% 以上（第三章第三節）</td>
    <td>近四季合計 vs 前四季合計 ≥20%（達 15% 給 △）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>⑤ 營收動能</td>
    <td>最近 2~3 季營收成長率 10% 以上（第三章第三節，p.110-122）</td>
    <td>近 3 季營收年增逐季檢查；台股輔以月營收（更即時）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>⑥ 獲利動能</td>
    <td>最近 2~3 季獲利成長率 20% 以上；未達原則上淘汰但保留彈性（p.122）</td>
    <td>近 3 季稅前淨利年增逐季檢查；不合格時結論降為「有硬傷」而非直接剔除（依 p.122 的彈性）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>⑦ 未來獲利判斷</td>
    <td>成長理由要能「一句話說清楚」；聽到「景氣發言」（成長只靠景氣好）就淘汰（第三章第五、六節，p.131-146）。書中方式是看公司說明會</td>
    <td>AI 讀取近期新聞＋營運數字＋業務簡介，依上述標準給 ○/△/×，推理過程與引用新聞連結完整顯示在評分卡黃色區塊；AI 失敗時退回「人工」。AI 看不到法說會影片，判斷深度有限，是參考不是決定</td>
    <td><span class="tag tag-ai">AI 輔助</span></td></tr>
<tr><td>⑧ 本益比</td>
    <td>排除本益比 60 倍以上的標的（第三章第七節，p.153）</td>
    <td>台股以近四季 EPS 計算、美股用資料源本益比；≥60 直接淘汰</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>⑨ 大盤上漲力道</td>
    <td>創新高價股數量比（近一年新高家數÷全市場）愈高漲勢愈強；書中明言「沒有必漲的基準點、套公式危險」，要求比對歷史走勢圖（p.91）；輔看前 50 大市值股是否創高（p.92-94）</td>
    <td>比率每日計算並畫成走勢線（等同書中圖表 2-25）；紅黃綠燈是系統把「比對歷史」自動化的近似（現值在近一年的相對位置＋與一個月前比的趨勢方向）</td>
    <td><span class="tag tag-book">比率為書中原文</span><br><span class="tag tag-sys">燈號為系統近似</span></td></tr>
</tbody>
</table>
<div class="help">評分卡的「檢核分數 /100」與結論分級（強力候選／候選／偏弱／淘汰）也是<span class="tag tag-sys">系統近似</span>——
書中做法是人工看 ○△× 做「綜合性判斷」（p.237，沒有一支股票會全部是○）。系統加權計分（書中標★的重要項目權重加倍）
是為了自動排序與寄信門檻，分數相近時請自己看各項目內容，不要只比分數。</div>

<h2>賣出：三種情況（第四章）</h2>
<table>
<thead><tr><th>條件</th><th>書中規則（出處）</th><th>本系統的做法</th><th>性質</th></tr></thead>
<tbody>
<tr><td>1. 停損</td>
    <td>「停損必須在股價從買價下跌 8% 左右時進行，務必嚴格遵守」（賣股公式4，p.227）；幅度可依人設 7~10%（p.228）；跌 7~10% 且跌破近Ｎ日最低價可提前賣（p.228）；攤平是最糟糕的規則（p.228）</td>
    <td>收盤跌破買價 8% → 立即賣出警報；跌幅達 7% 且跌破近 20 日最低收盤 → 提前警示。以每日收盤檢查（免費資料限制，非盤中即時）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>2. 基本面惡化</td>
    <td>單季獲利年增未達 20% 就賣，即使財測上修也一樣；爆發醜聞立即賣（p.192-193）。基本面賣訊通常太慢，僅供緊急應對（第四章第四節）</td>
    <td>每天檢查持股最新一季稅前淨利年增，&lt;20% 觸發警報；醜聞無法自動偵測，靠你看新聞（AI 判斷的新聞連結可輔助）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>3. 技術面（賣壓比例 SPR）</td>
    <td>作者自創指標：以每日開高低收把行進拆成買盤段與賣壓段，按幅度比例分配成交量，SPR＝20 個營業日賣出股數÷買進股數，達 116~118% 為賣出訊號（第四章第五節，p.201-215）；訊號出現未必要立刻賣，可觀察（p.211-213）</td>
    <td>照書中演算法完整實作（含書中數值範例的程式驗證），門檻 117%；觸發顯示「賣出訊號」（橘色，非紅色急賣）</td>
    <td><span class="tag tag-book">書中原文</span></td></tr>
</tbody>
</table>

<h2>資金管理與操作節奏</h2>
<table>
<thead><tr><th>規則</th><th>書中出處</th><th>本系統的做法</th><th>性質</th></tr></thead>
<tbody>
<tr><td>單檔上限 10%</td><td>模擬操作「每次都拿資產的 10% 當投資額」（p.28）</td>
    <td>Email 附建議金額（總資產 × 10%）</td><td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>依行情增減買量</td><td>「行情走強可增加單次股數量，走弱則減少」（p.95）</td>
    <td>綠燈全額、黃燈減半、紅燈不買</td><td><span class="tag tag-book">書中原文</span><span class="tag tag-sys">減半比例為系統設定</span></td></tr>
<tr><td>從最小單位開始</td><td>「就算口袋很深，也請從最小單位開始買起」（p.22）</td>
    <td>小額可用台股零股執行，規則完全相同</td><td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>訊號隔日開盤買進</td><td>訊號收盤確認、機械式操作（第一章模擬設定，p.28-29）</td>
    <td>收盤後掃描 → 通知 → 你隔日開盤下單；虛擬操盤用同一假設</td><td><span class="tag tag-book">書中原文</span></td></tr>
<tr><td>虛擬操盤部位公式</td><td>—（書中無此公式）</td>
    <td>部位％＝燈號基準（綠10%／黃5%／紅0）×（檢核分數÷100），把「行情強弱」與「訊號品質」都納入，每筆成交記錄寫明算式；含台股手續費與證交稅</td>
    <td><span class="tag tag-sys">系統近似</span></td></tr>
</tbody>
</table>

<h2>網頁本身用到的方法與技術</h2>
<div class="help">上面是「投資規則」，這裡說明「這個網頁怎麼運作、資料哪裡來、算法在做什麼」。
全部程式與計算公開在 <a href="https://github.com/20070117cheng/stock-breakout-signals" target="_blank" rel="noopener">GitHub</a>，可自行檢視。</div>
<table>
<thead><tr><th>功能</th><th>怎麼運作 / 用到的方法</th><th>資料來源</th></tr></thead>
<tbody>
<tr><td>每日自動掃描</td>
    <td>GitHub Actions 排程（雲端伺服器，與你的電腦無關）：台股每交易日 16:30、美股每交易日 06:00（台北時間）自動執行，收盤資料為準</td>
    <td>GitHub Actions（免費額度）</td></tr>
<tr><td>股價與掃描範圍</td>
    <td>批次下載全市場收盤價，快取成檔案增量更新（省流量）；台股上市＋上櫃約 2000 檔、美股 S&amp;P500＋NASDAQ100 約 500 檔</td>
    <td>Yahoo Finance（yfinance）、FinMind、Wikipedia 成分股表</td></tr>
<tr><td>大盤燈號走勢線</td>
    <td>每日算「創一年新高家數÷全市場家數」，取 10 日移動平均畫成走勢線（即書中圖表 2-25）；燈號＝此比率在近一年分布的位置＋與一個月前比的趨勢（<span class="tag tag-sys">系統近似</span>，非書中公式）</td>
    <td>由股價計算</td></tr>
<tr><td>賣壓比例 SPR</td>
    <td>用每日開高低收還原當日買賣路徑、按幅度分配成交量，滾動 20 日計算（書 p.201-215 演算法，已用書中數值範例做程式驗證）</td>
    <td>由持股 OHLCV 計算</td></tr>
<tr><td>AI 第⑦項判斷</td>
    <td>對較強候選（每日最多 8 檔）蒐集新聞與營運數字，交給 Gemini 模型依書中標準判斷，推理與來源顯示於評分卡；失敗自動退回人工，且模型有備援清單</td>
    <td>Google News＋Google Gemini API（免費額度）</td></tr>
<tr><td>Email 通知</td>
    <td>有買賣訊號時，用 Gmail 應用程式密碼透過 SMTP 寄信給你自己；無訊號不寄</td>
    <td>Gmail SMTP</td></tr>
<tr><td>虛擬操盤</td>
    <td>純機械模擬（不吃 AI 意見），訊號隔日開盤價成交、記錄每筆買賣與資產曲線，當作「方法本身」的成效基準線</td>
    <td>由股價與訊號計算</td></tr>
<tr><td>持股快速登錄</td>
    <td>網頁是靜態頁面無法直接寫資料，改用「表單產生 GitHub Issue → 雲端自動解析寫入 holdings.csv → 回覆並關閉」；僅接受你本人帳號的 Issue</td>
    <td>GitHub Issues + Actions</td></tr>
<tr><td>儀表板網頁</td>
    <td>每次掃描後由程式重新產生單一 HTML，推送到 GitHub Pages 免費空間；純靜態、無後端、無追蹤</td>
    <td>GitHub Pages</td></tr>
</tbody>
</table>
<div class="help">完整資料來源清單（含各項連結與更新頻率）在「大盤燈號」分頁最下方。
這一切都設計成不依賴任何付費訂閱（含 AI 訂閱），你之後不續訂也能繼續自動運作。</div>

<h2>每天的例行流程（2 分鐘）</h2>
<div class="help">
1. 看「大盤燈號」決定今天的心態（綠＝積極、黃＝保守、紅＝休息）。<br>
2. 有收到 Email 才需要動作：買進候選 → 看評分卡與 AI 依據、有餘力查法說會 → 決定要不要隔天開盤買；持股警報 → 依指示賣出。<br>
3. 買賣之後到「持股監控」用快速登錄表單更新。<br>
4. 週末有空去「訊號記錄」複盤，並比較「虛擬操盤」和自己的操作差在哪。
</div>
</section>
</main>
<footer>本頁由 GitHub Actions 自動產生，規則出自林則行《大漲的訊號》。僅供學習參考，不構成投資建議；投資人應自行承擔風險。</footer>
<script>
const REPO = 'https://github.com/20070117cheng/stock-breakout-signals';
function openIssue(title) {{
  const body = '由儀表板產生，按下方綠色 Create 按鈕即完成登錄。';
  window.open(REPO + '/issues/new?title=' + encodeURIComponent(title) +
              '&body=' + encodeURIComponent(body), '_blank');
}}
function regBuy() {{
  const suffix = document.getElementById('f-mkt').value;
  const ticker = document.getElementById('f-ticker').value.trim().toUpperCase();
  const name = document.getElementById('f-name').value.trim();
  const price = document.getElementById('f-price').value.trim();
  const date = document.getElementById('f-date').value || new Date().toISOString().slice(0, 10);
  if (!ticker || !price) {{ alert('請填代號和買價'); return; }}
  const full = ticker.includes('.') ? ticker : ticker + suffix;
  openIssue(['持股', '買', full, price, date, name].filter(Boolean).join(' '));
}}
function regSell() {{
  const ticker = document.getElementById('f-sell').value.trim().toUpperCase();
  if (!ticker) {{ alert('請填代號'); return; }}
  openIssue('持股 賣 ' + ticker);
}}
document.querySelectorAll('.tabs button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    window.scrollTo(0, 0);
  }});
}});
</script>
</body>
</html>"""
    HTML_PATH.parent.mkdir(exist_ok=True)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"[report] 已更新 {HTML_PATH}")
