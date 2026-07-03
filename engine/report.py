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
    trade_rows = "".join(
        f"<tr><td>{t['date']}</td><td>{'買進' if t['action'] == 'BUY' else '賣出'}</td>"
        f"<td><b>{t['name']}</b></td><td>{t['price']:g}</td>"
        f"<td>{('%+.1f%%' % (t['pnl_pct'] * 100)) if 'pnl_pct' in t else '—'}</td>"
        f"<td class='muted'>{t['reason']}</td></tr>"
        for t in reversed(p.get("trades", []))
    ) or "<tr><td colspan='6' class='muted'>尚無成交記錄</td></tr>"
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
  <h4>近期成交（賣出會顯示在這裡，含損益與原因）</h4>
  <table><thead><tr><th>日期</th><th>動作</th><th>股票</th><th>成交價</th><th>損益</th><th>原因</th></tr></thead>
  <tbody>{trade_rows}</tbody></table>
</div>"""


def _log_section(log: list[dict]) -> str:
    if not log:
        return "<p class='empty'>尚無訊號記錄。</p>"
    rows = [
        f"<tr><td>{e['date']}</td><td>{e['market']}</td><td>{e['type']}</td>"
        f"<td><b>{e['name']}（{e['ticker']}）</b></td><td class='muted'>{e['note']}</td></tr>"
        for e in reversed(log[-60:])
    ]
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
台股計入手續費 0.1425% 與賣出證交稅 0.3%。<br>
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
<b>1. 只買創新高的股票</b>：突破 2~3 年高價代表公司進入新時代，之前要有長而平穩的整理期（能量累積）。<br>
<b>2. 基本面要加速</b>：長期獲利年均 ≥7%、近年 ≥20%、近幾季營收 ≥10% 且獲利 ≥20%，本益比 &lt;60 倍。<br>
<b>3. 絕不賠大錢</b>：跌破買價 8% 無條件停損；單季獲利年增掉到 20% 以下就賣；賣壓比例出現訊號代表高點近了。<br>
<b>4. 看大盤臉色</b>：創新高股愈多行情愈強；紅燈時系統自然找不到訊號，空手就是策略。<br>
<b>5. 資金控管</b>：單檔不超過總資產 10%，行情弱就再減量。
</div>
<h2>每天的例行流程（2 分鐘）</h2>
<div class="help">
1. 看「大盤燈號」決定今天的心態（綠＝積極、黃＝保守、紅＝休息）。<br>
2. 有收到 Email 才需要動作：買進候選 → 做第⑦項功課 → 決定要不要隔天開盤買；持股警報 → 依指示賣出。<br>
3. 買賣之後記得更新 <code>holdings.csv</code>。<br>
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
