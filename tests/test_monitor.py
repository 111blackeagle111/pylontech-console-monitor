"""Test con output reali (anonimizzati) della console di un banco di 4 Pylontech US2000C.

Uso:  python3 -m unittest discover -s tests
"""
import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request
from datetime import datetime, timedelta

os.environ["PYLON_DATA"] = tempfile.mkdtemp(prefix="pylon-test-")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pylon_monitor as pm  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), newline="") as fh:
        return fh.read()


class FakeSerial:
    """Porta seriale finta: restituisce i dati preparati e risponde con il prompt a ogni invio."""

    def __init__(self, data):
        self.data, self.sent = data, b""

    def reset_input_buffer(self):
        pass

    def write(self, b):
        self.sent += b
        self.data += b"\r\npylon>"

    @property
    def in_waiting(self):
        return len(self.data)

    def read(self, n):
        out, self.data = self.data[:n], self.data[n:]
        return out


def bank():
    mods = pm.parse_pwr(fixture("pwr.txt"))
    for m in mods:
        n = 2 if m["id"] == 2 else 1  # celle reali dei moduli 1 e 2
        rows = pm.parse_table(fixture(f"bat_{n}.txt"), 12)
        soh = {int(r[0]): r[3] for r in pm.parse_table(fixture(f"soh_{n}.txt"), 4)}
        m["cells"] = [{"n": int(r[0]), "v": int(r[1]), "t": int(r[3]) / 1000, "bal": r[-1] == "Y", "soh": soh[int(r[0])]}
                      for r in rows]
    return mods


class ParsingTest(unittest.TestCase):
    def test_pwr_summary(self):
        mods = pm.parse_pwr(fixture("pwr.txt"))
        self.assertEqual([m["id"] for m in mods], [1, 2, 3, 4])
        self.assertEqual([m["soc"] for m in mods], [76, 15, 72, 76])
        m2 = mods[1]
        self.assertEqual((m2["vlow"], m2["vhigh"]), (3233, 3318))
        self.assertAlmostEqual(m2["curr"], -1.405)
        self.assertEqual(m2["base"], "Dischg")
        self.assertIn("clock", m2)
        self.assertIn("mos_temp", m2)

    def test_cells_and_health(self):
        rows = pm.parse_table(fixture("bat_2.txt"), 12)
        self.assertEqual(len(rows), 15)
        self.assertEqual(min(rows, key=lambda r: int(r[1]))[0], "1")  # la cella 1 è la più bassa
        soh2 = {int(r[0]): r[3] for r in pm.parse_table(fixture("soh_2.txt"), 4)}
        soh1 = {int(r[0]): r[3] for r in pm.parse_table(fixture("soh_1.txt"), 4)}
        self.assertEqual([n for n, s in soh2.items() if s == "Abnormal"], [1])
        self.assertNotIn("Abnormal", soh1.values())

    def test_key_value_commands(self):
        stat = pm.parse_kv(fixture("stat_2.txt"))
        info = pm.parse_kv(fixture("info_2.txt"))
        pwr = pm.parse_kv(fixture("pwr_2.txt"))
        self.assertEqual(stat["CYCLE Times"], "1254")
        self.assertEqual(stat["Bat OV Times"], "1198")
        self.assertEqual(info["Device name"], "US2000C")
        self.assertEqual(info["Barcode"], "H0000000000000000")
        self.assertEqual(pwr["Soh. Status"], "Abnormal")
        self.assertEqual(pwr["Total Coulomb"], "50000 mAH")

    def test_event_log_paging(self):
        s = FakeSerial(("log\r\n" + fixture("log.txt")).encode())
        entries = pm.read_log(s)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["index"], "31")
        self.assertEqual(entries[0]["info"], "The device start discharging.")
        self.assertTrue(s.sent.startswith(b"log\r"))


class StorageTest(unittest.TestCase):
    def test_history_and_daily_stats(self):
        mods = bank()
        start = datetime.now() - timedelta(hours=2)
        for i in range(10):
            pm.append_log((start + timedelta(minutes=10 * i)).isoformat(timespec="seconds"), mods)
        h = pm.history(24)
        self.assertEqual(sorted(h["series"]), [1, 2, 3, 4])
        soc2 = [p[1] for p in h["series"][2]]
        self.assertTrue(all(v == 15 for v in soc2))
        self.assertTrue(all(p[1] < 0 for p in h["total"]))  # banco in scarica

        stat = pm.parse_kv(fixture("stat_2.txt"))
        pm.append_stats((datetime.now() - timedelta(days=3)).isoformat(timespec="seconds"),
                        {2: {"stat": dict(stat, **{"Bat OV Times": "1100"})}})
        pm.append_stats(datetime.now().isoformat(timespec="seconds"), {2: {"stat": stat}})
        days = pm.stats_history(8)["2"]
        self.assertEqual(len(days), 2)
        self.assertEqual((days[0][1]["Bat OV Times"], days[-1][1]["Bat OV Times"]), ("1100", "1198"))


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pm.latest.update(ts=datetime.now().isoformat(timespec="seconds"), modules=bank(), error=None)
        cls.srv = pm.ThreadingHTTPServer(("127.0.0.1", 0), pm.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as r:
            return r.status, r.read().decode()

    def test_page(self):
        status, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("Banco batterie", body)

    def test_api(self):
        latest = json.loads(self.get("/api/latest")[1])
        self.assertEqual(len(latest["modules"]), 4)
        self.assertEqual(len(latest["modules"][1]["cells"]), 15)
        self.assertIn("series", json.loads(self.get("/api/history?hours=6")[1]))
        self.assertIsInstance(json.loads(self.get("/api/stats?days=7")[1]), dict)

    def test_unknown_path(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/nope")
        self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
