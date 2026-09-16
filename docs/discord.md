# Discord

## 建立 webhook

**編輯頻道 → 整合 → Webhook → 新 Webhook**（或 **伺服器設定 → 整合 → Webhook**），設定名稱、頭像與頻道，然後複製網址填入 `MC_WEBHOOK_URL`。

webhook 網址本身就是密碼，任何人拿到都能發訊息到該頻道。外洩時直接在 Discord 刪除該 webhook，重建後更新設定檔即可。

## 頭像

有三種做法，由簡單到複雜：

### 1. 使用 webhook 本身的頭像（推薦）

`MC_AVATAR_URL` 留空，訊息就會使用 webhook 設定頁上傳的頭像，完全不需要網址。

多個伺服器時，**每台各建一個 webhook**（可以指向同一個頻道），各自上傳頭像，再填進各自的設定檔。

### 2. 放在 GitHub

需要共用一個 webhook 時，可以把圖片放在公開 repo，使用 raw 網址：

```bash
MC_AVATAR_URL=https://raw.githubusercontent.com/<帳號>/<repo>/main/icons/modpack.png
```

### 3. 用自己的網頁伺服器

已經有 nginx 的話，加一個靜態路徑即可：

```nginx
location /mc-icons/ {
    alias /usr/share/nginx/mc-icons/;
    expires 7d;
    add_header Cache-Control "public";
    autoindex off;
}
```

Docker 環境下把圖片目錄唯讀掛載進去：

```yaml
volumes:
  - ./mc-icons:/usr/share/nginx/mc-icons:ro
```

伺服器目錄下的 `server-icon.png`（伺服器列表上的圖示，64×64）可以直接拿來用。

### 注意事項

- 網址必須是公開、`https`、不需登入的圖片，建議用正方形的 PNG 或 JPG。
- **不要用 Discord 附件的網址**：附件網址帶有會過期的簽章，一段時間後頭像會消失。
- **Discord 會快取頭像**：同一個網址換圖片可能很久都不會更新，換圖時改檔名或加上 `?v=2`。
- 網站在 Cloudflare 後面而頭像沒顯示時，檢查 Bot Fight Mode 或 WAF 規則是否擋掉了 Discord 的抓取程式（在安全事件紀錄搜尋 `Discordbot`）。

## 身分組 ID

`MC_PING_ROLE_ID` 需要身分組的數字 ID：

1. **使用者設定 → 進階 → 開發者模式** 打開
2. **伺服器設定 → 身分組**，在身分組上按右鍵 → **複製身分組 ID**

也可以在任一頻道輸入 `\@身分組名稱` 送出，訊息會顯示成 `<@&123456789012345678>`，中間的數字就是 ID。

身分組需要允許被提及，或 webhook 所在頻道的 `@everyone` 要有「提及 @everyone、@here 和所有身分組」權限，否則 ping 不會生效。

## 靜音訊息

`MC_SILENT_EVENTS` 裡的事件會加上 Discord 的 `SUPPRESS_NOTIFICATIONS` 旗標：訊息照常出現在頻道，但不會觸發手機或桌面推播。適合玩家進出這類頻繁、低重要性的通知。

## 狀態看板

開啟 `MC_STATUS_BOARD=true` 後，程式會發一則訊息並持續編輯它。

- **建立後建議手動釘選**，方便隨時查看
- 看板訊息本身以靜音方式發送，編輯也不會觸發推播
- 刪除看板訊息後，程式會在下次更新時自動重建
- 想換一則新的看板：刪除舊訊息即可；或停止服務後刪除 `/var/lib/mc-notify/<實例名稱>/status_board.json`
- 移除 mc-notify 時，看板訊息不會自動刪除

建議把看板放在獨立的頻道，避免被一般通知洗到上面去找不到。

---

## Webhook 能做到什麼

以下是 Discord webhook 的能力整理，mc-notify 用到的部分已標註。

### 訊息內容

- **純文字 `content`**：最多 2000 字元，支援 Markdown（粗體、斜體、刪除線、防雷、標題、`-#` 小字、清單、引用、程式碼區塊、遮罩連結）
- **動態時間戳** `<t:Unix時間:R>`：依觀看者時區與語言顯示成「3 分鐘前」— *看板的最後更新時間*
- **提及** `<@使用者ID>`、`<@&身分組ID>`，並可用 `allowed_mentions` 精確控制哪些提及會通知 — *ping 功能*

### Embed（一則訊息最多 10 個）

| 元素 | 限制 | mc-notify |
|---|---|---|
| `title` | 256 字 | 事件標題 |
| `description` | 4096 字 | 事件說明 |
| `fields` | 最多 25 組，名稱 256 字、值 1024 字；`inline` 可並排 | TPS、MSPT、崩潰摘要、看板資訊 |
| `color` | 左側色條 | 依事件類型 |
| `timestamp` | 顯示為觀看者的時區 | 所有通知 |
| `footer` | 2048 字 | 看板更新間隔 |
| `author`、`thumbnail`、`image` | | 未使用 |

一則訊息所有 embed 的文字加總不能超過 6000 字元。

### 其他

- **每則訊息可改名稱與頭像**：`username`、`avatar_url` — *`MC_SERVER_NAME`、`MC_AVATAR_URL`*
- **附件**：multipart 上傳，embed 中可用 `attachment://檔名` 引用圖片 — *crash report*
- **編輯與刪除自己發的訊息**：發送時加 `?wait=true` 取得訊息 ID — *狀態看板*
- **旗標**：`SUPPRESS_NOTIFICATIONS`（靜音）、`SUPPRESS_EMBEDS` — *靜音事件*
- **討論串**：`thread_id` 發到指定討論串；論壇頻道可用 `thread_name` 開新貼文
- **投票**、TTS
- **非互動式元件**：加 `?with_components=true` 可以送連結按鈕與 Components V2 版面元件（與 `content`、`embeds` 不能混用）

### 做不到的

一般 webhook 是**單向**的：

- 不能使用會觸發動作的按鈕或選單（例如「按一下重啟伺服器」）
- 不能讀取頻道、收不到回覆、不能加反應
- 不能使用斜線指令

需要雙向互動時，要改寫成 Discord Bot。

### 速率限制

送太快會收到 HTTP 429，回應中的 `retry_after` 表示要等幾秒。mc-notify 會依此等待後重試。
