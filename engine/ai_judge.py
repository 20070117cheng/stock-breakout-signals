"""AI 自動判斷檢核表第⑦項「未來獲利能否穩健成長」——Gemini 免費 API。

設計原則：
- 判斷標準完全依書 p.131-146：成長理由能否一句話說清楚？是結構性變化還是
  只靠景氣？（「景氣發言」就淘汰）
- 證據透明：AI 只能根據系統蒐集並展示給使用者的證據（新聞、營收趨勢、業務簡介）
  做判斷，且必須標注引用了哪幾則來源。
- 降級保護：未設 GEMINI_API_KEY 或呼叫失敗 → 回傳 None，⑦ 退回人工判斷，
  核心系統照常運作。
"""
from __future__ import annotations

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl={hl}&gl={gl}&ceid={ceid}"


# ---------- 證據蒐集 ----------

def fetch_news(name: str, market: str, limit: int = 8) -> list[dict]:
    """Google News RSS（免費、無需金鑰）。"""
    if market == "tw":
        query = requests.utils.quote(f'"{name}" 營收 OR 獲利 OR 展望 OR 法說')
        url = NEWS_RSS.format(query=query, hl="zh-TW", gl="TW", ceid="TW:zh-Hant")
    else:
        query = requests.utils.quote(f'"{name}" earnings OR outlook OR growth')
        url = NEWS_RSS.format(query=query, hl="en-US", gl="US", ceid="US:en")
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return parse_news_rss(r.text, limit)
    except Exception:
        return []


def parse_news_rss(xml_text: str, limit: int = 8) -> list[dict]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items = []
    for item in root.iter("item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        date = (item.findtext("pubDate") or "")[:16]
        src = item.find("source")
        source = src.text if src is not None and src.text else ""
        if title:
            items.append({"title": title, "link": link, "date": date, "source": source})
        if len(items) >= limit:
            break
    return items


# ---------- Prompt 與解析 ----------

def build_prompt(name: str, market: str, business: str, industry: str,
                 fundamentals_text: str, news: list[dict]) -> str:
    news_block = "\n".join(
        f"[{i + 1}] {n['title']}（{n['source']}，{n['date']}）" for i, n in enumerate(news)
    ) or "（查無近期新聞）"
    return f"""你是一位保守的證券分析師。請依《大漲的訊號》檢核表第⑦項的標準，判斷下列公司「未來獲利能否穩健成長」。

判斷標準（務必遵守）：
1. 成長理由必須能用「一句話」說清楚，說不清楚就是不合格。
2. 成長必須來自結構性變化（產業趨勢、商業模式、市占提升等）；如果成長理由只是「景氣好」「循環回升」這類景氣發言，直接判 X（原書 p.146：聽到景氣發言就淘汰）。
3. 只能根據下面提供的證據判斷，禁止使用證據以外的記憶或推測；證據不足時判 T 並說明不足之處。

公司：{name}（市場：{'台股' if market == 'tw' else '美股'}）
產業：{industry}
業務簡介：{business}
近期營運數字：{fundamentals_text}

近期新聞標題：
{news_block}

請只輸出 JSON（不要其他文字），格式：
{{"grade": "O 或 T 或 X",
 "one_line": "一句話成長理由（或不合格的理由）",
 "analysis": "3~5 句推理過程，說明你如何從證據得出結論",
 "risks": "1~2 個主要風險",
 "sources_used": [引用的新聞編號，例如 1, 3]}}"""


def parse_llm_json(text: str) -> dict | None:
    """解析模型輸出；容忍 markdown 圍欄；等級不合法回 None。"""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        out = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if out.get("grade") not in ("O", "T", "X") or not out.get("one_line"):
        return None
    return out


# ---------- 主流程 ----------

def judge_candidate(market: str, ticker: str, name: str,
                    fundamentals_text: str, cfg: dict) -> dict | None:
    """回傳 {grade, one_line, analysis, risks, sources, model, judged_at} 或 None（降級）。"""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or not cfg.get("ai_judge_enabled", True):
        return None

    business, industry = "", ""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        business = (info.get("longBusinessSummary") or "")[:600]
        industry = info.get("industry") or info.get("sector") or ""
    except Exception:
        pass

    news = fetch_news(name, market)
    prompt = build_prompt(name, market, business, industry, fundamentals_text, news)
    model = cfg.get("gemini_model", "gemini-2.0-flash")

    for attempt in range(2):
        try:
            r = requests.post(
                GEMINI_URL.format(model=model),
                params={"key": api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"temperature": 0.2, "response_mime_type": "application/json"},
                },
                timeout=60,
            )
            if r.status_code == 429:
                time.sleep(20)
                continue
            r.raise_for_status()
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            out = parse_llm_json(text)
            if out is None:
                return None
            used = out.get("sources_used") or []
            sources = [news[i - 1] for i in used if isinstance(i, int) and 1 <= i <= len(news)]
            return {
                "grade": out["grade"],
                "one_line": out["one_line"],
                "analysis": out.get("analysis", ""),
                "risks": out.get("risks", ""),
                "sources": sources,
                "all_news": news,
                "model": model,
                "judged_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
        except Exception as e:
            print(f"[ai_judge] {ticker} 第 {attempt + 1} 次呼叫失敗：{e}")
            time.sleep(5)
    return None
