# 安裝說明

## 需求

- 使用 systemd 的 Linux（Ubuntu 22.04 以上已測試）
- Python 3.8 以上：`python3 --version`
- Minecraft Java 伺服器（Forge、NeoForge、Fabric 或原版），直接在主機上執行（非 Docker）
- 伺服器所在的 Discord 頻道要有建立 webhook 的權限

## 1. 開啟伺服器的 RCON

編輯伺服器目錄下的 `server.properties`，改完後重啟伺服器：

```properties
enable-rcon=true
rcon.port=25575
rcon.password=一組長的隨機密碼
broadcast-rcon-to-ops=false
```

- `rcon.password` 可以用 `openssl rand -base64 24` 產生。
- `broadcast-rcon-to-ops=false` 一定要設，否則 OP 會在遊戲裡一直看到 RCON 指令的訊息。
- 同一台主機有多個伺服器時，每個伺服器的 `rcon.port` 必須不同。
- **不要在防火牆開放 RCON port。** RCON 沒有加密，mc-notify 只需要從本機連線。詳見 [RCON](rcon.md)。

## 2. 建立 Discord webhook

在 Discord 頻道：**編輯頻道 → 整合 → Webhook → 新 Webhook**，設定名稱與頭像後複製網址。

多個伺服器建議各建一個 webhook（可以指向同一個頻道），這樣每台伺服器有自己的名稱和頭像，外洩時也能只刪掉一個。詳見 [Discord](discord.md)。

## 3. 執行安裝腳本

```bash
git clone https://github.com/<你的帳號>/mc-notify.git
cd mc-notify
sudo ./install.sh
```

腳本會做這些事，重複執行也安全：

| 步驟 | 內容 |
|---|---|
| 檢查 Python | 確認版本 ≥ 3.8 |
| 建立帳號 | 系統帳號 `mc-notify`，無法登入、沒有家目錄 |
| 安裝程式 | `/opt/mc-notify/mc_notify.py` 與設定檔範例，擁有者 root、權限 644 |
| 設定目錄 | `/etc/mc-notify/`，權限 700 |
| 安裝服務 | `/etc/systemd/system/mc-notify@.service` 並 `daemon-reload` |
| 更新時 | 重新啟動執行中的實例，套用新版程式 |
| 舊版偵測 | 發現舊的 `mc-notify.service` 時提出警告（見 [遷移](migration.md)） |

## 4. 新增伺服器

```bash
sudo ./install.sh add modpack --group <伺服器的群組>
```

- `modpack` 是實例名稱，只能用英數字、底線、連字號。之後的服務名稱就是 `mc-notify@modpack`。
- 會從範例建立 `/etc/mc-notify/modpack.env`（root 擁有、權限 600）。已存在的設定檔不會被覆蓋。
- `--group` 會把 `mc-notify` 帳號加入該群組，讓它能讀取伺服器的 log。

### 確認讀取權限

服務帳號必須能讀取 `logs/latest.log`，要附上 crash report 的話還要能讀 `crash-reports/`。路徑上的**每一層目錄**都需要執行（x）權限：

```bash
# 查看伺服器檔案屬於哪個群組
ls -ld /伺服器路徑

# 逐層檢查權限
namei -l /伺服器路徑/logs/latest.log

# 實際測試
sudo -u mc-notify head -n 3 /伺服器路徑/logs/latest.log
sudo -u mc-notify ls /伺服器路徑/crash-reports
```

Ubuntu 21.04 之後，新建的家目錄預設是 `750`。如果伺服器放在 `/home/使用者/` 底下，`mc-notify` 必須加入該使用者的群組才進得去。

## 5. 編輯設定檔

```bash
sudo nano /etc/mc-notify/modpack.env
```

至少要填：

```bash
MC_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
MC_RCON_PASSWORD=跟server.properties一樣
MC_LOG_PATH=/伺服器路徑/logs/latest.log
MC_RCON_PORT=25575
MC_TPS_COMMAND=forge tps
MC_SERVER_NAME=模組服
```

所有選項見 [設定](configuration.md)。`MC_TPS_COMMAND` 依伺服器類型不同，見 [伺服器類型](servers.md)。

## 6. 檢查設定

```bash
sudo ./install.sh check modpack               # 只檢查
sudo ./install.sh check modpack --send-test   # 檢查並發送測試訊息
```

檢查會用 `systemd-run` 以**服務帳號的身分、相同的設定檔與沙箱**執行 `mc_notify.py --check`，結果跟正式服務一致。檢查項目：

- 必要設定是否齊全、格式是否正確
- 能否讀取 log 與 crash report 目錄
- 狀態看板的紀錄目錄能否寫入（有開看板時）
- RCON 能否登入，TPS 指令與 `list` 的輸出能否解析
- 加上 `--send-test` 時，發送一則測試訊息到 Discord

輸出範例：

```
mc-notify 2.1.0 設定檢查（模組服）
✅ 必要設定齊全
✅ 可以讀取 log：/srv/minecraft/modpack/logs/latest.log
✅ 可以讀取 crash report 目錄：/srv/minecraft/modpack/crash-reports
✅ RCON 連線成功：127.0.0.1:25575
✅ TPS 指令 'forge tps' 解析成功：TPS 20.00，MSPT 12.3 ms
✅ 玩家清單解析成功：0 / 20
✅ 已發送測試訊息到 Discord
檢查完成：全部通過
```

## 7. 啟動

```bash
sudo systemctl enable --now mc-notify@modpack
journalctl -u mc-notify@modpack -n 20
```

`enable` 設定開機自動啟動，`--now` 立即啟動。

---

## 更新

```bash
cd mc-notify
git pull
sudo ./install.sh
```

安裝腳本會自動重新啟動執行中的實例。更新後建議看一下 [CHANGELOG](../CHANGELOG.md)，並對照 `/opt/mc-notify/mc-notify.env.example` 看看有沒有新的設定可以加。

## 移除

```bash
sudo ./uninstall.sh            # 移除程式與服務，保留設定檔
sudo ./uninstall.sh --purge    # 連同設定檔、看板紀錄、服務帳號一起刪除
```

Discord 上的狀態看板訊息不會自動刪除。

---

## 手動安裝（不使用腳本）

想了解每個步驟在做什麼，或不想用腳本時：

```bash
# 服務帳號
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mc-notify
sudo usermod -aG <伺服器的群組> mc-notify

# 程式
sudo install -d -o root -g root -m 755 /opt/mc-notify
sudo install -o root -g root -m 644 mc_notify.py /opt/mc-notify/

# 設定檔
sudo install -d -o root -g root -m 700 /etc/mc-notify
sudo install -o root -g root -m 600 mc-notify.env.example /etc/mc-notify/modpack.env
sudo nano /etc/mc-notify/modpack.env

# 服務
sudo install -o root -g root -m 644 systemd/mc-notify@.service /etc/systemd/system/
sudo systemctl daemon-reload

# 以服務帳號檢查（手動版的 install.sh check）
sudo systemd-run --quiet --wait --pipe --collect \
    -p User=mc-notify -p Group=mc-notify \
    -p EnvironmentFile=/etc/mc-notify/modpack.env \
    -p StateDirectory=mc-notify/modpack \
    /usr/bin/python3 /opt/mc-notify/mc_notify.py --check

sudo systemctl enable --now mc-notify@modpack
```

各檔案為什麼要這樣設定權限，見 [安全性](security.md)。

## 不使用 systemd 時

`mc_notify.py` 本身只讀環境變數，可以直接執行（例如測試用）：

```bash
set -a; . ./test.env; set +a
python3 mc_notify.py --check
python3 mc_notify.py
```

注意 `.` 載入設定檔時，含空白的值（例如 `MC_TPS_COMMAND=forge tps`）要加引號，這點跟 systemd 的格式不同。
