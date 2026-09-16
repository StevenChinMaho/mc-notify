# 安全性

mc-notify 處理的是**不可信任的輸入**：log 內容有一部分來自玩家（名稱、聊天），RCON 回應則來自一個跑著大量第三方模組的 Java 程序。因此設計上盡量縮小它能碰到的範圍。

## 執行身分

放在 `/etc/systemd/system/` 的服務，如果沒寫 `User=`，**預設以 root 執行**。mc-notify 實際需要的權限只有：

- 讀取伺服器的 `logs/` 與 `crash-reports/`
- 連線本機的 RCON
- 連線外網的 Discord
- 寫入自己的看板紀錄目錄

所以服務以專用的系統帳號 `mc-notify` 執行：無法登入、沒有家目錄，只透過群組取得讀取 log 的權限。萬一程式有漏洞被利用，影響範圍僅限於這個帳號能讀到的東西。

### 為什麼不用跑伺服器的那個帳號

也可以，設定最簡單，但那個帳號能修改世界檔、`server.properties` 與模組。用專用帳號時，mc-notify 對伺服器只有**讀取**權限。

## 檔案權限

| 路徑 | 擁有者 | 權限 | 理由 |
|---|---|---|---|
| `/opt/mc-notify/` | root:root | 755 | 服務帳號不能在裡面新增或替換檔案 |
| `/opt/mc-notify/mc_notify.py` | root:root | 644 | 只需要讀，由 `python3` 執行，不需要 x 權限 |
| `/etc/mc-notify/` | root:root | 700 | 一般使用者無法列出有哪些設定 |
| `/etc/mc-notify/*.env` | root:root | 600 | 含 webhook 網址與 RCON 密碼 |
| `/etc/systemd/system/mc-notify@.service` | root:root | 644 | |
| `/var/lib/mc-notify/<實例>/` | mc-notify | 700 | 由 systemd `StateDirectory=` 自動建立 |

### 程式檔一定要歸 root

- **如果程式檔能被服務帳號修改**：該帳號被攻破時，攻擊者可以改寫程式，每次服務重啟都會執行他的程式碼，入侵就被「持久化」了。
- **如果服務以 root 執行，而程式檔能被一般使用者修改**：這是典型的提權漏洞。

「程式歸 root、服務用一般帳號」可以同時擋住這兩種風險。

### 設定檔為什麼服務帳號讀不到也沒關係

`EnvironmentFile=` 是由 systemd（PID 1，root 身分）在切換使用者**之前**讀取的，所以設定檔可以維持 root 600，服務帳號本身完全讀不到它。

## systemd 沙箱

`mc-notify@.service` 啟用了以下限制，因為程式只讀不寫（看板紀錄目錄除外）：

| 設定 | 作用 |
|---|---|
| `NoNewPrivileges=yes` | 禁止透過 setuid 程式等方式取得更高權限 |
| `ProtectSystem=strict` | 整個檔案系統唯讀，只有 `StateDirectory` 可寫 |
| `ProtectHome=read-only` | `/home`、`/root` 唯讀 |
| `PrivateTmp=yes` | 獨立的 `/tmp` |
| `PrivateDevices=yes` | 無法存取實體裝置 |
| `ProtectKernelTunables=yes` | `/proc/sys` 等核心參數唯讀 |
| `ProtectKernelModules=yes` | 無法載入核心模組 |
| `ProtectControlGroups=yes` | cgroup 唯讀 |
| `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX` | 只允許 IPv4、IPv6 與 Unix socket |
| `RestrictNamespaces=yes` | 無法建立新的 namespace |
| `LockPersonality=yes` | 無法改變執行模式 |
| `MemoryDenyWriteExecute=yes` | 禁止可寫又可執行的記憶體 |

### ProtectHome 的注意事項

伺服器放在 `/home` 底下時，**不能**把 `ProtectHome` 改成 `yes`，那會整個隱藏 `/home`，程式就讀不到 log 了。`read-only` 是可以讀取的。

### 檢查沙箱強度

```bash
systemd-analyze security mc-notify@modpack
```

分數越低越安全，輸出也會列出還能加強的項目。

## RCON

- RCON 沒有加密，**不要在防火牆開放 RCON port**，mc-notify 只從 `127.0.0.1` 連線。
- 使用長度足夠的隨機密碼：`openssl rand -base64 24`
- 設定 `broadcast-rcon-to-ops=false`

詳見 [RCON](rcon.md#限制)。

## Discord

- **webhook 網址就是密碼**。不要貼到公開的地方，也不要提交到 git（`.gitignore` 已排除 `*.env`）。
- 外洩時在 Discord 刪除該 webhook 再重建，舊網址會立即失效。
- 看板紀錄檔只存 webhook 網址的 SHA-256 雜湊值前 16 碼，用來判斷 webhook 是否換過，**不存 token**。
- `allowed_mentions` 預設為空，玩家名稱或 crash report 內容裡的文字無法觸發任何提及。
- 玩家名稱會跳脫 Markdown 字元，避免名稱中的底線等符號破壞訊息格式。

## JMX

如果另外架設 JMX 監控，**不要開放遠端 JMX port**。傳統遠端 JMX 走 RMI 協定，歷史上有大量反序列化漏洞，未加認證的 JMX port 幾乎等於可以遠端執行程式碼。請改用只綁定本機的 jmx_exporter，詳見 [監控筆記](monitoring-notes.md#jmx)。
