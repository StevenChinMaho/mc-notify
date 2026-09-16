# 開發

## 測試

只需要 Python，不需要安裝任何套件。

```bash
# 單元測試（幾秒）
python3 -m unittest discover -s tests -v

# 加上整合測試（約 70 秒）
MC_NOTIFY_INTEGRATION=1 python3 -m unittest discover -s tests -v

# 安裝腳本
shellcheck install.sh uninstall.sh
```

| 檔案 | 內容 |
|---|---|
| `tests/test_parsing.py` | TPS 與玩家清單解析、log 事件判斷、crash report、設定讀取、訊息組成 |
| `tests/test_integration.py` | 啟動假的 Discord（HTTP）與假的 RCON 伺服器，實際執行程式，測試完整生命週期、狀態看板、`--check` |
| `tests/helpers.py` | 在指定環境變數下重新載入模組、記錄通知 |

整合測試涵蓋：啟動、玩家進出、聊天誤判、TPS 過低與恢復、watchdog 與 crash report 合併、崩潰後關閉不重複通知、重新啟動、無預警消失與恢復、SIGTERM、看板沿用與重建、Discord 429 重試。

GitHub Actions（`.github/workflows/tests.yml`）會在每次 push 時執行單元測試（Python 3.10、3.12、3.13）、整合測試與 shellcheck。

## 程式結構

`mc_notify.py` 由上而下：

| 區段 | 內容 |
|---|---|
| 設定讀取工具、設定 | `env_str`、`env_bool`、`env_set` 等，模組載入時讀取所有環境變數 |
| 常數與共用狀態 | 顏色、旗標、`state`（由 `state_lock` 保護） |
| Discord HTTP | `discord_request`（重試、429、multipart） |
| 一般通知 | `notify` 放入佇列，`_sender` 執行緒發送 |
| Crash report | 讀取、摘要、`send_crash` |
| Log 追蹤 | 正規表示式、`handle_line`、`follow_log` |
| RCON | `Rcon` 類別 |
| 輸出解析 | `parse_tps`、`parse_list` |
| 狀態看板 | `StatusBoard`、`board_status`、`board_embed` |
| 主監控迴圈 | `monitor` |
| 啟動 | `validate`、`main`、`run_check`、`cli` |

設計原則：

- 只用標準函式庫，維持單一檔案，方便複製部署
- 語法相容 Python 3.8
- 所有設定都來自環境變數

## 新增一種事件

1. 在 `EVENTS` 加上名稱
2. 在 `handle_line` 或 `monitor` 中呼叫 `notify("事件名稱", ...)`
3. 在 `tests/test_parsing.py` 加上測試
4. 更新 `mc-notify.env.example` 與 `docs/configuration.md` 的事件列表

## 發布新版本

1. 修改 `mc_notify.py` 的 `__version__`
2. 更新 `CHANGELOG.md`
3. 如有新設定，更新 `mc-notify.env.example`、`docs/configuration.md`、`docs/migration.md`
4. 執行全部測試
5. 提交並加上標籤：
   ```bash
   git commit -am "v2.1.0"
   git tag v2.1.0
   git push --follow-tags
   ```

使用者更新時只需要 `git pull && sudo ./install.sh`。
