# 租屋分帳

合租室友的共同支出，先記下來，之後再挑幾筆一起算清。紀錄永久保留。

## 怎麼跑

開兩個終端機。

**後端**（第一次要先建虛擬環境）：

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8001
```

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

## 示範資料

```bash
cd backend
.venv/bin/python seed.py   # 會清空 app.db 後重建
```

建立群組「民生東路 3F」與三個帳號 `amy` / `ben` / `cindy`，密碼都是 `demo1234`。
含 5 筆項目，其中 2 筆已結算。

## 怎麼測

```bash
cd backend
.venv/bin/python split.py      # 分帳與欠款計算
.venv/bin/python test_api.py   # 註冊 → 記帳 → 欠款 → 結算 → 取消結算
```

## 檔案

| 檔案 | 做什麼 |
|---|---|
| `backend/split.py` | 平分、餘數規則、誰欠誰多少。核心邏輯都在這 |
| `backend/models.py` | 資料表 |
| `backend/auth.py` | 密碼雜湊 (bcrypt) 與 JWT |
| `backend/main.py` | API 路由 |
| `frontend/src/api.js` | 呼叫後端的包裝 |
| `frontend/src/GroupLayout.jsx` | 三個畫面共用的外框，資料在這裡載一次 |
| `frontend/src/Ledger.jsx` | 帳本：結餘 + 未結項目 |
| `frontend/src/History.jsx` | 結算紀錄（含每次涵蓋的項目） |
| `frontend/src/Members.jsx` | 成員管理 |

## 畫面

| 網址 | 內容 |
|---|---|
| `/` | 群組列表 |
| `/g/:id` | 帳本：結餘、未結項目、結算 |
| `/g/:id/history` | 結算紀錄：誰付誰多少、涵蓋哪些項目、復原 |
| `/g/:id/members` | 成員：停用／啟用、移出群組 |

結算完成後會自動跳到結算紀錄，才看得到該轉多少錢給誰。

## 規則備忘

- 金額一律**整數（台幣元）**。平分除不盡時，餘數由**付款人**吸收；付款人不在分攤名單內則給名單第一人。
- 支出 `settlement_id` 有值 = **已結**，鎖定不可改不可刪。要改先取消該次結算。
- 停用成員：不能再被選入新支出，但既有未結欠款照算。
- 管理員（開群組的人）多兩個權限：刪群組、把成員移出群組。

## 還沒做

- 邀請連結（資料表已備好，`invites`）：目前只能靠直接寫 DB 把人加進群組
- 站內通知（資料表已備好，`notifications`）
- 前端 UI 沒有實際點過，只確認過能編譯、能啟動
