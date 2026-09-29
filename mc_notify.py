#!/usr/bin/env python3
"""
mc_notify.py — Minecraft 伺服器 Discord Webhook 通知

功能（全部可在 .env 設定）：
  - 玩家加入 / 退出（可關閉，預設以靜音訊息發送）
  - 伺服器啟動 / 正常關閉
  - 崩潰（crash report、watchdog 卡死），可附上 crash report 檔案
  - 伺服器無回應（被 kill、OOM、JVM 直接掛掉等沒留下 log 的情況）
  - TPS 持續過低，以及恢復通知
  - 指定事件 ping 身分組
  - 即時狀態看板（持續編輯同一則訊息）

原理：追蹤 logs/latest.log + 透過 RCON 定期查詢
只用 Python 標準函式庫（Python 3.8+），不需要 pip install

用法：
  mc_notify.py               正常執行（通常由 systemd 啟動）
  mc_notify.py --check       檢查設定、檔案權限與 RCON 連線
  mc_notify.py --send-test   同上，並發送一則測試訊息到 Discord
"""
import argparse
import hashlib
import json
import os
import queue
import re
import signal
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

__version__ = "2.2.0"


# ===================== 設定讀取工具 =====================
def env_str(name, default=""):
    return os.environ.get(name, default).strip()


def env_bool(name, default):
    v = env_str(name)
    if v == "":
        return default
    return v.lower() in ("1", "true", "yes", "on")


def env_int(name, default):
    v = env_str(name)
    return int(v) if v else default


def env_float(name, default):
    v = env_str(name)
    return float(v) if v else default


def env_set(name, default):
    """逗號分隔清單；有設定但留空 = 空集合"""
    v = os.environ.get(name)
    if v is None:
        v = default
    return {x.strip().lower() for x in v.split(",") if x.strip()}


# ===================== 設定 =====================
WEBHOOK_URL   = env_str("MC_WEBHOOK_URL").split("?")[0].rstrip("/")
SERVER_NAME   = env_str("MC_SERVER_NAME", "Minecraft")
AVATAR_URL    = env_str("MC_AVATAR_URL")

LOG_PATH      = env_str("MC_LOG_PATH", "/opt/minecraft/logs/latest.log")
SERVER_DIR    = env_str("MC_SERVER_DIR") or os.path.dirname(os.path.dirname(os.path.abspath(LOG_PATH)))

RCON_HOST     = env_str("MC_RCON_HOST", "127.0.0.1")
RCON_PORT     = env_int("MC_RCON_PORT", 25575)
RCON_PASSWORD = env_str("MC_RCON_PASSWORD")

# Forge: "forge tps" / NeoForge: "neoforge tps" / 原版或 Fabric 1.20.3+: "tick query"
# 設為空字串 → 不監控 TPS，只用 RCON 的 "list" 檢查存活
TPS_COMMAND   = env_str("MC_TPS_COMMAND", "forge tps")
TPS_THRESHOLD = env_float("MC_TPS_THRESHOLD", 19.5)
POLL_INTERVAL = max(5, env_int("MC_POLL_INTERVAL", 30))
LOW_TPS_COUNT = max(1, env_int("MC_LOW_TPS_COUNT", 10))
DOWN_COUNT    = max(1, env_int("MC_DOWN_COUNT", 3))

NOTIFY_PLAYERS = env_bool("MC_NOTIFY_PLAYERS", True)

# 事件名稱：players start stop crash down up tps_low tps_ok
EVENTS = {"players", "start", "stop", "crash", "down", "up", "tps_low", "tps_ok"}
PING_ROLE_ID  = env_str("MC_PING_ROLE_ID")
PING_EVENTS   = env_set("MC_PING_EVENTS", "crash,down")
SILENT_EVENTS = env_set("MC_SILENT_EVENTS", "players")

ATTACH_CRASH_REPORT = env_bool("MC_ATTACH_CRASH_REPORT", True)
ATTACH_MAX_BYTES    = int(env_float("MC_ATTACH_MAX_MB", 8) * 1024 * 1024)

STATUS_BOARD    = env_bool("MC_STATUS_BOARD", False)
STATUS_INTERVAL = max(10, env_int("MC_STATUS_INTERVAL", 60))
# systemd 的 StateDirectory= 會自動設定 STATE_DIRECTORY
STATE_DIR = env_str("MC_STATE_DIR") or env_str("STATE_DIRECTORY").split(":")[0]

# ===================== 常數與共用狀態 =====================
GREEN, GREY, RED, ORANGE, BLUE, YELLOW = 0x2ECC71, 0x95A5A6, 0xE74C3C, 0xE67E22, 0x3498DB, 0xF1C40F
FLAG_SILENT = 1 << 12          # SUPPRESS_NOTIFICATIONS
USER_AGENT = f"mc-notify/{__version__}"
CRASH_REPORT_WAIT = 5          # watchdog 判定卡死後，等 crash report 寫出的秒數

state_lock = threading.Lock()
state = {
    "expected_stop": False,   # 預期中的關閉（不發「無回應」）
    "crashed": False,
    "crash_sent": False,
    "crash_timer": None,
    "phase": "unknown",       # starting / running / stopping / crashed
    "version": None,
    "started_at": None,       # Unix 時間
    "boot_gen": 0,            # 每次啟動完成 +1，讓監控迴圈重新計算失敗次數
}


def log(msg):
    print(f"[mc_notify] {msg}", flush=True)  # systemd 下會進 journald


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def clip(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fmt_duration(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    m, s = divmod(seconds, 60)
    return f"{m} 分鐘" + (f" {s} 秒" if s else "")


def md_escape(text):
    return re.sub(r"([_*~`|>\\])", r"\\\1", text)


# ===================== Discord HTTP =====================
class NotFound(Exception):
    pass


def _encode_multipart(payload, files):
    boundary = uuid.uuid4().hex
    out = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
        f"Content-Type: application/json\r\n\r\n".encode(),
        json.dumps(payload).encode(), b"\r\n",
    ]
    for i, (name, data) in enumerate(files):
        out += [
            f'--{boundary}\r\nContent-Disposition: form-data; name="files[{i}]"; filename="{name}"\r\n'
            f"Content-Type: text/plain; charset=utf-8\r\n\r\n".encode(),
            data, b"\r\n",
        ]
    out.append(f"--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def discord_request(method, url, payload, files=None):
    """回傳解析後的 JSON（無內容時為 {}）；失敗回傳 None；404 拋出 NotFound"""
    if files:
        body, ctype = _encode_multipart(payload, files)
    else:
        body, ctype = json.dumps(payload).encode(), "application/json"
    for _ in range(5):
        req = urllib.request.Request(
            url, data=body, method=method,
            headers={"Content-Type": ctype, "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw = r.read()
            return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            detail = e.read()
            if e.code == 429:
                try:
                    wait = float(json.loads(detail).get("retry_after", 1))
                except Exception:
                    wait = 2
                time.sleep(wait + 0.1)
                continue
            if e.code == 404:
                raise NotFound()
            log(f"Discord 回傳 HTTP {e.code}：{detail[:300]!r}")
            return None
        except Exception as e:
            log(f"Discord 連線失敗：{e}，5 秒後重試")
            time.sleep(5)
    return None


def base_payload(embed):
    payload = {"username": SERVER_NAME, "embeds": [embed], "allowed_mentions": {"parse": []}}
    if AVATAR_URL:
        payload["avatar_url"] = AVATAR_URL
    return payload


# ===================== 一般通知 =====================
_q = queue.Queue()


def notify(event, title, desc="", color=BLUE, fields=None, attachment=None):
    embed = {"title": title, "color": color, "timestamp": now_iso()}
    if desc:
        embed["description"] = desc
    if fields:
        embed["fields"] = fields
    _q.put((event, embed, attachment))


def build_message(event, embed, attachment):
    payload = base_payload(embed)
    if PING_ROLE_ID and event in PING_EVENTS:
        payload["content"] = f"<@&{PING_ROLE_ID}>"
        payload["allowed_mentions"] = {"parse": [], "roles": [PING_ROLE_ID]}
    if event in SILENT_EVENTS:
        payload["flags"] = FLAG_SILENT
    files = None
    if attachment:
        name, data = attachment
        payload["attachments"] = [{"id": 0, "filename": name}]
        files = [(name, data)]
    return payload, files


def _sender():
    while True:
        event, embed, attachment = _q.get()
        try:
            payload, files = build_message(event, embed, attachment)
            discord_request("POST", WEBHOOK_URL, payload, files)
        except NotFound:
            log("Webhook 不存在（404），請檢查 MC_WEBHOOK_URL")
        except Exception as e:
            log(f"發送通知失敗：{e}")
        finally:
            _q.task_done()


# ===================== Crash report =====================
def resolve_path(p):
    p = p.strip()
    if not os.path.isabs(p):
        p = os.path.join(SERVER_DIR, p)
    return os.path.normpath(p)


def read_crash_report(path):
    """回傳 (原始內容, 描述, 例外摘要, 是否截斷)；讀不到回傳 None"""
    try:
        with open(path, "rb") as f:
            data = f.read(ATTACH_MAX_BYTES + 1)
    except OSError as e:
        log(f"無法讀取 crash report：{e}")
        return None
    truncated = len(data) > ATTACH_MAX_BYTES
    data = data[:ATTACH_MAX_BYTES]
    lines = data.decode("utf-8", "replace").splitlines()
    description, exc_lines = "", []
    for i, line in enumerate(lines):
        if line.startswith("Description:"):
            description = line.split(":", 1)[1].strip()
            for nxt in lines[i + 1:]:
                if not nxt.strip():
                    if exc_lines:
                        break
                    continue
                exc_lines.append(nxt.rstrip())
                if len(exc_lines) >= 6:  # 例外訊息 + 前幾行 stack trace
                    break
            break
    return data, description, "\n".join(exc_lines), truncated


def send_crash(hang, report_path=None):
    with state_lock:
        if state["crash_sent"]:
            return
        state["crash_sent"] = True

    desc = ("Watchdog 偵測到單一 tick 超過 max-tick-time，伺服器被強制關閉"
            if hang else "伺服器發生未處理的例外")
    fields, attachment = [], None
    if report_path:
        path = resolve_path(report_path)
        desc += f"\nCrash report：`{path}`"
        info = read_crash_report(path)
        if info:
            data, description, exception, truncated = info
            if description:
                fields.append({"name": "描述", "value": clip(description, 1024)})
            if exception:
                exception = exception.replace("```", "'''")
                fields.append({"name": "例外", "value": f"```\n{clip(exception, 1000)}\n```"})
            if ATTACH_CRASH_REPORT:
                name = re.sub(r"[^\w.\-]", "_", os.path.basename(path)) or "crash-report.txt"
                attachment = (name, data)
                if truncated:
                    desc += f"\n（檔案超過 {ATTACH_MAX_BYTES / 1048576:.3g} MB，附件只含前段內容）"
    notify("crash", "💥 伺服器崩潰", desc, RED, fields, attachment)


# ===================== Log 追蹤 =====================
# 要求 "]: " 後面直接是玩家名稱，避免有人在聊天打 "xxx joined the game" 造成誤判
JOIN_RE  = re.compile(r"\]: (\w{3,16}) joined the game\s*$")
LEAVE_RE = re.compile(r"\]: (\w{3,16}) left the game\s*$")
BOOT_RE  = re.compile(r"\]: Starting minecraft server version (\S+)")
DONE_RE  = re.compile(r"\]: Done \(([\d.]+)s\)!")
STOP_RE  = re.compile(r"\]: Stopping server\s*$")
CRASH_RE = re.compile(r"This crash report has been saved to:?\s*(.+)$")
HANG_RE  = re.compile(r"Considering it to be crashed")


def handle_line(line):
    if m := JOIN_RE.search(line):
        if NOTIFY_PLAYERS:
            notify("players", f"🟢 {md_escape(m[1])} 加入了伺服器", color=GREEN)

    elif m := LEAVE_RE.search(line):
        if NOTIFY_PLAYERS:
            notify("players", f"⚪ {md_escape(m[1])} 離開了伺服器", color=GREY)

    elif m := BOOT_RE.search(line):
        with state_lock:
            state.update(phase="starting", version=m[1], expected_stop=True,
                         crashed=False, crash_sent=False, started_at=None)

    elif m := DONE_RE.search(line):
        with state_lock:
            state.update(phase="running", expected_stop=False, crashed=False,
                         crash_sent=False, started_at=int(time.time()),
                         boot_gen=state["boot_gen"] + 1)
            version = state["version"]
        desc = f"啟動耗時 {m[1]} 秒" + (f"，版本 {version}" if version else "")
        notify("start", "✅ 伺服器已啟動", desc, GREEN)

    elif STOP_RE.search(line):
        with state_lock:
            crashed = state["crashed"]
            state["expected_stop"] = True
            if not crashed:
                state["phase"] = "stopping"
        if not crashed:  # 崩潰後也會印 Stopping server，不重複通知
            notify("stop", "⏹️ 伺服器正在關閉", color=BLUE)

    elif m := CRASH_RE.search(line):
        with state_lock:
            timer = state["crash_timer"]
            state.update(crashed=True, expected_stop=True, phase="crashed", crash_timer=None)
        if timer:
            timer.cancel()
        send_crash(hang=timer is not None, report_path=m[1])

    elif HANG_RE.search(line):
        with state_lock:
            if state["crashed"]:
                return
            state.update(crashed=True, expected_stop=True, phase="crashed")
            # 先等一下 crash report，等到就一起附上，沒等到就直接發
            timer = threading.Timer(CRASH_REPORT_WAIT, send_crash, kwargs={"hang": True})
            timer.daemon = True
            state["crash_timer"] = timer
        timer.start()


def follow_log():
    f, inode, buf, first = None, None, b"", True
    while True:
        try:
            if f is None:
                f = open(LOG_PATH, "rb")
                inode = os.fstat(f.fileno()).st_ino
                if first:
                    f.seek(0, os.SEEK_END)  # 腳本剛啟動時略過舊內容
                first = False
                buf = b""
            chunk = f.read()
            if chunk:
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    handle_line(ln.decode("utf-8", "replace").rstrip("\r"))
                continue
            st = os.stat(LOG_PATH)
            if st.st_ino != inode or st.st_size < f.tell():
                # 伺服器重啟時 latest.log 會被壓縮並重建 → 重新開啟並從頭讀
                f.close()
                f = None
                continue
        except FileNotFoundError:
            if f:
                f.close()
                f = None
        except Exception as e:
            log(f"讀取 log 發生錯誤：{e}")
        time.sleep(0.5)


# ===================== RCON =====================
class Rcon:
    def __init__(self):
        self.sock = None
        self.rid = 0

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.sock = None

    def _send(self, typ, body):
        self.rid += 1
        data = struct.pack("<ii", self.rid, typ) + body.encode("utf-8") + b"\x00\x00"
        self.sock.sendall(struct.pack("<i", len(data)) + data)

    def _recv_exact(self, n):
        b = b""
        while len(b) < n:
            c = self.sock.recv(n - len(b))
            if not c:
                raise ConnectionError("RCON 連線被關閉")
            b += c
        return b

    def _recv(self):
        (length,) = struct.unpack("<i", self._recv_exact(4))
        data = self._recv_exact(length)
        rid, _typ = struct.unpack("<ii", data[:8])
        return rid, data[8:-2].decode("utf-8", "replace")

    def connect(self):
        self.close()
        self.sock = socket.create_connection((RCON_HOST, RCON_PORT), timeout=10)
        self._send(3, RCON_PASSWORD)
        rid, _ = self._recv()
        if rid == -1:
            self.close()
            raise PermissionError("RCON 密碼錯誤")

    def command(self, cmd):
        # 維持長連線，避免每次連線都在伺服器 log 留下 RCON Client started 訊息
        try:
            if self.sock is None:
                self.connect()
            self._send(2, cmd)
            return self._recv()[1]
        except Exception:
            self.close()
            raise


# ===================== 輸出解析 =====================
COLOR_RE = re.compile(r"§.")
LIST_RE = re.compile(r"There are (\d+)\s*(?:of a max(?: of)?|/)\s*(\d+) players online:?(.*)", re.S)


def parse_tps(text):
    """回傳 (tps, mspt)；無法解析時回傳 None"""
    t = COLOR_RE.sub("", text)
    num = r"(\d+(?:[.,]\d+)?)"  # JVM 語系可能用逗號當小數點

    def f(s):
        return float(s.replace(",", "."))

    i = t.rfind("Overall")
    if i >= 0:  # Forge / NeoForge：取最後一個 Overall，避免被維度名稱干擾
        seg = t[i:]
        m = re.search(r"Mean TPS:\s*" + num, seg) or re.search(num + r"\s*TPS", seg)
        ms = re.search(num + r"\s*ms", seg)
        if m:
            return f(m[1]), (f(ms[1]) if ms else None)
    m = re.search(r"time per tick:\s*" + num + r"\s*ms", t, re.I)  # 原版 /tick query
    if m:
        mspt = f(m[1])
        return (min(20.0, 1000 / mspt) if mspt > 0 else 20.0), mspt
    return None


def parse_list(text):
    """回傳 (線上人數, 上限, [玩家名稱])；無法解析時回傳 None"""
    m = LIST_RE.search(COLOR_RE.sub("", text))
    if not m:
        return None
    names = [n.strip() for n in m[3].replace("\n", ",").split(",") if n.strip()]
    return int(m[1]), int(m[2]), names


# ===================== 狀態看板 =====================
class StatusBoard:
    """持續編輯同一則訊息；訊息 ID 存在 STATE_DIR，重啟後沿用"""

    def __init__(self):
        self.message_id = None
        self.key = hashlib.sha256(WEBHOOK_URL.encode()).hexdigest()[:16]  # 不把 token 寫進檔案
        self.path = os.path.join(STATE_DIR, "status_board.json") if STATE_DIR else None
        self._latest = None
        self._cv = threading.Condition()
        self._send_lock = threading.Lock()
        self._load()

    def _load(self):
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("webhook") == self.key:
                self.message_id = d.get("message_id")
        except FileNotFoundError:
            pass
        except Exception as e:
            log(f"讀取狀態看板紀錄失敗：{e}")

    def _save(self):
        if not self.path:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"webhook": self.key, "message_id": self.message_id}, f)
            os.replace(tmp, self.path)
        except Exception as e:
            log(f"儲存狀態看板紀錄失敗（重啟後會建立新訊息）：{e}")

    def submit(self, embed):
        """只保留最新的一份，Discord 慢的時候不會堆積"""
        with self._cv:
            self._latest = embed
            self._cv.notify()

    def run(self):
        while True:
            with self._cv:
                while self._latest is None:
                    self._cv.wait()
                embed, self._latest = self._latest, None
            self.send_now(embed)

    def send_now(self, embed):
        with self._send_lock:
            try:
                if self.message_id:
                    try:
                        discord_request("PATCH", f"{WEBHOOK_URL}/messages/{self.message_id}",
                                        {"embeds": [embed]})
                        return
                    except NotFound:
                        log("狀態看板訊息已不存在，重新建立")
                        self.message_id = None
                payload = base_payload(embed)
                payload["flags"] = FLAG_SILENT
                r = discord_request("POST", f"{WEBHOOK_URL}?wait=true", payload)
                if r and r.get("id"):
                    self.message_id = r["id"]
                    self._save()
                    log(f"已建立狀態看板訊息 {self.message_id}（可以把它釘選起來）")
            except Exception as e:
                log(f"更新狀態看板失敗：{e}")


def board_status(ok, fail):
    if ok:
        return "🟢 運作中", GREEN
    with state_lock:
        phase = state["phase"]
    if phase == "crashed":
        return "💥 已崩潰", RED
    if phase == "starting":
        return "🟡 啟動中", YELLOW
    if phase == "stopping":
        return "⏹️ 已關閉", GREY
    if fail >= DOWN_COUNT:
        return "🔴 無回應", RED
    return "🟡 連線異常", YELLOW


def board_embed(status, color, players=None, tps=None):
    now = int(time.time())
    with state_lock:
        started_at = state["started_at"]
    fields = []
    if players:
        online, max_players, _ = players
        fields.append({"name": "玩家", "value": f"{online} / {max_players}", "inline": True})
    if tps:
        fields.append({"name": "TPS", "value": f"{tps[0]:.2f}", "inline": True})
        if tps[1] is not None:
            fields.append({"name": "MSPT", "value": f"{tps[1]:.1f} ms", "inline": True})
    if status.startswith("🟢"):
        fields.append({"name": "啟動於",
                       "value": f"<t:{started_at}:R>" if started_at else "—（通知程式啟動前）",
                       "inline": True})
    if players and players[2]:
        names = ", ".join(md_escape(n) for n in players[2])
        fields.append({"name": "線上玩家", "value": clip(names, 1024)})
    embed = {
        "title": f"📊 {SERVER_NAME}",
        "description": f"**{status}**\n最後更新 <t:{now}:R>",
        "color": color,
        "footer": {"text": f"每 {STATUS_INTERVAL} 秒更新"},
        "timestamp": now_iso(),
    }
    if fields:
        embed["fields"] = fields
    return embed


# ===================== 主監控迴圈 =====================
def monitor(board):
    rcon = Rcon()
    low = fail = 0
    low_alerted = down_alerted = parse_warned = False
    last_ok, last_tps = False, None
    boot_gen = 0
    next_poll = next_board = time.monotonic()

    while True:
        now = time.monotonic()

        if now >= next_poll:
            next_poll = now + POLL_INTERVAL
            last_ok = False
            with state_lock:
                gen, expected = state["boot_gen"], state["expected_stop"]
            if gen != boot_gen:
                # 伺服器剛啟動完成，RCON 可能還沒開好 → 從零開始計算
                # 已經發過「已啟動」，就不用再發「恢復回應」
                boot_gen, fail, down_alerted = gen, 0, False
            try:
                out = rcon.command(TPS_COMMAND or "list")
                last_ok = True
                fail = 0
                if down_alerted:
                    notify("up", "✅ 伺服器恢復回應", color=GREEN)
                    down_alerted = False

                if TPS_COMMAND:
                    r = parse_tps(out)
                    if r is None:
                        if not parse_warned:
                            log(f"無法解析 TPS 指令輸出，請檢查 MC_TPS_COMMAND：{out!r}")
                            parse_warned = True
                    else:
                        last_tps = r
                        tps, mspt = r
                        mspt_txt = f"{mspt:.1f} ms" if mspt is not None else "—"
                        if tps < TPS_THRESHOLD:
                            low += 1
                            if low >= LOW_TPS_COUNT and not low_alerted:
                                duration = fmt_duration(LOW_TPS_COUNT * POLL_INTERVAL)
                                notify("tps_low", "🐢 TPS 持續過低",
                                       f"已連續低於門檻 {TPS_THRESHOLD:g}，可以用 `/spark profiler` 找原因",
                                       ORANGE, [
                                           {"name": "TPS", "value": f"{tps:.2f}", "inline": True},
                                           {"name": "MSPT", "value": mspt_txt, "inline": True},
                                           {"name": "持續", "value": f"約 {duration}", "inline": True},
                                       ])
                                low_alerted = True
                        else:
                            if low_alerted:
                                notify("tps_ok", "👍 TPS 已恢復", color=GREEN, fields=[
                                    {"name": "TPS", "value": f"{tps:.2f}", "inline": True},
                                    {"name": "MSPT", "value": mspt_txt, "inline": True},
                                ])
                            low = 0
                            low_alerted = False

            except PermissionError as e:
                log(f"{e}，請檢查 MC_RCON_PASSWORD")
            except Exception as e:
                fail += 1
                low = 0
                low_alerted = False
                last_tps = None
                if expected:
                    if fail == DOWN_COUNT:
                        log(f"RCON 無法連線（預期中的關閉或已通報崩潰）：{e}")
                elif fail >= DOWN_COUNT and not down_alerted:
                    notify("down", "🔴 伺服器無回應",
                           f"RCON 已連續 {fail} 次失敗，伺服器可能已崩潰、卡死或被強制結束",
                           RED, [{"name": "錯誤", "value": clip(f"`{e}`", 1024)}])
                    down_alerted = True

        if board and now >= next_board:
            next_board = now + STATUS_INTERVAL
            ok, players = last_ok, None
            if ok:
                try:
                    players = parse_list(rcon.command("list"))
                except Exception:
                    ok = False
            status, color = board_status(ok, fail)
            board.submit(board_embed(status, color, players, last_tps if ok else None))

        wake = min(next_poll, next_board) if board else next_poll
        time.sleep(max(0.5, wake - time.monotonic()))


# ===================== 啟動 =====================
def validate():
    errors = []
    if not WEBHOOK_URL.startswith("https://"):
        errors.append("MC_WEBHOOK_URL 未設定或格式錯誤")
    if not RCON_PASSWORD:
        errors.append("MC_RCON_PASSWORD 未設定")
    if PING_ROLE_ID and not PING_ROLE_ID.isdigit():
        errors.append("MC_PING_ROLE_ID 必須是純數字的身分組 ID")
    if errors:
        raise SystemExit("設定錯誤：\n  " + "\n  ".join(errors))

    for name, s in (("MC_PING_EVENTS", PING_EVENTS), ("MC_SILENT_EVENTS", SILENT_EVENTS)):
        if s - EVENTS:
            log(f"警告：{name} 有未知的事件名稱 {sorted(s - EVENTS)}，可用：{sorted(EVENTS)}")
    if PING_ROLE_ID and PING_EVENTS & SILENT_EVENTS:
        log(f"警告：{sorted(PING_EVENTS & SILENT_EVENTS)} 同時設為 ping 與靜音，"
            f"身分組會被標記但不會收到推播")
    if STATUS_BOARD and not STATE_DIR:
        log("警告：未設定 MC_STATE_DIR，狀態看板在每次重啟後都會建立新訊息")


def main():
    validate()

    def _on_term(signum, frame):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, _on_term)

    threading.Thread(target=_sender, daemon=True).start()
    threading.Thread(target=follow_log, daemon=True).start()
    board = None
    if STATUS_BOARD:
        board = StatusBoard()
        threading.Thread(target=board.run, daemon=True).start()

    tps_desc = repr(TPS_COMMAND) if TPS_COMMAND else "停用（只檢查存活）"
    log(f"mc-notify {__version__} 已啟動：log={LOG_PATH}，RCON={RCON_HOST}:{RCON_PORT}，TPS 指令={tps_desc}")
    log(f"玩家進出通知={'開' if NOTIFY_PLAYERS else '關'}，"
        f"ping 身分組={PING_ROLE_ID or '無'}（事件 {sorted(PING_EVENTS)}），"
        f"靜音事件={sorted(SILENT_EVENTS)}，"
        f"附加 crash report={'開' if ATTACH_CRASH_REPORT else '關'}，"
        f"狀態看板={'開，每 %d 秒' % STATUS_INTERVAL if STATUS_BOARD else '關'}")

    try:
        monitor(board)
    finally:
        # 收到 SIGTERM：盡量把還沒送出的通知送完，並把看板標示為停止
        deadline = time.monotonic() + 5
        while _q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.1)
        if board:
            board.send_now(board_embed("⚫ 監控程式已停止", GREY))
        log("已停止")


def run_check(send_test=False):
    """檢查設定與環境，回傳 exit code"""
    problems = 0

    def result(status, msg):
        nonlocal problems
        if status == "fail":
            problems += 1
        print({"ok": "✅", "warn": "⚠️ ", "fail": "❌"}[status], msg, flush=True)

    print(f"mc-notify {__version__} 設定檢查（{SERVER_NAME}）")
    try:
        validate()
        result("ok", "必要設定齊全")
    except SystemExit as e:
        result("fail", str(e))
        return 1

    # log 檔
    if os.access(LOG_PATH, os.R_OK):
        result("ok", f"可以讀取 log：{LOG_PATH}")
    elif os.path.exists(LOG_PATH):
        result("fail", f"log 存在但沒有讀取權限：{LOG_PATH}")
    else:
        result("fail", f"找不到 log，或上層目錄沒有進入權限：{LOG_PATH}")

    # crash-reports
    crash_dir = os.path.join(SERVER_DIR, "crash-reports")
    if not os.access(SERVER_DIR, os.X_OK):
        result("fail" if ATTACH_CRASH_REPORT else "warn",
               f"無法進入伺服器目錄（權限不足或路徑錯誤）：{SERVER_DIR}")
    elif os.path.isdir(crash_dir):
        if os.access(crash_dir, os.R_OK | os.X_OK):
            result("ok", f"可以讀取 crash report 目錄：{crash_dir}")
        else:
            result("fail" if ATTACH_CRASH_REPORT else "warn",
                   f"沒有 crash report 目錄的讀取權限：{crash_dir}")
    else:
        result("warn", f"crash report 目錄尚未存在（伺服器沒崩潰過就不會有）：{crash_dir}")

    # 狀態看板
    if STATUS_BOARD:
        if not STATE_DIR:
            result("warn", "狀態看板已開啟但沒有 STATE_DIR，重啟後會建立新訊息")
        elif os.access(STATE_DIR, os.W_OK):
            result("ok", f"狀態看板紀錄目錄可寫入：{STATE_DIR}")
        else:
            result("fail", f"狀態看板紀錄目錄無法寫入：{STATE_DIR}")

    # RCON
    rcon = Rcon()
    try:
        out = rcon.command(TPS_COMMAND or "list")
        result("ok", f"RCON 連線成功：{RCON_HOST}:{RCON_PORT}")
        if TPS_COMMAND:
            r = parse_tps(out)
            if r:
                mspt = f"，MSPT {r[1]:.1f} ms" if r[1] is not None else ""
                result("ok", f"TPS 指令 {TPS_COMMAND!r} 解析成功：TPS {r[0]:.2f}{mspt}")
            else:
                result("fail", f"無法解析 {TPS_COMMAND!r} 的輸出：{out[:300]!r}")
        else:
            result("warn", "MC_TPS_COMMAND 為空，只會檢查存活，不監控 TPS")
        players = parse_list(rcon.command("list"))
        if players:
            result("ok", f"玩家清單解析成功：{players[0]} / {players[1]}")
        else:
            result("warn", "無法解析 list 指令的輸出，狀態看板不會顯示玩家")
    except PermissionError as e:
        result("fail", str(e))
    except Exception as e:
        result("fail", f"RCON 無法連線（伺服器沒開，或 enable-rcon / rcon.port 設定不符）：{e}")
    finally:
        rcon.close()

    # Discord
    if send_test:
        embed = {"title": "🧪 mc-notify 測試訊息", "color": BLUE, "timestamp": now_iso(),
                 "description": "看到這則訊息代表 webhook 設定正確"}
        try:
            r = discord_request("POST", WEBHOOK_URL, base_payload(embed))
            if r is None:
                result("fail", "Discord 拒絕了測試訊息，請看上方的錯誤")
            else:
                result("ok", "已發送測試訊息到 Discord")
        except NotFound:
            result("fail", "Webhook 不存在（404），請檢查 MC_WEBHOOK_URL")

    print("檢查完成：" + ("全部通過" if problems == 0 else f"{problems} 個問題"))
    return 0 if problems == 0 else 1


def cli(argv=None):
    ap = argparse.ArgumentParser(description="Minecraft 伺服器 Discord Webhook 通知")
    ap.add_argument("--check", action="store_true", help="檢查設定、檔案權限與 RCON 連線")
    ap.add_argument("--send-test", action="store_true", help="檢查並發送一則測試訊息")
    ap.add_argument("--version", action="version", version=f"mc-notify {__version__}")
    args = ap.parse_args(argv)
    if args.check or args.send_test:
        raise SystemExit(run_check(send_test=args.send_test))
    main()


if __name__ == "__main__":
    cli()
