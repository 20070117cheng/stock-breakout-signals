# 持股登錄指令解析測試（Issue 標題 → holdings.csv）
import pytest

from engine.holdings_cmd import parse_command, apply_command

CSV_HEADER = "market,ticker,name,buy_price,buy_date\n"


def test_parse_buy_tw():
    cmd = parse_command("持股 買 2330.TW 980 2026-07-06 台積電")
    assert cmd == {"action": "buy", "market": "tw", "ticker": "2330.TW",
                   "name": "台積電", "buy_price": 980.0, "buy_date": "2026-07-06"}


def test_parse_buy_us_name_with_spaces():
    cmd = parse_command("持股 買 VRTX 405.5 2026-07-06 Vertex Pharmaceuticals")
    assert cmd["market"] == "us"
    assert cmd["name"] == "Vertex Pharmaceuticals"


def test_parse_buy_otc_and_default_name():
    cmd = parse_command("持股 買 5904.TWO 720 2026-07-06")
    assert cmd["market"] == "tw"
    assert cmd["name"] == "5904.TWO"  # 未填名稱時用代號


def test_parse_sell():
    cmd = parse_command("持股 賣 2330.TW")
    assert cmd == {"action": "sell", "ticker": "2330.TW"}


def test_parse_invalid():
    with pytest.raises(ValueError):
        parse_command("持股 買 2330.TW abc 2026-07-06")  # 價格不是數字
    with pytest.raises(ValueError):
        parse_command("你好")


def test_apply_buy_then_sell(tmp_path):
    csv = tmp_path / "holdings.csv"
    csv.write_text(CSV_HEADER + "# 註解行\n", encoding="utf-8")
    msg = apply_command(parse_command("持股 買 2330.TW 980 2026-07-06 台積電"), csv)
    assert "台積電" in msg
    content = csv.read_text(encoding="utf-8")
    assert "tw,2330.TW,台積電,980.0,2026-07-06" in content
    assert "# 註解行" in content  # 註解保留

    msg = apply_command(parse_command("持股 賣 2330.TW"), csv)
    assert "已移除" in msg
    assert "2330.TW" not in csv.read_text(encoding="utf-8")


def test_apply_buy_duplicate_updates(tmp_path):
    csv = tmp_path / "holdings.csv"
    csv.write_text(CSV_HEADER, encoding="utf-8")
    apply_command(parse_command("持股 買 2330.TW 980 2026-07-06 台積電"), csv)
    apply_command(parse_command("持股 買 2330.TW 1000 2026-07-08 台積電"), csv)
    content = csv.read_text(encoding="utf-8")
    assert content.count("2330.TW") == 1  # 同一檔覆蓋而非重複
    assert "1000.0" in content


def test_apply_sell_not_found(tmp_path):
    csv = tmp_path / "holdings.csv"
    csv.write_text(CSV_HEADER, encoding="utf-8")
    with pytest.raises(ValueError):
        apply_command(parse_command("持股 賣 9999.TW"), csv)
