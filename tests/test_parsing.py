"""解析與事件判斷的單元測試（不需要網路，幾秒內跑完）

執行：python3 -m unittest discover -s tests -v
"""
import os
import tempfile
import time
import unittest

from helpers import Recorder, load

# 實際 Forge 1.20.1 伺服器的 forge tps 輸出（透過 RCON 時各行會直接串接）
FORGE_TPS = (
    "Dim minecraft:overworld (minecraft:overworld): Mean tick time: 57.739 ms. Mean TPS: 17.319"
    "Dim twilightforest:twilight_forest (twilightforest:twilight_forest_type): Mean tick time: 0.029 ms. Mean TPS: 20.000"
    "Dim ae2:spatial_storage (ae2:spatial_storage): Mean tick time: 0.005 ms. Mean TPS: 20.000"
    "Overall: Mean tick time: 61.063 ms. Mean TPS: 16.376"
)
NEOFORGE_TPS = "Overall: 18.500 TPS (54.054 ms/tick)minecraft:overworld: 20.000 TPS (1.0 ms/tick)"
VANILLA_TICK_QUERY = (
    "The game is running, but can't keep up with the target tick rate"
    "Target tick rate: 20.0 per second.\nAverage time per tick: 62.3ms (Target: 50.0ms)"
    "Percentiles: P50: 55.1ms P95: 80.2ms P99: 95.0ms, sample: 100"
)

FORGE_PREFIX = "[15Sep2026 10:00:00.000] [Server thread/INFO] [minecraft/MinecraftServer]: "
VANILLA_PREFIX = "[10:00:00] [Server thread/INFO]: "


class TestParseTps(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_forge_concatenated(self):
        self.assertEqual(self.m.parse_tps(FORGE_TPS), (16.376, 61.063))

    def test_forge_with_newlines(self):
        text = FORGE_TPS.replace("Dim ", "\nDim ").replace("Overall", "\nOverall")
        self.assertEqual(self.m.parse_tps(text), (16.376, 61.063))

    def test_forge_comma_decimal(self):
        text = FORGE_TPS.replace("61.063", "61,063").replace("16.376", "16,376")
        self.assertEqual(self.m.parse_tps(text), (16.376, 61.063))

    def test_color_codes(self):
        self.assertEqual(self.m.parse_tps("§6Overall§r: Mean tick time: §a1.000§r ms. Mean TPS: §a20.000"),
                         (20.0, 1.0))

    def test_neoforge(self):
        self.assertEqual(self.m.parse_tps(NEOFORGE_TPS), (18.5, 54.054))

    def test_vanilla_tick_query(self):
        tps, mspt = self.m.parse_tps(VANILLA_TICK_QUERY)
        self.assertAlmostEqual(tps, 1000 / 62.3)
        self.assertEqual(mspt, 62.3)

    def test_vanilla_capped_at_20(self):
        tps, _ = self.m.parse_tps("Average time per tick: 3.0ms (Target: 50.0ms)")
        self.assertEqual(tps, 20.0)

    def test_unparsable(self):
        self.assertIsNone(self.m.parse_tps("Unknown or incomplete command"))


class TestParseList(unittest.TestCase):
    def setUp(self):
        self.m = load()

    def test_modern(self):
        self.assertEqual(self.m.parse_list("There are 2 of a max of 20 players online: Steve, cool_guy"),
                         (2, 20, ["Steve", "cool_guy"]))

    def test_empty(self):
        self.assertEqual(self.m.parse_list("There are 0 of a max of 20 players online: "), (0, 20, []))

    def test_old_format(self):
        self.assertEqual(self.m.parse_list("There are 1/20 players online:\nAlex"), (1, 20, ["Alex"]))


class TestLogEvents(unittest.TestCase):
    def setUp(self):
        self.m = load()
        self.rec = Recorder(self.m)

    def feed(self, *lines, prefix=FORGE_PREFIX):
        for line in lines:
            self.m.handle_line(prefix + line)

    def test_join_leave(self):
        self.feed("Steve joined the game", "cool_guy left the game")
        self.assertEqual(self.rec.events, ["players", "players"])
        self.assertIn("cool\\_guy", self.rec.calls[1]["title"])  # Markdown 跳脫

    def test_vanilla_format(self):
        self.feed("Alex joined the game", prefix=VANILLA_PREFIX)
        self.assertEqual(self.rec.events, ["players"])

    def test_chat_spoof_ignored(self):
        self.feed("<Steve> Bob joined the game", "[Server] Bob left the game")
        self.assertEqual(self.rec.calls, [])

    def test_players_disabled(self):
        m = load(MC_NOTIFY_PLAYERS="false")
        rec = Recorder(m)
        m.handle_line(FORGE_PREFIX + "Steve joined the game")
        self.assertEqual(rec.calls, [])

    def test_spark_and_tps_lines_ignored(self):
        self.feed("Overall: Mean tick time: 61.063 ms. Mean TPS: 16.376",
                  "[⚡] Tick #1753 lasted 63.22 ms. (4.15% increase from avg)")
        self.assertEqual(self.rec.calls, [])

    def test_boot_sequence(self):
        self.feed("Starting minecraft server version 1.20.1", 'Done (10.123s)! For help, type "help"')
        self.assertEqual(self.rec.events, ["start"])
        self.assertIn("1.20.1", self.rec.calls[0]["desc"])
        self.assertEqual(self.m.state["phase"], "running")
        self.assertFalse(self.m.state["expected_stop"])

    def test_normal_stop(self):
        self.feed("Stopping server")
        self.assertEqual(self.rec.events, ["stop"])
        self.assertTrue(self.m.state["expected_stop"])

    def test_crash_then_stop_is_one_message(self):
        self.feed("This crash report has been saved to: /nonexistent/crash.txt", "Stopping server")
        self.assertEqual(self.rec.events, ["crash"])
        self.assertEqual(self.m.state["phase"], "crashed")

    def test_hang_without_report(self):
        self.m.CRASH_REPORT_WAIT = 0.2
        self.feed("Considering it to be crashed, server will forcibly shutdown.")
        self.assertEqual(self.rec.calls, [])  # 先等 crash report
        time.sleep(0.5)
        self.assertEqual(self.rec.events, ["crash"])
        self.assertIsNone(self.rec.calls[0]["attachment"])

    def test_hang_with_report_is_merged(self):
        self.m.CRASH_REPORT_WAIT = 5
        self.feed("Considering it to be crashed, server will forcibly shutdown.",
                  "This crash report has been saved to: /nonexistent/crash.txt")
        time.sleep(0.2)
        self.assertEqual(self.rec.events, ["crash"])
        self.assertIn("Watchdog", self.rec.calls[0]["desc"])

    def test_new_boot_resets_crash(self):
        self.feed("This crash report has been saved to: /x", "Starting minecraft server version 1.20.1",
                  'Done (1.0s)! For help, type "help"', "This crash report has been saved to: /y")
        self.assertEqual(self.rec.events, ["crash", "start", "crash"])


class TestCrashReport(unittest.TestCase):
    REPORT = (
        "---- Minecraft Crash Report ----\n// Oops.\n\nTime: 2026-09-15 10:00:00\n"
        "Description: Exception in server tick loop\n\n"
        'java.lang.NullPointerException: Cannot invoke "Foo.bar()"\n'
        "\tat com.example.mod.Thing.tick(Thing.java:42)\n\n"
        "A detailed walkthrough of the error...\n" + "x" * 3000
    )

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "logs"))
        os.makedirs(os.path.join(self.dir, "crash-reports"))
        with open(os.path.join(self.dir, "crash-reports", "crash-1.txt"), "w") as f:
            f.write(self.REPORT)

    def crash(self, **env):
        m = load(MC_LOG_PATH=os.path.join(self.dir, "logs", "latest.log"), **env)
        rec = Recorder(m)
        m.handle_line(FORGE_PREFIX + "This crash report has been saved to: ./crash-reports/crash-1.txt")
        return rec.calls[0]

    def test_fields_and_attachment(self):
        call = self.crash()
        fields = {f["name"]: f["value"] for f in call["fields"]}
        self.assertEqual(fields["描述"], "Exception in server tick loop")
        self.assertIn("NullPointerException", fields["例外"])
        self.assertIn("Thing.java:42", fields["例外"])
        self.assertEqual(call["attachment"][0], "crash-1.txt")
        self.assertEqual(len(call["attachment"][1]), len(self.REPORT))

    def test_truncated(self):
        call = self.crash(MC_ATTACH_MAX_MB="0.001")
        self.assertEqual(len(call["attachment"][1]), int(0.001 * 1024 * 1024))
        self.assertIn("前段", call["desc"])

    def test_attachment_disabled(self):
        call = self.crash(MC_ATTACH_CRASH_REPORT="false")
        self.assertIsNone(call["attachment"])
        self.assertTrue(call["fields"])  # 摘要仍然會顯示


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        m = load(STATE_DIRECTORY="/var/lib/mc-notify/modpack")
        self.assertEqual(m.TPS_COMMAND, "forge tps")
        self.assertEqual(m.PING_EVENTS, {"crash", "down"})
        self.assertEqual(m.SILENT_EVENTS, {"players"})
        self.assertEqual(m.STATE_DIR, "/var/lib/mc-notify/modpack")
        self.assertFalse(m.STATUS_BOARD)
        self.assertTrue(m.NOTIFY_PLAYERS)

    def test_empty_list_means_none(self):
        m = load(MC_SILENT_EVENTS="", MC_TPS_COMMAND="")
        self.assertEqual(m.SILENT_EVENTS, set())
        self.assertEqual(m.TPS_COMMAND, "")

    def test_list_normalized(self):
        m = load(MC_PING_EVENTS=" Crash , TPS_LOW ,")
        self.assertEqual(m.PING_EVENTS, {"crash", "tps_low"})

    def test_bool_values(self):
        for value, expected in [("1", True), ("on", True), ("YES", True), ("0", False), ("off", False)]:
            self.assertEqual(load(MC_STATUS_BOARD=value).STATUS_BOARD, expected, value)

    def test_minimums(self):
        m = load(MC_POLL_INTERVAL="1", MC_STATUS_INTERVAL="1")
        self.assertEqual((m.POLL_INTERVAL, m.STATUS_INTERVAL), (5, 10))

    def test_webhook_query_stripped(self):
        m = load(MC_WEBHOOK_URL="https://discord.com/api/webhooks/1/abc/?wait=true")
        self.assertEqual(m.WEBHOOK_URL, "https://discord.com/api/webhooks/1/abc")

    def test_validate_errors(self):
        m = load(MC_WEBHOOK_URL="http://x", MC_PING_ROLE_ID="abc")
        with self.assertRaises(SystemExit) as cm:
            m.validate()
        msg = str(cm.exception)
        self.assertIn("MC_WEBHOOK_URL", msg)
        self.assertIn("MC_RCON_PASSWORD", msg)
        self.assertIn("MC_PING_ROLE_ID", msg)


class TestBuildMessage(unittest.TestCase):
    def test_ping_and_silent(self):
        m = load(MC_PING_ROLE_ID="123", MC_AVATAR_URL="https://example.com/a.png", MC_SERVER_NAME="測試服")
        p, files = m.build_message("crash", {"title": "x"}, ("c.txt", b"data"))
        self.assertEqual(p["content"], "<@&123>")
        self.assertEqual(p["allowed_mentions"], {"parse": [], "roles": ["123"]})
        self.assertEqual(p["avatar_url"], "https://example.com/a.png")
        self.assertEqual(p["username"], "測試服")
        self.assertEqual(p["attachments"], [{"id": 0, "filename": "c.txt"}])
        self.assertEqual(files, [("c.txt", b"data")])
        self.assertNotIn("flags", p)

        p, files = m.build_message("players", {"title": "x"}, None)
        self.assertEqual(p["flags"], 1 << 12)
        self.assertNotIn("content", p)
        self.assertEqual(p["allowed_mentions"], {"parse": []})
        self.assertIsNone(files)

    def test_no_role_no_ping(self):
        m = load()
        p, _ = m.build_message("crash", {"title": "x"}, None)
        self.assertNotIn("content", p)
        self.assertNotIn("avatar_url", p)


if __name__ == "__main__":
    unittest.main()
