"""完整流程測試：啟動假的 Discord 與假的 RCON 伺服器，實際執行 mc_notify.py

約需 70 秒，預設略過。執行方式：
  MC_NOTIFY_INTEGRATION=1 python3 -m unittest discover -s tests -v
"""
import http.server
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREFIX = "[15Sep2026 10:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: "


class FakeDiscord:
    """記錄收到的請求；第一個請求回 429 以測試限流處理；/messages/404 回 404"""

    def __init__(self):
        self.requests = []
        self.rate_limited = False
        self.next_id = 1000
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _handle(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                if not outer.rate_limited:
                    outer.rate_limited = True
                    self._reply(429, {"retry_after": 0.2})
                    return
                if self.headers["Content-Type"].startswith("multipart"):
                    part = body.split(b'name="payload_json"')[1].split(b"\r\n\r\n", 1)[1]
                    payload = json.loads(part.split(b"\r\n--")[0])
                    filename = body.split(b'filename="')[1].split(b'"')[0].decode()
                else:
                    payload, filename = json.loads(body), None
                outer.requests.append({"method": self.command, "path": self.path,
                                       "payload": payload, "file": filename})
                if self.command == "PATCH" and "/messages/404" in self.path:
                    self._reply(404, {"message": "Unknown Message"})
                elif "wait=true" in self.path:
                    outer.next_id += 1
                    self._reply(200, {"id": str(outer.next_id)})
                else:
                    self.send_response(204)
                    self.end_headers()

            def _reply(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_POST = do_PATCH = _handle

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    # 輔助查詢
    def messages(self):
        return [r for r in self.requests if r["method"] == "POST" and "wait=true" not in r["path"]]

    def titles(self):
        return [r["payload"]["embeds"][0]["title"] for r in self.messages()]

    def board_updates(self):
        return [r for r in self.requests if r["method"] == "PATCH" or "wait=true" in r["path"]]

    def board_statuses(self):
        return [r["payload"]["embeds"][0]["description"].split("\n")[0] for r in self.board_updates()]


class FakeRcon:
    def __init__(self):
        self.up = True
        self.tps, self.mspt = "20.000", "10.000"
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            conn, _ = self.sock.accept()
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, c):
        def recv(n):
            b = b""
            while len(b) < n:
                chunk = c.recv(n - len(b))
                if not chunk:
                    raise ConnectionError
                b += chunk
            return b

        def send(rid, typ, text):
            d = struct.pack("<ii", rid, typ) + text.encode() + b"\0\0"
            c.sendall(struct.pack("<i", len(d)) + d)

        try:
            while True:
                n = struct.unpack("<i", recv(4))[0]
                d = recv(n)
                rid, typ = struct.unpack("<ii", d[:8])
                body = d[8:-2].decode()
                if not self.up:
                    c.close()
                    return
                if typ == 3:
                    send(rid if body == "secret" else -1, 2, "")
                elif body == "forge tps":
                    send(rid, 0, "Dim minecraft:overworld (minecraft:overworld): Mean tick time: 1.0 ms. "
                                 f"Mean TPS: 20.000Overall: Mean tick time: {self.mspt} ms. Mean TPS: {self.tps}")
                elif body == "list":
                    send(rid, 0, "There are 2 of a max of 20 players online: Steve, cool_guy")
                else:
                    send(rid, 0, "Unknown command")
        except Exception:
            c.close()


@unittest.skipUnless(os.environ.get("MC_NOTIFY_INTEGRATION"), "設定 MC_NOTIFY_INTEGRATION=1 才執行")
class TestIntegration(unittest.TestCase):
    def setUp(self):
        self.discord = FakeDiscord()
        self.rcon = FakeRcon()
        self.dir = tempfile.mkdtemp()
        for sub in ("logs", "crash-reports", "state"):
            os.makedirs(os.path.join(self.dir, sub))
        self.log = os.path.join(self.dir, "logs", "latest.log")
        open(self.log, "w").close()
        self.crash = os.path.join(self.dir, "crash-reports", "crash-2026-09-15_10.00.00-server.txt")
        with open(self.crash, "w") as f:
            f.write("---- Minecraft Crash Report ----\nDescription: Exception in server tick loop\n\n"
                    "java.lang.NullPointerException: boom\n\tat com.example.Thing.tick(Thing.java:42)\n")
        self.env = dict(
            os.environ,
            MC_WEBHOOK_URL="https://placeholder/api/webhooks/1/tok",
            MC_RCON_PORT=str(self.rcon.port), MC_RCON_PASSWORD="secret", MC_LOG_PATH=self.log,
            MC_POLL_INTERVAL="5", MC_LOW_TPS_COUNT="2", MC_DOWN_COUNT="2",
            MC_STATUS_BOARD="true", MC_STATUS_INTERVAL="10",
            MC_STATE_DIR=os.path.join(self.dir, "state"),
            MC_PING_ROLE_ID="123456", MC_AVATAR_URL="https://example.com/a.png",
            MC_SERVER_NAME="測試服",
        )

    def start(self, *args, validate=False):
        # 假 Discord 只有 http，所以用程式碼替換掉 webhook 網址並略過 https 檢查
        code = (f"import sys; sys.path.insert(0, {ROOT!r}); import mc_notify as m; "
                f"m.WEBHOOK_URL = 'http://127.0.0.1:{self.discord.port}/api/webhooks/1/tok'; ")
        if not validate:
            code += "m.validate = lambda: None; "
        code += f"m.cli({list(args)!r})"
        return subprocess.Popen([sys.executable, "-c", code], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def write(self, *lines):
        with open(self.log, "a") as f:
            for line in lines:
                f.write(PREFIX + line + "\n")

    def stop(self, proc):
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=20)
        return out

    def test_full_lifecycle(self):
        d, r = self.discord, self.rcon
        proc = self.start()
        time.sleep(2)
        self.write("Starting minecraft server version 1.20.1", 'Done (10.123s)! For help, type "help"',
                   "Steve joined the game", "<Steve> Bob joined the game", "cool_guy left the game")
        r.tps, r.mspt = "16.000", "62.500"
        time.sleep(11)
        r.tps, r.mspt = "20.000", "10.000"
        time.sleep(6)
        self.write("Considering it to be crashed, server will forcibly shutdown.")
        time.sleep(1)
        self.write(f"This crash report has been saved to: {self.crash}", "Stopping server")
        r.up = False
        time.sleep(12)
        self.write("Starting minecraft server version 1.20.1")
        time.sleep(1)
        self.write('Done (9.0s)! For help, type "help"')
        r.up = True
        time.sleep(6)
        r.up = False  # 無預警消失
        time.sleep(12)
        r.up = True
        time.sleep(6)
        out = self.stop(proc)

        self.assertEqual(d.titles(), [
            "✅ 伺服器已啟動", "🟢 Steve 加入了伺服器", "⚪ cool\\_guy 離開了伺服器",
            "🐢 TPS 持續過低", "👍 TPS 已恢復", "💥 伺服器崩潰",
            "✅ 伺服器已啟動", "🔴 伺服器無回應", "✅ 伺服器恢復回應",
        ], out)

        by_title = {m["payload"]["embeds"][0]["title"]: m for m in d.messages()}
        # 靜音與 ping
        self.assertEqual(by_title["🟢 Steve 加入了伺服器"]["payload"].get("flags"), 4096)
        self.assertEqual(by_title["💥 伺服器崩潰"]["payload"]["content"], "<@&123456>")
        self.assertEqual(by_title["🔴 伺服器無回應"]["payload"]["content"], "<@&123456>")
        self.assertNotIn("content", by_title["✅ 伺服器已啟動"]["payload"])
        # 崩潰：合併 watchdog 與 crash report，附上檔案
        crash = by_title["💥 伺服器崩潰"]
        self.assertIn("Watchdog", crash["payload"]["embeds"][0]["description"])
        self.assertEqual(crash["file"], os.path.basename(self.crash))
        # 外觀
        self.assertEqual(crash["payload"]["username"], "測試服")
        self.assertEqual(crash["payload"]["avatar_url"], "https://example.com/a.png")

        # 狀態看板：只建立一次，之後都是編輯；最後標示停止
        boards = d.board_updates()
        self.assertEqual(sum(1 for b in boards if b["method"] == "POST"), 1)
        self.assertEqual(boards[0]["payload"]["flags"], 4096)
        self.assertNotIn("username", boards[1]["payload"])  # 編輯時不能帶 username
        statuses = d.board_statuses()
        self.assertEqual(statuses[0], "**🟢 運作中**")
        self.assertIn("**💥 已崩潰**", statuses)
        self.assertIn("**🔴 無回應**", statuses)
        self.assertEqual(statuses[-1], "**⚫ 監控程式已停止**")
        fields = {f["name"]: f["value"] for f in boards[0]["payload"]["embeds"][0]["fields"]}
        self.assertEqual(fields["玩家"], "2 / 20")
        self.assertIn("cool\\_guy", fields["線上玩家"])

        # 重啟後沿用同一則看板
        with open(os.path.join(self.dir, "state", "status_board.json")) as f:
            saved = json.load(f)
        self.assertEqual(saved["message_id"], "1001")
        self.assertNotIn("tok", json.dumps(saved))  # 不儲存 token
        n = len(d.requests)
        self.stop(self._started_and_waited())
        self.assertTrue(all(x["method"] == "PATCH" and x["path"].endswith("/messages/1001")
                            for x in d.requests[n:]))

        # 看板被刪除：PATCH 404 → 重新建立
        saved["message_id"] = "404"
        with open(os.path.join(self.dir, "state", "status_board.json"), "w") as f:
            json.dump(saved, f)
        n = len(d.requests)
        self.stop(self._started_and_waited())
        methods = [(x["method"], "wait=true" in x["path"]) for x in d.requests[n:]]
        self.assertEqual(methods[:2], [("PATCH", False), ("POST", True)])

    def _started_and_waited(self):
        proc = self.start()
        time.sleep(3)
        return proc

    def test_check_mode(self):
        proc = self.start("--send-test", validate=True)
        out, _ = proc.communicate(timeout=30)
        # 假 Discord 是 http，validate 會失敗 → 確認錯誤有被列出
        self.assertEqual(proc.returncode, 1)
        self.assertIn("MC_WEBHOOK_URL", out)

        proc = self.start("--send-test")
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 0, out)
        self.assertIn("TPS 20.00", out)
        self.assertIn("2 / 20", out)
        self.assertEqual(self.discord.titles(), ["🧪 mc-notify 測試訊息"])

        self.env["MC_RCON_PASSWORD"] = "wrong"
        proc = self.start("--check")
        out, _ = proc.communicate(timeout=30)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("RCON 密碼錯誤", out)


if __name__ == "__main__":
    unittest.main()
