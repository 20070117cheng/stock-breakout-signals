"""持股登錄指令：解析 GitHub Issue 標題，更新 holdings.csv。

指令格式（由儀表板表單自動產生，也可手動開 Issue）：
  持股 買 <代號> <買價> <日期YYYY-MM-DD> [名稱...]
  持股 賣 <代號>

市場由代號尾碼判斷：.TW / .TWO → 台股，其餘 → 美股。
由 .github/workflows/holdings.yml 觸發，僅接受儲存庫擁有者的 Issue。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "holdings.csv"
HEADER = "market,ticker,name,buy_price,buy_date"


def parse_command(title: str) -> dict:
    tokens = title.split()
    if len(tokens) < 3 or tokens[0] != "持股" or tokens[1] not in ("買", "賣"):
        raise ValueError(f"無法解析指令：{title!r}（格式：持股 買 代號 買價 日期 名稱 / 持股 賣 代號）")
    ticker = tokens[2].upper().replace(".two", ".TWO").replace(".tw", ".TW")

    if tokens[1] == "賣":
        return {"action": "sell", "ticker": ticker}

    if len(tokens) < 5:
        raise ValueError("買進指令需要：持股 買 代號 買價 日期 [名稱]")
    try:
        price = float(tokens[3])
    except ValueError:
        raise ValueError(f"買價必須是數字：{tokens[3]!r}")
    date = tokens[4]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError(f"日期格式須為 YYYY-MM-DD：{date!r}")
    name = " ".join(tokens[5:]) or ticker
    market = "tw" if ticker.endswith((".TW", ".TWO")) else "us"
    return {"action": "buy", "market": market, "ticker": ticker,
            "name": name, "buy_price": price, "buy_date": date}


def apply_command(cmd: dict, csv_path: Path = CSV_PATH) -> str:
    lines = csv_path.read_text(encoding="utf-8-sig").splitlines() if csv_path.exists() else [HEADER]
    if not lines or not lines[0].startswith("market"):
        lines.insert(0, HEADER)

    def is_data_row(line: str) -> bool:
        return bool(line.strip()) and not line.startswith("#") and not line.startswith("market")

    if cmd["action"] == "buy":
        # 同一代號覆蓋（重複登錄視為修正買價）
        lines = [l for l in lines if not (is_data_row(l) and l.split(",")[1].strip() == cmd["ticker"])]
        lines.append(f"{cmd['market']},{cmd['ticker']},{cmd['name']},{cmd['buy_price']},{cmd['buy_date']}")
        msg = (f"已登錄買進：{cmd['name']}（{cmd['ticker']}），買價 {cmd['buy_price']:g}，"
               f"日期 {cmd['buy_date']}。下一次排程起開始監控賣出三條件。")
    else:
        before = len(lines)
        lines = [l for l in lines if not (is_data_row(l) and l.split(",")[1].strip() == cmd["ticker"])]
        if len(lines) == before:
            raise ValueError(f"找不到持股 {cmd['ticker']}，目前未在監控清單中")
        msg = f"已移除持股：{cmd['ticker']}，停止監控。"

    csv_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return msg


def main() -> None:
    title = os.environ.get("ISSUE_TITLE", "").strip()
    try:
        msg = apply_command(parse_command(title))
        print(msg)
    except ValueError as e:
        print(f"登錄失敗：{e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
