# 設定

所有設定都透過環境變數提供。以 systemd 執行時，每個實例讀取 `/etc/mc-notify/<實例名稱>.env`。範例檔：[`mc-notify.env.example`](../mc-notify.env.example)。

修改設定後需要重啟該實例：

```bash
sudo systemctl restart mc-notify@modpack
journalctl -u mc-notify@modpack -n 5    # 啟動訊息會列出目前生效的設定
```

## 設定檔格式

systemd 的 `EnvironmentFile` 規則：

- 註解必須**獨立一行**，`KEY=value  # 註解` 會把註解也當成值的一部分
- 值可以有空白，不需要引號：`MC_TPS_COMMAND=forge tps`
- 被註解掉或沒寫的設定使用預設值
- 布林值：`1`、`true`、`yes`、`on`（不分大小寫）為開啟，其他值為關閉，**留空則使用預設值**
- 清單值（逗號分隔）：**留空代表空清單**，不是使用預設值

## 所有設定

### 必填

| 變數 | 說明 |
|---|---|
| `MC_WEBHOOK_URL` | Discord webhook 網址，必須是 `https://`。網址後面的查詢參數會被忽略 |
| `MC_RCON_PASSWORD` | 與 `server.properties` 的 `rcon.password` 相同 |

### 伺服器

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_SERVER_NAME` | `Minecraft` | Discord 上顯示的發送者名稱，也是狀態看板的標題 |
| `MC_LOG_PATH` | `/opt/minecraft/logs/latest.log` | 伺服器 log 檔 |
| `MC_SERVER_DIR` | log 路徑往上兩層 | 伺服器根目錄，用來解析相對路徑的 crash report |
| `MC_RCON_HOST` | `127.0.0.1` | RCON 位址 |
| `MC_RCON_PORT` | `25575` | 與 `server.properties` 的 `rcon.port` 相同 |

### Discord 外觀

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_AVATAR_URL` | 空 | 發送者頭像網址。留空則使用 webhook 本身的頭像（建議，見 [Discord](discord.md#頭像)） |

### TPS 與存活檢查

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_TPS_COMMAND` | `forge tps` | 查詢 TPS 的 RCON 指令。**留空**則不監控 TPS，只用 `list` 檢查存活。各伺服器類型的值見 [伺服器類型](servers.md) |
| `MC_TPS_THRESHOLD` | `19.5` | TPS 低於此值算一次「過低」 |
| `MC_POLL_INTERVAL` | `30` | 每幾秒查詢一次（最小 5） |
| `MC_LOW_TPS_COUNT` | `10` | 連續幾次過低才通知 |
| `MC_DOWN_COUNT` | `3` | RCON 連續失敗幾次視為無回應 |

實際的反應時間是 `次數 × 間隔`：
- TPS 警報：預設 10 × 30 秒 = **5 分鐘**
- 無回應警報：預設 3 × 30 秒 = **1.5 分鐘**

#### 門檻怎麼設

Forge 的 TPS 上限就是 20.000，只要平均每 tick 超過 50 ms 就會低於 20。自動存檔、玩家跑新區塊時常常短暫掉到 19.8 左右，這很正常，所以預設門檻是 19.5 並要求持續 5 分鐘。

- 大型模組包平常就在 19 上下：門檻設 `18`
- 只在意嚴重卡頓：門檻設 `15`，次數設 `4`（2 分鐘）

另外，Forge 的 TPS 是最近 100 個 tick（約 5 秒）的平均，查詢間隔之間的短暫尖峰不會被看到。要追查單次卡頓請用 Spark。

### 通知行為

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_NOTIFY_PLAYERS` | `true` | 玩家加入、離開的通知 |
| `MC_PING_ROLE_ID` | 空 | 要 ping 的身分組 ID（純數字）。留空則不 ping。取得方式見 [Discord](discord.md#身分組-id) |
| `MC_PING_EVENTS` | `crash,down` | 哪些事件要 ping |
| `MC_SILENT_EVENTS` | `players` | 哪些事件用靜音訊息發送（頻道照常顯示，但不推播） |

### 事件名稱

`MC_PING_EVENTS` 與 `MC_SILENT_EVENTS` 使用的名稱：

| 名稱 | 通知 | 預設 |
|---|---|---|
| `players` | 🟢 加入了伺服器、⚪ 離開了伺服器 | 靜音 |
| `start` | ✅ 伺服器已啟動 | |
| `stop` | ⏹️ 伺服器正在關閉 | |
| `crash` | 💥 伺服器崩潰 | ping |
| `down` | 🔴 伺服器無回應 | ping |
| `up` | ✅ 伺服器恢復回應 | |
| `tps_low` | 🐢 TPS 持續過低 | |
| `tps_ok` | 👍 TPS 已恢復 | |

名稱不分大小寫，打錯時啟動 log 會出現警告。同一個事件同時設為 ping 和靜音時，身分組會被標記但收不到推播，啟動時也會警告。

### Crash report

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_ATTACH_CRASH_REPORT` | `true` | 崩潰通知附上 crash report 檔案。關閉時仍會顯示描述與例外摘要 |
| `MC_ATTACH_MAX_MB` | `8` | 附件大小上限。超過時只附前段（stack trace 在最前面） |

### 狀態看板

| 變數 | 預設值 | 說明 |
|---|---|---|
| `MC_STATUS_BOARD` | `false` | 開啟後會發一則訊息並持續編輯 |
| `MC_STATUS_INTERVAL` | `60` | 更新間隔秒數（最小 10） |
| `MC_STATE_DIR` | 自動 | 存放看板訊息 ID 的目錄。systemd 服務會透過 `StateDirectory=` 自動設定為 `/var/lib/mc-notify/<實例名稱>`，通常不用填 |

沒有 `MC_STATE_DIR` 時看板仍可運作，但每次重啟都會建立新訊息。

---

## 設定範例

### Forge 模組服（完整功能）

```bash
MC_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/yyyy
MC_RCON_PASSWORD=...
MC_SERVER_NAME=模組服
MC_LOG_PATH=/srv/minecraft/modpack/logs/latest.log
MC_RCON_PORT=25575
MC_TPS_COMMAND=forge tps
MC_TPS_THRESHOLD=18
MC_PING_ROLE_ID=123456789012345678
MC_PING_EVENTS=crash,down,tps_low
MC_STATUS_BOARD=true
```

### 原版 1.20.4、不要玩家通知

```bash
MC_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/zzzz
MC_RCON_PASSWORD=...
MC_SERVER_NAME=原版服
MC_LOG_PATH=/srv/minecraft/vanilla/logs/latest.log
MC_RCON_PORT=25576
MC_TPS_COMMAND=tick query
MC_NOTIFY_PLAYERS=false
```

### 舊版原版（1.20.2 以前），只要崩潰與存活通知

```bash
MC_WEBHOOK_URL=https://discord.com/api/webhooks/xxxx/wwww
MC_RCON_PASSWORD=...
MC_SERVER_NAME=懷舊服
MC_LOG_PATH=/srv/minecraft/legacy/logs/latest.log
MC_RCON_PORT=25577
MC_TPS_COMMAND=
MC_NOTIFY_PLAYERS=false
MC_SILENT_EVENTS=start,stop
```

### 所有通知都正常推播

```bash
MC_SILENT_EVENTS=
```
