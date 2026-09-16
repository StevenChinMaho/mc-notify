# 更新紀錄

## 2.1.0 — 2026-09-16

### 新增
- 安裝工具 `install.sh`：安裝與更新、`add` 新增伺服器、`check` 以服務身分檢查設定
- 移除工具 `uninstall.sh`，可選擇 `--purge` 完全移除
- `--check`：檢查設定、log 與 crash report 讀取權限、看板紀錄目錄、RCON 連線、TPS 與玩家清單解析
- `--send-test`：檢查並發送測試訊息
- `--version`
- 完整文件與單元測試、整合測試、GitHub Actions

### 修正
- TPS 數字支援逗號小數點（JVM 語系為德文、法文等時，Forge 會輸出 `16,376`）
- 解析時改取最後一個 `Overall`，避免維度名稱干擾

## 2.0.0

### 新增
- 指定事件 ping 身分組（`MC_PING_ROLE_ID`、`MC_PING_EVENTS`）
- 靜音訊息（`MC_SILENT_EVENTS`），玩家進出預設靜音
- 自訂頭像（`MC_AVATAR_URL`）
- 崩潰通知附上 crash report 檔案，並顯示描述與例外摘要
- Watchdog 卡死與 crash report 合併為一則通知
- TPS 通知改用欄位顯示 TPS、MSPT、持續時間
- 狀態看板（`MC_STATUS_BOARD`），重啟後沿用同一則訊息，被刪除時自動重建
- 收到 SIGTERM 時送完佇列中的通知，並將看板標示為停止
- systemd 模板服務加上 `StateDirectory=`

### 修正
- RCON 登入失敗時沒有關閉 socket，伺服器恢復後第一次查詢必定失敗
- 崩潰後重新啟動期間，失敗次數超過門檻，導致之後再次掛掉時不會通知
- 伺服器啟動完成、RCON 尚未就緒時可能誤報無回應
- 重新啟動後同時發出「已啟動」與「恢復回應」

### 行為改變
- 玩家進出通知預設改為靜音

## 1.2.0
- 支援多個伺服器（systemd 模板服務 `mc-notify@.service`）
- 支援原版伺服器：`MC_TPS_COMMAND=tick query`
- `MC_TPS_COMMAND` 留空時只檢查存活
- 相容 Python 3.10 以前的 f-string 語法

## 1.1.0
- `MC_NOTIFY_PLAYERS` 開關

## 1.0.0
- 玩家加入與離開、伺服器啟動與關閉、崩潰、無回應、TPS 過低通知
- log 追蹤與 RCON 輪詢
- Discord 429 速率限制處理
