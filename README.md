# HouseMate（室友共居管家）

合租室友的共同支出，先記下來，之後再挑幾筆一起算清。紀錄永久保留。

## 選一種啟動方式

| 方式 | 執行環境 | 網站 |
| --- | --- | --- |
| **A．Docker Compose 一鍵啟動** | 前端、後端、資料庫都由 Docker 啟動。可選展示模式或自動重載的開發模式。 | [127.0.0.1:8080](http://127.0.0.1:8080) |
| **B．本機開發** | Docker 只啟動資料庫，FastAPI 與 Vite 由本機終端機啟動。適合修改程式並即時預覽。 | [localhost:5173](http://localhost:5173) |

以下兩套步驟擇一執行。

### A．Docker Compose 一鍵啟動

#### A1．展示模式

準備 Docker 與 Docker Compose，在專案根目錄執行這一條指令：

```bash
docker compose up --build --wait
```

指令完成後，直接開啟 [HouseMate](http://127.0.0.1:8080)。Compose 已啟動三個服務並等待它們就緒。
API 文件在 [127.0.0.1:8080/api/docs](http://127.0.0.1:8080/api/docs)。
前端由 Nginx 提供，`/api/` 會轉送到 FastAPI，包含站內通知的 SSE 串流。

尚無帳號的資料庫會自動載入下方的示範資料。有帳號時會跳過，既有資料仍保存在
`pgdata` 資料卷。啟動時若不想載入示範資料，可在專案根目錄的 `.env` 設定
`HOUSEMATE_SEED_DEMO=0`。可用 `HOUSEMATE_WEB_PORT` 或 `HOUSEMATE_DB_PORT` 更改主機埠，
預設分別為 8080 和 5432。

```bash
docker compose ps
docker compose down
```

`docker compose ps` 查看服務狀態，`docker compose down` 停止服務並保留資料卷。

#### A2．Docker 開發模式

在專案根目錄執行以下指令，啟動開發容器與 [Compose Watch](https://docs.docker.com/compose/how-tos/file-watch/)：

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build --watch
```

開啟 [HouseMate](http://127.0.0.1:8080)。將終端機保持開啟，存檔後容器會同步程式碼。
修改前端時 Vite 會更新瀏覽器，修改 Python 時 Uvicorn 會重載 API。修改套件清單或
Dockerfile 時會重新建置對應的容器。

A1 與 A2 使用同一個網址和 PostgreSQL 資料卷。按 `Ctrl+C` 結束開發模式，
要切回展示時再執行 A1 的指令。

### B．本機開發

準備 Docker Compose、Python 3.12 與 Node.js 22。以下三步都要執行。
若已用方式 A 啟動，要切換到本機開發時，可先在專案根目錄執行
`docker compose stop frontend backend`，留下資料庫容器。

**1．資料庫。** 在專案根目錄只啟動 PostgreSQL：

```bash
docker compose up --wait db
```

**2．後端。** 開第一個終端機，從專案根目錄進入 `backend`。第一次先建立虛擬環境並安裝依賴：

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn main:app --reload --port 8001 --timeout-graceful-shutdown 5
```

> **Windows PowerShell** 使用下列指令啟動後端：
>
> ```powershell
> cd backend
> py -3.12 -m venv .venv
> .venv\Scripts\pip install -r requirements.txt
> .venv\Scripts\uvicorn main:app --reload --port 8001 --timeout-graceful-shutdown 5
> ```

API 文件在 http://127.0.0.1:8001/docs

> 用 `127.0.0.1` 不要用 `localhost`：macOS 的 `localhost` 會先解析成 IPv6，
> 而 uvicorn 只聽 IPv4。前端不受影響，它走 Vite 的 proxy。

**3．前端。** 開第二個終端機，從專案根目錄進入 `frontend`：

```bash
cd frontend
npm ci
npm run dev
```

啟動後開啟 [HouseMate](http://localhost:5173)。

若另開一組本機後端做測試，可用 `HOUSEMATE_API_TARGET` 指定 Vite 的 API 代理目標。

## 示範資料

- **方式 A** 預設在首次啟動時載入。若要手動匯入，從專案根目錄執行
  `docker compose exec backend python seed.py --if-empty`。
- **方式 B** 可在資料庫啟動後，於 `backend` 目錄執行 `.venv/bin/python seed.py --if-empty`。
  Windows PowerShell 改用 `.venv\Scripts\python seed.py --if-empty`。

上述指令會在資料庫已有帳號時跳過。移除 `--if-empty` 會清空並重建應用程式的資料表。

建立群組「民生東路 3F」與三個帳號 `amy` / `ben` / `cindy`，密碼都是 `demo1234`。
含 5 筆支出，其中 2 筆已結算。「電費 7-8 月」的繳款期限為執行腳本的隔天（台北時間），
通知頁已有記帳、結算或到期提醒。

在「共居」分頁，隔天 18:30 的垃圾車時間會配對到 ben。ben 完成「倒垃圾」後，
下一週的同一時段會指派給 cindy。同頁也能看到 cindy 已完成的「打掃公共區域」。

## 怎麼測

以下是選用的本機測試指令，需先依方式 B 準備資料庫和 Python 環境。

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
| `backend/household.py`         | 空檔、垃圾車時間、家務 API                 |
| `backend/notifications.py`     | 站內通知、繳款提醒、標記已讀               |
| `frontend/src/api.js`          | 呼叫後端的包裝                             |
| `frontend/src/GroupLayout.jsx` | 三個畫面共用的外框，資料在這裡載一次       |
| `frontend/src/Ledger.jsx`      | 帳本：結餘 + 未結項目                      |
| `frontend/src/History.jsx`     | 結算紀錄（含每次涵蓋的項目）               |
| `frontend/src/Members.jsx`     | 成員管理、產生邀請連結                     |
| `frontend/src/Join.jsx`        | 開啟邀請連結後加入群組                     |

## 畫面

| 網址                     | 內容                                                 |
| ------------------------ | ---------------------------------------------------- |
| `/`                    | 群組列表                                             |
| `/g/:id`               | 帳本：結餘、未結項目、結算                           |
| `/g/:id/history`       | 結算紀錄：誰付誰多少、涵蓋哪些項目、復原             |
| `/g/:id/members`       | 成員：停用／啟用、移出群組、產生邀請連結             |
| `/g/:id/household`     | 登記空檔、查看垃圾車時段及可到場成員、指派及完成家務 |
| `/g/:id/notifications` | 查看站內通知及標記已讀                               |
| `/join/:token`         | 開啟邀請連結，登入後自動加入群組（7 天有效）         |

結算完成後會自動跳到結算紀錄，才看得到該轉多少錢給誰。

## 規則備忘

- 金額一律**整數（台幣元）**。平分除不盡時，餘數由**付款人**吸收；付款人不在分攤名單內則給名單第一人。
- 支出 `settlement_id` 有值 = **已結**，鎖定不可改不可刪。要改先取消該次結算。
- 停用成員：不能再被選入新支出，但既有未結欠款照算。
- 只有結算發起人或管理員可復原結算，已有任何一筆確認收款時不可復原。
- 管理員（開群組的人）可移出成員及維護垃圾車時間。
- 空檔、垃圾車及家務以台北時間顯示。垃圾車抵達時間落在空檔的起點或區間內才會配對，結束時間不算。
- 家務可設定至少兩人的每週輪值。完成當次後，系統會依序建立下一次家務，略過停用成員與已錯過的週次。可從待完成的家務調整輪值或關閉輪值。
- 支出可選填繳款期限。開啟群組時，系統從到期前一天起提醒應付款的人。未結支出依個人分攤額提醒，不含墊付人自己的份額。
- 結算後改提醒尚未確認收款的轉帳。轉帳取該付款人欠該收款人的相關支出中最早的期限，提醒金額以相抵後的轉帳額為準。每筆轉帳只提醒一次，確認收款後保留舊通知。
- 群組頁開啟時會透過 SSE 更新通知列表、未讀數、帳本與結算紀錄，收到新通知會顯示提示。頁面以台北日期跨日時也會重新檢查到期提醒。

## 現有 PostgreSQL 資料庫升級

後端啟動時會建立新資料表、補上期限欄位及提醒去重索引，並為既有轉帳補算可推得的期限。若要先獨立執行，可在 `backend` 跑 `.venv/bin/python models.py`。若環境有設定 `DATABASE_URL`，升級會套用到該連線的資料庫。

正式部署及 LINE／Email 提醒留在 M4。
