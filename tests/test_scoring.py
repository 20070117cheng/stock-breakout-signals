# 檢核表評分測試
from engine.scoring import build_scorecard


def _base_items(**overrides):
    items = {
        "1": ("O", ""), "2": ("O", ""), "3": ("O", ""), "4": ("O", ""),
        "5": ("O", ""), "6": ("O", ""), "8": ("O", ""), "9": ("O", ""),
    }
    items.update(overrides)
    return items


def test_all_pass_is_strong_candidate():
    sc = build_scorecard(_base_items())
    assert sc["verdict"].startswith("強力候選")
    assert sc["score"] == 100


def test_growth_x_caps_verdict():
    # ③④獲利成長 × → 不得評為強力候選（書第三章：原則上淘汰、保留彈性）
    sc = build_scorecard(_base_items(**{"3": ("X", ""), "4": ("X", "")}))
    assert "強力候選" not in sc["verdict"]
    assert "硬傷" in sc["verdict"] or sc["verdict"].startswith("偏弱")


def test_no_breakout_is_hard_fail():
    sc = build_scorecard(_base_items(**{"1": ("X", "")}))
    assert sc["verdict"].startswith("淘汰")


def test_pe_over_60_is_hard_fail():
    sc = build_scorecard(_base_items(**{"8": ("X", "")}))
    assert sc["verdict"].startswith("淘汰")


def test_item7_always_manual():
    sc = build_scorecard(_base_items())
    item7 = [r for r in sc["items"] if r["key"] == "7"][0]
    assert item7["grade"] == "M"
