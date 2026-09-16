# 疑難排解

遇到問題時，先做這兩件事：

```bash
sudo ./install.sh check <名稱>              # 以服務身分檢查設定
journalctl -u mc-notify@<名稱> -n 50        # 查看服務 log
```

服務啟動時會印出目前生效的設定，可以確認設定檔有沒有被正確讀取：

```
[mc_notify] mc-notify 2.1.0 已啟動：log=/srv/minecraft/modpack/logs/latest.log，RCON=127.0.0.1:25575，TPS 指令='forge tps'
[mc_notify] 玩家進出通知=開，ping 身分組=123...（事件 ['crash', 'down']），靜音事件=['players']，附加 crash report=開，狀態看板=關
```

---

## 完全沒有收到訊息

1. `systemctl status mc-notify@<名稱>` 確認服務在執行
2. `sudo ./install.sh check <名稱> --send-test` 發測試訊息
3. 服務 log 中搜尋 `Discord` 的錯誤訊息

| log 訊息 | 原因 |
|---|---|
| `Webhook 不存在（404）` | webhook 被刪除或網址打錯 |
| `Discord 回傳 HTTP 401` / `403` | 網址中的 token 不正確 |
| `Discord 回傳 HTTP 400` | 訊息格式被拒絕，把完整錯誤回報到 issue |
| `Discord 連線失敗` | 主機無法連到外網，或 DNS 問題 |

## 設定錯誤，服務起不來

```
設定錯誤：
  MC_WEBHOOK_URL 未設定或格式錯誤
```

- 確認設定檔路徑：`/etc/mc-notify/<名稱>.env`，名稱要跟服務的 `@` 後面一致
- 註解要獨立一行，`KEY=value # 註解` 會把註解當成值
- 修改後要 `sudo systemctl restart mc-notify@<名稱>`

## 讀不到 log

```
❌ 找不到 log，或上層目錄沒有進入權限
❌ 無法進入伺服器目錄（權限不足或路徑錯誤）
```

```bash
namei -l /伺服器路徑/logs/latest.log     # 每一層都要有 x 權限
id mc-notify                              # 確認群組
sudo usermod -aG <伺服器的群組> mc-notify
sudo systemctl restart mc-notify@<名稱>   # 群組變更要重啟才會生效
```

伺服器在 `/home/使用者/` 底下時，家目錄通常是 750，`mc-notify` 必須在該使用者的群組裡。

## RCON 連不上

```
❌ RCON 無法連線（伺服器沒開，或 enable-rcon / rcon.port 設定不符）：[Errno 111] Connection refused
```

- 伺服器有沒有在執行
- `server.properties` 有 `enable-rcon=true`，而且**改完有重啟伺服器**
- `rcon.password` 不能是空的，空的時候 RCON 不會啟動
- `MC_RCON_PORT` 與 `rcon.port` 一致
- `sudo ss -tlnp | grep 25575` 確認有在監聽
- 伺服器 log 中搜尋 `RCON running on`

```
❌ RCON 密碼錯誤
```

`MC_RCON_PASSWORD` 與 `rcon.password` 不一致。注意設定檔中值前後的空白會被移除。

## TPS 無法解析

```
無法解析 TPS 指令輸出，請檢查 MC_TPS_COMMAND：'Unknown or incomplete command...'
```

- 指令與伺服器類型不符，見 [伺服器類型](servers.md#伺服器類型)
- 原版 1.20.2 以前沒有可用的指令，請把 `MC_TPS_COMMAND` 留空
- 如果輸出看起來正確卻無法解析，請把 log 中的原始輸出回報到 issue

## 同一則通知出現兩次

新舊服務同時在跑，或同一台伺服器設定了兩個實例：

```bash
systemctl list-units 'mc-notify*'
```

舊的 `mc-notify.service` 移除方式見 [遷移](migration.md)。

## 程式啟動時收到「伺服器無回應」

程式啟動時伺服器剛好沒開，而 log 中沒有 `Stopping server` 可以判斷是正常關閉，所以會通知一次。這是已知行為，伺服器啟動後就會恢復正常。

## TPS 警報太頻繁

- 提高門檻：`MC_TPS_THRESHOLD=18`
- 拉長持續時間：`MC_LOW_TPS_COUNT=20`（20 × 30 秒 = 10 分鐘）
- 先用 `/spark profiler` 找出並解決卡頓來源

## 伺服器崩潰了，但沒有附上 crash report

- 服務 log 中有 `無法讀取 crash report`：`mc-notify` 對 `crash-reports/` 沒有讀取權限
- crash report 路徑是相對路徑，而 `MC_SERVER_DIR` 推算錯誤：手動設定 `MC_SERVER_DIR`
- Watchdog 卡死超過 5 秒才寫出報告：通知會先發出，不含附件
- `MC_ATTACH_CRASH_REPORT=false`

## 狀態看板每次重啟都建立新訊息

- 服務檔要有 `StateDirectory=mc-notify/%i`（2.0 以後的版本才有）
- `sudo ./install.sh check <名稱>` 確認紀錄目錄可寫入
- 更換 webhook 網址後會建立新看板，這是預期行為

## 狀態看板停在「最後更新 很久以前」

mc-notify 本身停止或當掉了：

```bash
systemctl status mc-notify@<名稱>
journalctl -u mc-notify@<名稱> -n 50
```

## 身分組沒有被 ping

- `MC_PING_ROLE_ID` 是純數字的身分組 ID，不是名稱
- 事件名稱有在 `MC_PING_EVENTS` 裡
- 同一個事件不能也在 `MC_SILENT_EVENTS` 裡（會標記但不推播）
- 身分組要允許被提及，或頻道的 `@everyone` 要有提及身分組的權限

## 頭像沒有顯示

見 [Discord 頭像注意事項](discord.md#注意事項)。

## 玩家進出沒有通知

- `MC_NOTIFY_PLAYERS` 沒有被關掉
- 有模組改寫了進出訊息的格式：在伺服器 log 中找到玩家加入的那一行，確認是否為 `]: 名稱 joined the game` 的格式
