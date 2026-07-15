"""Gmail 通知：以應用程式密碼透過 SMTP 寄信給自己。

環境變數（GitHub Secrets）：GMAIL_ADDRESS、GMAIL_APP_PASSWORD。
"""
from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(subject: str, html_body: str) -> bool:
    addr = os.environ.get("GMAIL_ADDRESS")
    pwd = os.environ.get("GMAIL_APP_PASSWORD")
    if not addr or not pwd:
        print("[notify] 未設定 GMAIL_ADDRESS / GMAIL_APP_PASSWORD，跳過寄信")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = addr
    msg["To"] = addr
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(addr, pwd)
        server.sendmail(addr, [addr], msg.as_string())
    print(f"[notify] 已寄出：{subject}")
    return True


def format_signal_email(market_name: str, date_str: str, buy_candidates: list[dict],
                        sell_alerts: list[dict], market_gauge: dict,
                        dashboard_url: str, position_hint: str,
                        box_candidates: list[dict] | None = None,
                        combo_candidates: list[dict] | None = None) -> tuple[str, str]:
    """組出主旨與 HTML 內文。"""
    box_candidates = box_candidates or []
    combo_candidates = combo_candidates or []
    n_buy, n_sell = len(buy_candidates), len(sell_alerts)
    urgent = any(a["action"] == "SELL_NOW" for a in sell_alerts)
    subject = f"【大漲訊號】{date_str} {market_name}："
    parts = []
    if n_sell:
        parts.append(f"{n_sell} 檔持股警報" + ("（含緊急停損）" if urgent else ""))
    if combo_candidates:
        parts.append(f"{len(combo_candidates)} 檔綜合訊號")
    if n_buy:
        parts.append(f"{n_buy} 檔買進候選")
    if box_candidates:
        parts.append(f"{len(box_candidates)} 檔箱型訊號")
    subject += "、".join(parts) if parts else "無新訊號"

    light_emoji = {"green": "🟢", "yellow": "🟡", "red": "🔴"}.get(market_gauge.get("light"), "🟡")
    html = [
        f"<h2>{market_name}｜{date_str}</h2>",
        f"<p><b>大盤燈號 {light_emoji}</b>：{market_gauge.get('reason', '')}</p>",
    ]

    if combo_candidates:
        html.append("<h3>⭐ 綜合訊號（大漲＋箱型雙檢核通過，最強共振）</h3><ul>")
        for e in combo_candidates:
            score_txt = f"檢核 {e['score']}/100｜" if e.get("score") is not None else ""
            html.append(
                f"<li><b>{e['name']}（{e['ticker']}）</b> 收盤 {e['close']:g}｜{score_txt}"
                f"{e['kd_state']}，距3年高 {e['pct_of_high']}%</li>"
            )
        html.append("</ul><p>兩套策略同日給出訊號，技術面共振；仍請完成人工確認再決定。</p>")

    if sell_alerts:
        html.append("<h3>🚨 持股警報（依書中規則，出現訊號就要果斷行動）</h3><ul>")
        for a in sell_alerts:
            tag = "⛔ 立即賣出" if a["action"] == "SELL_NOW" else "⚠️ 賣出訊號（可觀察 1-2 日）"
            html.append(f"<li><b>{a['name']}（{a['ticker']}）</b> {tag}，損益 {a['pnl_pct']:+.1%}<br>")
            html.append("；".join(a["reasons"]) + "</li>")
        html.append("</ul>")

    if buy_candidates:
        html.append(f"<h3>📈 今日突破新高的買進候選</h3><p>{position_hint}</p><ul>")
        for c in buy_candidates:
            ai = c.get("ai7")
            ai_line = f"<br>AI 第⑦項（參考）：{ai['one_line']}" if ai else ""
            html.append(
                f"<li><b>{c['name']}（{c['ticker']}）</b> 收盤 {c['close']:g}，"
                f"檢核分數 {c['scorecard']['score']}/100 — {c['scorecard']['verdict']}{ai_line}</li>"
            )
        html.append("</ul>")
        html.append("<p>⚠️ 買進前請完成檢核表第⑦項人工確認（看法說會），細節見儀表板。</p>")

    if box_candidates:
        html.append("<h3>📦 箱型訊號（KD 金叉＋貼近 3 年高）</h3><ul>")
        for c in box_candidates:
            html.append(
                f"<li><b>{c['name']}（{c['ticker']}）</b> 現價 {c['close']:g}，"
                f"{c['kd_state']}，距 3 年收盤高 {c['pct_of_high']}%（K {c['k']}／D {c['d']}）</li>"
            )
        html.append("</ul><p>箱型策略出場規則：移動停利 10%／固定停損 3%。</p>")

    html.append(f'<p><a href="{dashboard_url}">👉 開啟完整儀表板</a></p>')
    html.append("<hr><p style='color:#888;font-size:12px'>本系統依《大漲的訊號》規則自動產生，僅供參考，不構成投資建議。投資有風險。</p>")
    return subject, "\n".join(html)
