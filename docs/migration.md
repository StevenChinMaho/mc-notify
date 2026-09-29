# 從舊版遷移

## 從單一服務 `mc-notify.service` 改為模板服務

早期版本使用單一服務 `mc-notify.service` 與設定檔 `/etc/mc-notify.env`。現在改為模板服務 `mc-notify@.service`，每個伺服器一個實例。

**新舊服務不要同時執行**，否則每則通知都會發兩次。

### 1. 安裝新版

```bash
sudo ./install.sh
```

安裝腳本偵測到舊服務時會提出警告，但不會自動刪除。

### 2. 搬移設定檔

```bash
sudo mv /etc/mc-notify.env /etc/mc-notify/modpack.env    # modpack 換成實例名稱
sudo chmod 600 /etc/mc-notify/modpack.env
```

對照 `/opt/mc-notify/mc-notify.env.example` 補上新的設定（見 [設定](configuration.md)）。

### 3. 確認服務帳號的權限

新的模板服務以 `mc-notify` 帳號執行。如果舊服務用的是跑伺服器的帳號，現在要讓 `mc-notify` 能讀取 log：

```bash
sudo usermod -aG <伺服器的群組> mc-notify
sudo ./install.sh check modpack
```

### 4. 停用並刪除舊服務

```bash
sudo systemctl disable --now mc-notify.service
sudo rm /etc/systemd/system/mc-notify.service
sudo rm -rf /etc/systemd/system/mc-notify.service.d    # 用 systemctl edit 改過才有
sudo systemctl daemon-reload
sudo systemctl reset-failed mc-notify.service 2>/dev/null
```

想保險一點，可以先改名成 `mc-notify.service.bak`，確認新服務沒問題再刪。systemd 不會載入 `.bak` 檔。

### 5. 啟動新實例

```bash
sudo systemctl enable --now mc-notify@modpack
systemctl list-unit-files 'mc-notify*'    # 應該只剩 mc-notify@.service
```

## 切換執行身分

從專用帳號改成跑伺服器的帳號（或反過來）不需要重裝：

```bash
sudo ./install.sh --user minecraft     # 或 --user mc-notify 改回預設
sudo systemctl restart 'mc-notify@*'
sudo ./install.sh check modpack
```

設定檔不受影響。改用其他帳號後如果看板無法寫入紀錄：

```bash
sudo chown -R minecraft /var/lib/mc-notify/modpack
```

不再需要專用帳號時可以刪掉它（它沒有家目錄，也沒有其他檔案）：

```bash
sudo userdel mc-notify
```

## 設定名稱的變化

| 版本 | 變化 |
|---|---|
| 2.2 | 執行身分可設定（`install.sh --user`），預設仍是專用帳號 `mc-notify` |
| 2.0 | 新增 `MC_AVATAR_URL`、`MC_PING_ROLE_ID`、`MC_PING_EVENTS`、`MC_SILENT_EVENTS`、`MC_ATTACH_CRASH_REPORT`、`MC_ATTACH_MAX_MB`、`MC_STATUS_BOARD`、`MC_STATUS_INTERVAL`、`MC_STATE_DIR` |
| 2.0 | **行為改變**：玩家進出通知預設改為靜音訊息。想恢復推播，設定 `MC_SILENT_EVENTS=` |
| 1.2 | `MC_TPS_COMMAND` 可以留空（只檢查存活） |
| 1.1 | 新增 `MC_NOTIFY_PLAYERS` |

舊的設定名稱都沒有更動，舊設定檔可以直接沿用。
