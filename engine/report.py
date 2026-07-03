"""產生 GitHub Pages 儀表板（docs/index.html）——單檔、無外部依賴、新手友善。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "state.json"
LOG_PATH = ROOT / "data" / "signals_log.json"
HTML_PATH = ROOT / "docs" / "index.html"

LIGHT = {
    "green": ("🟢", "綠燈｜行情強", "#16a34a"),
    "yellow": ("🟡", "黃燈｜行情普通", "#ca8a04"),
    "red": ("🔴", "紅燈｜行情弱", "#dc2626"),
}
ACTION_LABEL = {
    "SELL_NOW": ("⛔ 立即賣出", "#dc2626"),
    "SELL_SIGNAL": ("⚠️ 賣出訊號", "#ea580c"),
    "HOLD": ("✅ 續抱", "#16a34a"),
}


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


def _sparkline(values: list[float], color: str = "#2563eb") -> str:
    vals = [v for v in values if v == v] if values else []
    if len(vals) < 2:
        return ""
    w, h = 240, 48
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
    emoji, label, color = LIGHT.get(m["gauge"]["light"], LIGHT["yellow"])
    ratio = m["gauge"].get("ratio_now")
    ratio_txt = f"{ratio:.2%}" if ratio is not None else "—"
    spark = _sparkline(m.get("ratio_history", []), color)
    top50 = m.get("top50_hits", [])
    return f"""<div class="card">
  <h3>{name} <span style="color:{color}">{emoji} {label}</span></h3>
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
        rows.append(
            f"<tr><td>{star}</td><td>{it['name']}</td>"
            f"<td class='sym'>{it['symbol']}</td><td class='muted'>{it['detail']}</td></tr>"
        )
    return (
        "<table class='check'><thead><tr><th></th><th>檢核項目</th><th>結果</th><th>說明</th></tr></thead>"
        "<tbody>" + "".join(rows) + "</tbody></table>"
    )


def _candidates_section(state: dict) -> str:
    cards = []
    for mkt_key, mkt_name in [("tw", "台股"), ("us", "美股")]:
        m = state.get(mkt_key) or {}
        for c in m.get("buy_candidates", []):
            sc = c["scorecard"]
            cards.append(f"""<details class="card cand">
  <summary><b>{mkt_name}｜{c['name']}（{c['ticker']}）</b>
    收盤 {c['close']:g}｜檢核 <b>{sc['score']}/100</b> — {sc['verdict']}</summary>
  {_scorecard_table(sc)}
  <p class="muted">反彈幅度 {c.get('rebound', 0):.0%}｜平穩期品質 {c.get('base_quality', 0):.0%}｜訊號日 {m.get('date', '')}</p>
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
.card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
.big {{ font-size: 17px; margin: 6px 0; }}
.muted {{ color: #64748b; font-size: 13px; }}
.empty {{ background: #fff; border-radius: 12px; padding: 20px; color: #64748b; }}
table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 12px; overflow: hidden; font-size: 14px; }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid #e2e8f0; text-align: left; vertical-align: top; }}
th {{ background: #f8fafc; font-size: 13px; color: #475569; }}
.check td.sym {{ font-size: 16px; text-align: center; }}
details.cand summary {{ cursor: pointer; font-size: 15px; line-height: 1.6; }}
.help {{ background: #eff6ff; border-radius: 12px; padding: 14px 16px; font-size: 14px; line-height: 1.8; }}
footer {{ text-align: center; color: #94a3b8; font-size: 12px; padding: 24px; }}
@media (max-width: 640px) {{ th, td {{ padding: 6px; font-size: 12px; }} }}
</style>
</head>
<body>
<header>
  <h1>📊 大漲訊號儀表板</h1>
  <p>依《大漲的訊號》創新高價投資法自動掃描台股（上市+上櫃）與美股（S&P 500 + NASDAQ 100）｜更新：{now}</p>
</header>
<main>
<h2>今天可以進場嗎？（大盤上漲力道）</h2>
<div class="grid">
{_market_card("台股", state.get("tw"))}
{_market_card("美股", state.get("us"))}
</div>
<div class="help">🟢 綠燈＝創新高股多、行情強，可依計畫買進（單檔上限＝總資產 10%）｜
🟡 黃燈＝力道普通，減量操作｜🔴 紅燈＝創新高股稀少，書中建議空手等待。
判斷依據：全市場「創一年新高家數比率」與前 50 大市值股動向（書第二章第六節）。</div>

<h2>📈 買進候選（今日突破 2 年新高＋基本面檢核）</h2>
{_candidates_section(state)}
<div class="help">每張評分卡對應書中附錄一的 9 項檢核表（★＝書中標示的重要項目）。
<b>👤 第⑦項一律需要你自己判斷</b>：去看該公司法說會或年報，問自己「它獲利成長的理由，能不能用一句話說清楚？」
說不清楚就放棄這檔（書 p.131-146）。買進時機：訊號日的隔天開盤（書中為機械式操作）。</div>

<h2>💼 持股監控（賣出三條件）</h2>
{_holdings_section(state)}
<div class="help">⛔ 立即賣出＝觸發停損（跌破買價 8%）或基本面惡化（單季獲利年增 &lt;20%），書中要求不猶豫、不攤平｜
⚠️ 賣出訊號＝賣壓比例 SPR ≥ 117%（股價可能到中長期高點），可觀察後從容賣出（書 p.211）。</div>

<h2>🗒️ 近期訊號記錄</h2>
{_log_section(log)}

<h2>📖 新手三分鐘看懂這套方法</h2>
<div class="help">
1️⃣ <b>只買創新高的股票</b>：突破 2~3 年高價代表公司進入新時代，之前要有長而平穩的整理期（能量累積）。<br>
2️⃣ <b>基本面要加速</b>：長期獲利年均 ≥7%、近年 ≥20%、近幾季營收 ≥10% 且獲利 ≥20%，本益比 &lt;60 倍。<br>
3️⃣ <b>絕不賠大錢</b>：跌破買價 8% 無條件停損；單季獲利年增掉到 20% 以下就賣；賣壓比例出現訊號代表高點近了。<br>
4️⃣ <b>看大盤臉色</b>：創新高股愈多行情愈強；紅燈時系統自然找不到訊號，空手就是策略。<br>
5️⃣ <b>資金控管</b>：單檔不超過總資產 10%，行情弱就再減量。
</div>
</main>
<footer>本頁由 GitHub Actions 自動產生，規則出自林則行《大漲的訊號》。僅供學習參考，不構成投資建議；投資人應自行承擔風險。</footer>
</body>
</html>"""
    HTML_PATH.parent.mkdir(exist_ok=True)
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"[report] 已更新 {HTML_PATH}")
