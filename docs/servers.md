# 多伺服器與伺服器類型

## 多個伺服器

mc-notify 使用 systemd 的**模板服務** `mc-notify@.service`。`@` 後面的名稱（`%i`）決定讀哪個設定檔：

| 服務 | 設定檔 | 看板紀錄 |
|---|---|---|
| `mc-notify@modpack` | `/etc/mc-notify/modpack.env` | `/var/lib/mc-notify/modpack/` |
| `mc-notify@vanilla` | `/etc/mc-notify/vanilla.env` | `/var/lib/mc-notify/vanilla/` |

每個實例是獨立的程序，只佔幾 MB 記憶體，設定也完全獨立（TPS 門檻、ping、靜音、看板等）。

### 新增一台

```bash
sudo ./install.sh add vanilla --group <伺服器的群組>
sudo nano /etc/mc-notify/vanilla.env
sudo ./install.sh check vanilla --send-test
sudo systemctl enable --now mc-notify@vanilla
```

### 注意事項

- **每個伺服器的 `rcon.port` 必須不同**（例如 25575、25576、25577），每個都要設 `broadcast-rcon-to-ops=false`。
- **webhook 可以共用**，訊息的發送者名稱是 `MC_SERVER_NAME`，看得出來源。但建議每台一個 webhook，才能各自設定頭像，也方便分頻道。
- 共用同一個 webhook 又開了狀態看板時，每個實例會各自維護一則看板訊息，互不影響。
- 服務帳號要能讀取每一台伺服器的 log，可能需要加入多個群組。若每台伺服器分屬不同帳號，可以用 `sudo ./install.sh add <名稱> --user <帳號>` 讓每個實例各自使用對應的帳號。

### 管理多個實例

```bash
systemctl status 'mc-notify@*'
systemctl list-units 'mc-notify@*'
sudo systemctl restart 'mc-notify@*'       # 全部重啟
journalctl -u 'mc-notify@*' -f             # 同時看全部的 log
sudo systemctl disable --now mc-notify@vanilla   # 停用其中一台
```

---

## 伺服器類型

log 追蹤的部分（玩家進出、啟動、關閉、崩潰）對所有類型都通用。差別只在 TPS 查詢指令：

| 伺服器 | `MC_TPS_COMMAND` | 備註 |
|---|---|---|
| Forge | `forge tps` | 回傳各維度與整體的平均 tick 時間與 TPS |
| NeoForge | `neoforge tps` | |
| 原版 1.20.3 以上 | `tick query` | 回傳平均每 tick 耗時，程式換算成 TPS |
| Fabric 1.20.3 以上 | `tick query` | 使用原版指令 |
| 原版、Fabric 1.20.2 以前 | 留空 | 沒有可用的指令，只做存活檢查 |

設定完用 `sudo ./install.sh check <名稱>` 確認能解析。解析失敗時，檢查結果和服務 log 都會印出原始輸出。

### Java 版本與 Minecraft 版本

| Java | 可執行的 Minecraft 版本 |
|---|---|
| 17 | 1.18 ～ 1.20.4 |
| 21 | 1.20.5 以上 |

所以用 Java 17 的原版伺服器，只有 1.20.3、1.20.4 能用 `tick query`。

### 為什麼不用 `spark tps`

Spark 的指令是在自己的執行緒上非同步執行的，RCON 在指令回傳時就把回應送出了，這時 Spark 還沒產生輸出，所以會拿到空字串。Spark 很適合手動分析（`/spark profiler`），但不適合給程式查詢。

### 實際輸出範例

Forge 1.20.1 在控制台執行 `forge tps`：

```
Dim minecraft:overworld (minecraft:overworld): Mean tick time: 57.739 ms. Mean TPS: 17.319
Dim twilightforest:twilight_forest (...): Mean tick time: 0.029 ms. Mean TPS: 20.000
...
Overall: Mean tick time: 61.063 ms. Mean TPS: 16.376
```

透過 RCON 取得時沒有時間前綴，各行直接接在一起。程式只取最後一個 `Overall` 之後的內容，解析出 TPS 16.376、MSPT 61.063。詳見 [運作原理](how-it-works.md#tps-解析)。

原版 `tick query`：

```
Target tick rate: 20.0 per second.
Average time per tick: 62.3ms (Target: 50.0ms)
Percentiles: P50: 55.1ms P95: 80.2ms P99: 95.0ms, sample: 100
```

程式取 `Average time per tick` 的值，換算 TPS = min(20, 1000 ÷ 62.3) ≈ 16.05。

### 舊版伺服器也想要 TPS

原版從 1.16 起可以在 `server.properties` 設定 `enable-jmx-monitoring=true`，透過 JMX 取得平均 tick 時間。mc-notify 目前不支援從 JMX 讀取，做法見 [監控筆記](monitoring-notes.md#jmx)。
