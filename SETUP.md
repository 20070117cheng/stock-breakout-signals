# 🚀 新手設定教學（一次設定，之後全自動）

跟著做一遍約 30 分鐘。完成後系統每天自動跑，你的電腦關機也沒關係，
而且完全不需要任何 AI 訂閱。

---

## 第 1 步：註冊 GitHub（免費）

1. 打開 https://github.com/signup
2. 用你的 Gmail 註冊，設定密碼、驗證信箱
3. 記下你的「帳號名稱」（例如 `cheng123`），下面會用到

## 第 2 步：建立儲存庫（放程式的地方）

1. 登入後點右上角「＋」→「New repository」
2. Repository name 輸入：`stock-breakout-signals`
3. 選 **Public**（公開）
   - ⚠️ 為什麼要公開？免費版的 GitHub Pages（儀表板網頁）只支援公開儲存庫。
   - 這代表你的持股代號和買價，知道網址的人都看得到。介意的話：`holdings.csv` 不填真實買價、只填接近的整數，停損計算差異很小；或之後升級 GitHub Pro（月費 4 美元）改私人。
4. 按「Create repository」

## 第 3 步：上傳程式

在你電腦的這個資料夾（`stock-breakout-signals`）開啟終端機，執行：

```
git remote add origin https://github.com/<你的帳號>/stock-breakout-signals.git
git push -u origin main
```

（會要求登入 GitHub，依畫面指示操作。）

## 第 4 步：申請 Gmail 應用程式密碼（讓系統能寄信給你）

1. 打開 https://myaccount.google.com/security → 確認「兩步驟驗證」已開啟（沒開先開）
2. 打開 https://myaccount.google.com/apppasswords
3. 應用程式名稱輸入 `stock-signals`，按「建立」
4. 會出現 16 個字母的密碼（例如 `abcd efgh ijkl mnop`），**複製起來**（空格可留可不留）

## 第 5 步：把密碼放進 GitHub Secrets（安全保存，不會公開）

1. 到你的儲存庫頁面 → Settings → Secrets and variables → Actions
2. 按「New repository secret」，建立兩筆：

| Name | Secret（值） |
|------|------|
| `GMAIL_ADDRESS` | 你的 Gmail 地址 |
| `GMAIL_APP_PASSWORD` | 剛才的 16 字密碼 |

3. （選填但建議）到 https://finmindtrade.com 免費註冊拿 API token，
   再新增第三筆 secret：`FINMIND_TOKEN`＝你的 token。台股資料額度會更充裕。

## 第 6 步：開啟儀表板網頁（GitHub Pages）

1. 儲存庫 → Settings → Pages
2. Source 選「Deploy from a branch」，Branch 選 `main`、資料夾選 `/docs`，按 Save
3. 幾分鐘後你的儀表板網址就是：
   `https://<你的帳號>.github.io/stock-breakout-signals/`
4. 把這個網址填回 `config.yaml` 的 `dashboard_url`（直接在 GitHub 網頁上編輯該檔案即可）

## 第 7 步：手動跑第一次，確認一切正常

1. 儲存庫 → Actions 頁籤 → 若出現提示按「I understand my workflows, enable them」
2. 左邊點「台股每日掃描」→ 右邊「Run workflow」→ 綠色按鈕執行
3. 等 10~20 分鐘（第一次要下載 3 年歷史資料，之後每天只需幾分鐘）
4. 跑完後打開儀表板網址，應該就能看到大盤燈號和候選股了
5. 同樣方式跑一次「美股每日掃描」

之後系統就會自動在 **台北時間每天 16:30（台股）與 06:00（美股）** 執行。

---

## 📱 日常使用（每天 2 分鐘）

- **收 Email**：有買賣訊號才會寄信。標題含「立即賣出」的要優先處理。
- **看儀表板**：大盤燈號 → 買進候選評分卡 → 持股狀態。
- **買了股票之後**：到 GitHub 開 `holdings.csv` → 點鉛筆圖示編輯 → 加一行
  `tw,2330.TW,台積電,980,2026-07-01` → Commit changes。手機瀏覽器也能操作。
- **賣掉之後**：刪掉那一行。

## ❓ 常見問題

**Q：訊號來了就要無腦買嗎？**
不行。書中檢核表第⑦項（未來獲利能否穩健成長）要你自己判斷：去看該公司的
法說會影片或年報，「獲利成長的理由能用一句話說清楚」才買（書 p.131-146）。
系統會把該做的功課列在儀表板上。

**Q：多少錢買一檔？**
單檔不超過總資產 10%（先在 `config.yaml` 填你的 `total_capital`）。
大盤黃燈再減半，紅燈不買（書第二章第六節）。

**Q：為什麼有時候好幾天都沒訊號？**
正常。下跌行情本來就不會有創新高股，「空手等待」就是這套方法的一部分（書 p.87）。

**Q：系統會自動下單嗎？**
不會，也刻意不做。所有買賣由你自己在券商 App 執行，系統只負責訊號。

## ⚠️ 免責聲明

本系統把書中規則自動化，但書中也強調有兩處無法量化（平穩期認定、未來獲利判斷），
這些仍需你動手確認。歷史績效不代表未來；所有投資決定與風險由你自行承擔。
