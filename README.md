# mc-notify

Minecraft Java 伺服器的 Discord 通知工具。追蹤伺服器 log 並透過 RCON 定期查詢，把崩潰、卡頓、玩家進出等事件即時發送到 Discord webhook。

- 單一 Python 檔案，只用標準函式庫，不需要 `pip install`
- 以 systemd 服務執行，一台主機可以同時監控多個伺服器
- 支援 Forge、NeoForge、Fabric 與原版伺服器

## 功能

| 通知 | 觸發條件 |
|---|---|
| 💥 伺服器崩潰 | log 出現 crash report 或 watchdog 卡死訊息；會附上 crash report 檔案與例外摘要 |
| 🔴 伺服器無回應 | RCON 連續失敗，且 log 沒有正常關閉的紀錄（`kill -9`、OOM、JVM 崩潰、卡死） |
| 🐢 TPS 持續過低 | TPS 連續多次低於門檻，恢復時另外通知 |
| ✅ / ⏹️ 啟動與關閉 | log 出現 `Done (...)!` 或 `Stopping server` |
| 🟢 / ⚪ 玩家加入與離開 | 可關閉；預設以靜音訊息發送 |
| 📊 狀態看板 | 持續編輯同一則訊息，顯示運作狀態、線上玩家、TPS |

其他功能：指定事件 ping 身分組、自訂發送者名稱與頭像、設定檢查與測試訊息（`--check`、`--send-test`）。

## 需求

- 使用 systemd 的 Linux（在 Ubuntu 上開發與測試）
- Python 3.8 以上
- Minecraft Java 伺服器，並開啟 RCON
- 一個 Discord webhook

## 快速開始

```bash
git clone https://github.com/<你的帳號>/mc-notify.git
cd mc-notify

# 1. 安裝程式與 systemd 服務
#    預設建立專用帳號 mc-notify；想直接用跑伺服器的帳號就加 --user
sudo ./install.sh
# sudo ./install.sh --user minecraft

# 2. 為伺服器建立設定檔
#    用專用帳號時，--group 填伺服器檔案所屬的群組，讓它讀得到 log
sudo ./install.sh add modpack --group <伺服器的群組>
sudo nano /etc/mc-notify/modpack.env
```

服務的執行身分可以自由選擇：專用帳號 `mc-notify`（預設，權限最小）或跑伺服器的帳號（設定最簡單）。取捨見 [安全性](docs/security.md#執行身分)。

在伺服器的 `server.properties` 開啟 RCON，然後重啟伺服器：

```properties
enable-rcon=true
rcon.port=25575
rcon.password=一組長的隨機密碼
broadcast-rcon-to-ops=false
```

檢查設定、發送測試訊息，最後啟動服務：

```bash
sudo ./install.sh check modpack --send-test
sudo systemctl enable --now mc-notify@modpack
```

詳細步驟見 [安裝說明](docs/installation.md)。

## 常用指令

```bash
systemctl status 'mc-notify@*'              # 查看所有實例
journalctl -u mc-notify@modpack -f          # 即時查看 log
sudo systemctl restart mc-notify@modpack    # 修改設定後重啟
sudo ./install.sh check modpack             # 檢查設定

# 更新到最新版
git pull && sudo ./install.sh
```

## 文件

| 文件 | 內容 |
|---|---|
| [安裝說明](docs/installation.md) | 完整安裝流程、手動安裝、更新與移除 |
| [設定](docs/configuration.md) | 所有環境變數、事件名稱、設定範例 |
| [多伺服器與伺服器類型](docs/servers.md) | 多個伺服器、Forge / NeoForge / Fabric / 原版的差異 |
| [運作原理](docs/how-it-works.md) | log 追蹤、TPS 解析、崩潰判斷、狀態看板 |
| [RCON](docs/rcon.md) | RCON 協定、功能與限制 |
| [Discord](docs/discord.md) | webhook 能做什麼、頭像、身分組 ID、狀態看板 |
| [安全性](docs/security.md) | 執行身分、檔案權限、systemd 沙箱 |
| [監控筆記](docs/monitoring-notes.md) | Spark、JMX、Prometheus、GC log 等其他監控方式 |
| [疑難排解](docs/troubleshooting.md) | 常見問題與解法 |
| [從舊版遷移](docs/migration.md) | 從單一 `mc-notify.service` 改為模板服務 |
| [開發](docs/development.md) | 測試方式與專案結構 |

## 專案結構

```
mc-notify/
├── mc_notify.py              主程式
├── mc-notify.env.example     設定檔範例
├── install.sh                安裝、新增伺服器、檢查設定
├── uninstall.sh              移除
├── systemd/
│   └── mc-notify@.service    systemd 模板服務
├── docs/                     文件
└── tests/                    單元測試與整合測試
```

## 授權

[MIT](LICENSE)
