# AI 第⑦項判斷測試 — 重點：輸出解析、評分整合、沒有 AI 時的降級保護
import json

from engine.ai_judge import parse_llm_json, build_prompt, parse_news_rss
from engine.scoring import build_scorecard


def _items_all_pass():
    return {k: ("O", "") for k in ("1", "2", "3", "4", "5", "6", "8", "9")}


def test_parse_llm_json_clean():
    raw = json.dumps({
        "grade": "O", "one_line": "超商展店與鮮食滲透率提升的結構性成長",
        "analysis": "近三季營收…", "risks": "展店成本上升",
        "sources_used": [1, 2],
    }, ensure_ascii=False)
    out = parse_llm_json(raw)
    assert out["grade"] == "O"
    assert "結構性" in out["one_line"]


def test_parse_llm_json_with_markdown_fence():
    raw = '```json\n{"grade": "X", "one_line": "僅受惠景氣循環", "analysis": "a", "risks": "r", "sources_used": []}\n```'
    out = parse_llm_json(raw)
    assert out["grade"] == "X"


def test_parse_llm_json_invalid_returns_none():
    assert parse_llm_json("我覺得這檔不錯") is None
    assert parse_llm_json('{"grade": "Z", "one_line": "?"}') is None  # 不合法等級


def test_build_prompt_contains_book_criteria_and_evidence():
    p = build_prompt(
        name="寶雅", market="tw",
        business="美妝生活雜貨零售通路", industry="零售",
        fundamentals_text="近3月營收年增 30%、20%、35%",
        news=[{"title": "寶雅展店加速", "source": "測試報", "date": "2026-07-01", "link": "http://x"}],
    )
    assert "一句話" in p          # 書中判斷標準
    assert "景氣" in p            # 景氣發言就淘汰（p.146）
    assert "寶雅展店加速" in p    # 證據要進 prompt
    assert "[1]" in p             # 來源編號供引用


def test_parse_news_rss():
    xml = """<?xml version="1.0"?><rss><channel>
      <item><title>某公司營收創高</title><link>http://a</link>
        <pubDate>Wed, 01 Jul 2026 08:00:00 GMT</pubDate><source url="http://s">測試日報</source></item>
      <item><title>產業趨勢向上</title><link>http://b</link>
        <pubDate>Tue, 30 Jun 2026 08:00:00 GMT</pubDate><source url="http://s">測試週刊</source></item>
    </channel></rss>"""
    items = parse_news_rss(xml, limit=5)
    assert len(items) == 2
    assert items[0]["title"] == "某公司營收創高"
    assert items[0]["source"] == "測試日報"


def test_scorecard_with_ai7_positive():
    ai7 = {"grade": "O", "one_line": "結構性成長", "analysis": "…", "risks": "…", "sources": []}
    sc = build_scorecard(_items_all_pass(), ai7=ai7)
    row7 = [r for r in sc["items"] if r["key"] == "7"][0]
    assert row7["grade"] == "O"
    assert "AI" in row7["detail"]
    assert sc["score"] == 100  # ⑦ 有評分後計入總分


def test_scorecard_with_ai7_negative_caps_verdict():
    # AI 判 × → 不得為強力候選（書：說不清楚成長理由就放棄）
    ai7 = {"grade": "X", "one_line": "僅靠景氣", "analysis": "…", "risks": "…", "sources": []}
    sc = build_scorecard(_items_all_pass(), ai7=ai7)
    assert "強力候選" not in sc["verdict"]


def test_scorecard_without_ai7_stays_manual():
    # 沒有 AI（未設金鑰/失敗）→ 維持人工判斷，系統不受影響
    sc = build_scorecard(_items_all_pass(), ai7=None)
    row7 = [r for r in sc["items"] if r["key"] == "7"][0]
    assert row7["grade"] == "M"
