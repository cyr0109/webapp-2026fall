# HouseMate（室友共居管家）

合租室友的共同支出，先記下來，之後再挑幾筆一起算清。紀錄永久保留。

## 怎麼跑

**資料庫**（PostgreSQL，需要 Docker）：

```bash
docker compose up -d
```

開兩個終端機。

**後端**（第一次要先建虛擬環境）：

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8001
```

> **Windows**：本文件的 `.venv/bin/...` 指令在 Windows 不能用，因為 Windows 的虛擬環境放在 `.venv\Scripts\`。
> 把 `python3.12` 換成 `py -3.12`，`.venv/bin/xxx` 換成 `.venv\Scripts\xxx`，例如：
>
> ```powershell
> py -3.12 -m venv .venv
> .venv\Scripts\pip install -r requirements.txt
> .venv\Scripts\uvicorn main:app --reload --port 8001
> .venv\Scripts\python seed.py
> .venv\Scripts\python test_api.py
> ```

API 文件在 http://127.0.0.1:8001/docs

> 用 `127.0.0.1` 不要用 `localhost`：macOS 的 `localhost` 會先解析成 IPv6，
> 而 uvicorn 只聽 IPv4。前端不受影響，它走 Vite 的 proxy。

**前端**：

```bash
cd frontend
npm install
npm run dev
```

網站在 http://localhost:5173

若另開一組本機後端做測試，可用 `HOUSEMATE_API_TARGET` 指定 Vite 的 API 代理目標。

## 示範資料

```bash
cd backend
.venv/bin/python seed.py   # 會清空資料庫後重建
```

建立群組「民生東路 3F」與三個帳號 `amy` / `ben` / `cindy`，密碼都是 `demo1234`。
含 5 筆項目，其中 2 筆已結算。

## 怎麼測

```bash
cd backend
.venv/bin/python split.py      # 分帳與欠款計算
.venv/bin/python test_api.py   # 註冊 → 記帳 → 欠款 → 結算 → 取消結算 → 確認收款（用 housemate_test 資料庫）
```

## 檔案

| 檔案                             | 做什麼                                     |
| -------------------------------- | ------------------------------------------ |
| `backend/split.py`             | 平分、餘數規則、誰欠誰多少。核心邏輯都在這 |
| `backend/models.py`            | 資料表                                     |
| `backend/auth.py`              | 密碼雜湊 (bcrypt) 與 JWT                   |
| `backend/main.py`              | API 路由                                   |
| `backend/household.py`         | 空檔、垃圾車時間、家務 API                   |
| `backend/notifications.py`     | 站內通知、繳款提醒、標記已讀                 |
| `frontend/src/api.js`          | 呼叫後端的包裝                             |
| `frontend/src/GroupLayout.jsx` | 三個畫面共用的外框，資料在這裡載一次       |
| `frontend/src/Ledger.jsx`      | 帳本：結餘 + 未結項目                      |
| `frontend/src/History.jsx`     | 結算紀錄（含每次涵蓋的項目）               |
| `frontend/src/Members.jsx`     | 成員管理、產生邀請連結                     |
| `frontend/src/Join.jsx`        | 開啟邀請連結後加入群組                     |

## 畫面

| 網址               | 內容                                         |
| ------------------ | -------------------------------------------- |
| `/`              | 群組列表                                     |
| `/g/:id`         | 帳本：結餘、未結項目、結算                   |
| `/g/:id/history` | 結算紀錄：誰付誰多少、涵蓋哪些項目、復原     |
| `/g/:id/members` | 成員：停用／啟用、移出群組、產生邀請連結     |
| `/g/:id/household` | 登記空檔、查看垃圾車時段及可到場成員、指派及完成家務 |
| `/g/:id/notifications` | 查看站內通知及標記已讀 |
| `/join/:token`   | 開啟邀請連結，登入後自動加入群組（7 天有效） |

結算完成後會自動跳到結算紀錄，才看得到該轉多少錢給誰。

## 規則備忘

- 金額一律**整數（台幣元）**。平分除不盡時，餘數由**付款人**吸收；付款人不在分攤名單內則給名單第一人。
- 支出 `settlement_id` 有值 = **已結**，鎖定不可改不可刪。要改先取消該次結算。
- 停用成員：不能再被選入新支出，但既有未結欠款照算。
- 只有結算發起人或管理員可復原結算，已有任何一筆確認收款時不可復原。
- 管理員（開群組的人）可移出成員及維護垃圾車時間。
- 空檔、垃圾車及家務以台北時間顯示。垃圾車抵達時間落在空檔的起點或區間內才會配對，結束時間不算。
- 支出可選填繳款期限。開啟群組時會檢查個人的未結支出，於到期前一天起產生站內提醒，同筆支出與期限只提醒一次。

## 現有 PostgreSQL 資料庫升級

後端啟動時會建立新資料表、補上期限欄位及提醒去重索引，保留現有資料。若要先獨立執行，可在 `backend` 跑 `.venv/bin/python models.py`。若環境有設定 `DATABASE_URL`，升級會套用到該連線的資料庫。

正式部署及 LINE／Email 提醒留在 M4。
