# 監控筆記

mc-notify 負責的是**即時通知**。這份筆記整理 Minecraft 伺服器其他的監控方式，以及它們各自適合的情境。

## 各層級的工具

| 層級 | 工具 | 適合 |
|---|---|---|
| 遊戲效能分析 | Spark | 找出是哪個模組、實體、方塊造成卡頓 |
| 即時通知 | mc-notify | 崩潰、卡頓、玩家進出 |
| 服務存活 | Uptime Kuma | 簡單的上線監控與通知（內建 GameDig 類型可偵測 Minecraft） |
| 長期趨勢 | Prometheus + Grafana | 幾個月的 CPU、記憶體、TPS 歷史圖表 |
| 管理面板 | MCSManager、Crafty Controller、Pelican | 網頁控制台、排程、備份 |
| 臨時查看 | `btop`、`htop`、`journalctl` | 手動排查 |

## Spark

模組服的首選，Forge、NeoForge、Fabric 都支援。

```
/spark tps                     TPS 與 MSPT
/spark health                  CPU、記憶體、GC 狀況
/spark profiler start          開始錄製
/spark profiler stop           停止並產生網頁報告
/spark tickmonitor             每個超過門檻的 tick 都寫進 log
```

profiler 報告可以看出 CPU 時間花在哪個模組的哪個方法上。TPS 警報出現後，先錄 3～5 分鐘的 profiler 是最有效的第一步。

`tickmonitor` 會在 log 留下 `[⚡] Tick #1753 lasted 63.22 ms` 這類訊息，mc-notify 會忽略這些行。

### 看懂 `forge tps`

```
Dim minecraft:overworld (...): Mean tick time: 57.739 ms. Mean TPS: 17.319
Dim twilightforest:twilight_forest (...): Mean tick time: 0.029 ms. Mean TPS: 20.000
...
Overall: Mean tick time: 61.063 ms. Mean TPS: 16.376
```

- 每個維度的時間可以看出**卡頓集中在哪個世界**。上例幾乎全部集中在主世界。
- `Overall` 除了各維度，還包含網路、玩家資料等其他工作，所以會比各維度加總多一點。
- 每 tick 的預算是 50 ms，超過就會掉 TPS。

---

## JMX

JMX（Java Management Extensions）是 JVM 內建的管理介面，透過 MBean 公開 JVM 內部狀態。

### JMX 看得到什麼

- heap 與各記憶體區塊的用量
- GC 次數與耗時
- 執行緒數量、類別載入數、程序 CPU 使用率
- **Minecraft 的平均 tick 時間**（需要開啟，見下方）

| | Spark | JMX |
|---|---|---|
| 遊戲層級（TPS、哪個模組卡） | ✅ 強項 | ❌ |
| JVM 層級（heap、GC） | ✅ 當下狀態 | ✅ |
| 長期歷史 | 有限 | ✅ 搭配 Prometheus |
| 警報 | ❌ | ✅ 搭配 Alertmanager |

JMX 真正補上的是 **JVM 指標的長期時間序列與警報**。

### 什麼時候值得架

- 想知道 heap 實際用到多少，決定 `-Xmx` 要給多少
- 懷疑記憶體洩漏：GC 後的 heap 底線隨時間持續上升
- 想在 OOM **之前**收到警報
- 想比較不同 GC（G1、ZGC）的停頓時間

只要崩潰與 TPS 通知的話，不需要 JMX。

### Minecraft 內建的 tick 指標

`server.properties`：

```properties
enable-jmx-monitoring=true
```

原版 1.16 起支援（Forge 也有，因為是原版程式碼）。開啟後會註冊 MBean `net.minecraft.server:type=Server`：

| 屬性 | 內容 |
|---|---|
| `averageTickTime` | 最近 100 個 tick 的平均耗時（ms） |
| `tickTimes` | 最近 100 個 tick 各自的耗時（陣列） |

### 用 jmx_exporter，不要開遠端 JMX

傳統遠端 JMX 走 RMI，有大量反序列化漏洞歷史，還會另外開隨機 port。改用 Prometheus 官方的 [jmx_exporter](https://github.com/prometheus/jmx_exporter)，它以 Java agent 形式載入，把 MBean 轉成唯讀的 HTTP `/metrics`：

```bash
java -javaagent:/opt/jmx_exporter/jmx_prometheus_javaagent.jar=127.0.0.1:9404:/opt/jmx_exporter/config.yaml \
     -Xms... -Xmx... -jar server.jar nogui
```

Forge 通常用 `run.sh` 啟動，`-javaagent` 參數要加在 `user_jvm_args.txt`。

`config.yaml`：

```yaml
lowercaseOutputName: true
rules:
  - pattern: 'net.minecraft.server<type=Server><>averageTickTime'
    name: minecraft_average_tick_time_ms
    help: "Average tick time over the last 100 ticks (ms)"
    type: GAUGE
```

- 寫了 `rules` 就只輸出符合規則的 MBean；JVM 本身的記憶體、GC 指標由 agent 另外提供，不受影響
- `tickTimes` 是陣列，jmx_exporter 不會輸出
- 確認：`curl -s 127.0.0.1:9404/metrics | grep minecraft`

PromQL 範例：

```promql
# TPS
clamp_max(1000 / minecraft_average_tick_time_ms, 20)

# 警報：5 分鐘平均 MSPT 超過 50 ms
avg_over_time(minecraft_average_tick_time_ms[5m]) > 50
```

### JMX 與 RCON 的差別

| | JMX `averageTickTime` | RCON `forge tps` |
|---|---|---|
| 查詢時打擾主執行緒 | 不會 | 會（指令排進主執行緒） |
| 分維度 | ❌ | ✅ |
| 需要開 RCON | ❌ | ✅ |
| 能偵測卡死 | ❌ | ✅ |

**JMX 無法偵測卡死**：主執行緒卡住時，`averageTickTime` 會停在最後一次更新的值，而 JMX 讀取不經過主執行緒，所以看起來「一切正常」。這是 mc-notify 使用 RCON 的主要原因。

另外 100 tick 只有約 5 秒，Prometheus 每 15 秒抓一次會漏掉中間的尖峰。

完整架構是 **jmx_exporter → Prometheus → Grafana**，警報再加 **Alertmanager**（有原生的 Discord 接收器）。對單一伺服器來說比較重，但如果已經要看記憶體圖表，順便加上 tick 時間，就能看出「GC 停頓時 MSPT 飆高」這類關聯。

---

## 輕量的診斷方式

不需要常駐監控、也不用開任何 port。

### GC log

JVM 參數加上：

```
-Xlog:gc*:file=logs/gc.log:time,uptime:filecount=5,filesize=10M
```

Java 17 會記錄每次 GC，最多保留 5 個 10 MB 的檔案。出問題時再丟給 GCeasy 之類的工具分析。**成本幾乎是零，建議直接加上。**

### jcmd 與 JFR

需要 **JDK**（不是 JRE），用 `which jcmd` 確認。

```bash
jcmd <PID> GC.heap_info                                    # 目前 heap 狀況
jcmd <PID> JFR.start duration=10m filename=/tmp/mc.jfr     # 錄 10 分鐘
```

`.jfr` 檔用 JDK Mission Control 開啟，內容比 JMX 詳細很多。

### VisualVM

需要臨時連線時，一定要透過 SSH tunnel，不要開放 port。

---

## 建議

1. 先加上 **GC log**
2. 用 **Spark** 處理效能問題，用 **mc-notify** 處理通知
3. 常遇到記憶體相關的卡頓或崩潰時，再架 **jmx_exporter + Prometheus + Grafana**
