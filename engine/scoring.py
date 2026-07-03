"""買股公式檢核表評分卡 —《大漲的訊號》附錄一（p.229-238）。

仿照書中王將食品範例：每項打 ○（O）/△（T）/×（X）/無資料（N），
重要項目（書中標 * 者：①②⑥⑦⑨）加權，⑦ 為人工判斷項。
"""
from __future__ import annotations

GRADE_SYMBOL = {"O": "○", "T": "△", "X": "×", "N": "—"}

# 書中標星號的重要項目
STARRED = {"1", "2", "6", "7", "9"}

ITEM_NAMES = {
    "1": "① 股價突破近年來高價",
    "2": "② 新高價位置（反彈幅度≥60%）",
    "3": "③ 過去獲利穩健成長（年均≥7%）",
    "4": "④ 最近1~2年獲利成長≥20%",
    "5": "⑤ 最近2~3季營收成長≥10%",
    "6": "⑥ 最近2~3季獲利成長≥20%",
    "7": "⑦ 未來獲利能否穩健成長",
    "8": "⑧ 本益比未過熱（<60倍）",
    "9": "⑨ 大盤上漲力道",
}


def build_scorecard(items: dict[str, tuple[str, str]], ai7: dict | None = None) -> dict:
    """items: {"1": ("O", "細節"), ...}。

    ⑦ 預設為人工確認；提供 ai7（AI 判斷結果）時以其等級計分，
    並在列上保留完整推理供使用者複核。
    回傳 {items: [...], score: 加權分, verdict: 文字結論}
    """
    rows = []
    score = 0.0
    max_score = 0.0
    hard_fail = False
    for key in "123456789":
        grade, detail = items.get(key, ("N", "無資料"))
        row_extra = {}
        if key == "7":
            if ai7:
                grade = ai7["grade"]
                detail = f"AI 判斷（僅供參考，請複核依據）：{ai7['one_line']}"
                row_extra = {"ai": ai7}
            else:
                grade, detail = "M", "需人工確認：看公司法說會/財報說明，判斷成長理由能否用一句話說清楚（書 p.131-146）"
        rows.append(
            {
                "key": key,
                "name": ITEM_NAMES[key],
                "grade": grade,
                "symbol": "人工" if grade == "M" else GRADE_SYMBOL.get(grade, "—"),
                "detail": detail,
                "starred": key in STARRED,
                **row_extra,
            }
        )
        if grade == "M":
            continue
        w = 2.0 if key in STARRED else 1.0
        max_score += w
        if grade == "O":
            score += w
        elif grade == "T":
            score += w * 0.5
        elif grade == "X" and key in {"1", "8"}:
            hard_fail = True  # 沒突破新高或 PE≥60 直接淘汰

    # 書中基本面三步驟（第三章）：長期成長、近期成長、季獲利不合格者原則上淘汰，
    # 但保留彈性（p.122），故降級而非剔除
    growth_fail = any(items.get(k, ("N", ""))[0] == "X" for k in ("3", "4", "6"))
    ai_doubt = ai7 is not None and ai7["grade"] == "X"  # 書：成長理由說不清楚就放棄

    pct = score / max_score if max_score else 0.0
    if hard_fail:
        verdict = "淘汰：關鍵項目不合格"
    elif ai_doubt:
        verdict = "候選（AI 對未來成長持疑）：AI 判斷成長理由不成立或僅靠景氣，請自行複核其依據後再決定"
    elif growth_fail and pct >= 0.55:
        verdict = "候選（有硬傷）：獲利成長檢核有 × 項目，書中原則上應淘汰（p.122），除非其他表現足以彌補"
    elif growth_fail:
        verdict = "偏弱：獲利成長檢核不合格，觀望為宜"
    elif pct >= 0.75:
        verdict = (
            "強力候選：多數項目合格（⑦ 為 AI 參考意見，請複核其依據）後依⑨燈號決定買進量"
            if ai7 else
            "強力候選：多數項目合格，請完成⑦人工確認後依⑨燈號決定買進量"
        )
    elif pct >= 0.55:
        verdict = "候選：部分項目待觀察，書中提醒需綜合判斷（p.237）"
    else:
        verdict = "偏弱：合格項目不足，觀望為宜"
    return {"items": rows, "score": round(pct * 100), "verdict": verdict}
