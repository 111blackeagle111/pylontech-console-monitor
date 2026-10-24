"""Monitor locale Pylontech: legge la console RS232 del modulo master e mostra i dati su una pagina web.

Invia solo comandi di lettura: pwr, pwr N, bat N, soh N, stat N, info N, log.
Uso:  python3 pylon_monitor.py
Variabili opzionali: PYLON_PORT (porta seriale), PYLON_DATA (cartella dei CSV), HOST, PORT, INTERVAL,
                     NOMINAL_AH (capacità di un modulo), CUTOFF_SOC (soglia di passaggio alla rete dell'inverter)
Licenza MIT.
"""
import csv, glob, json, os, threading, time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import serial

SERIAL = os.environ.get("PYLON_PORT", "/dev/ttyUSB0")
DATA = os.environ.get("PYLON_DATA", os.path.dirname(os.path.abspath(__file__)))
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8765"))
INTERVAL = int(os.environ.get("INTERVAL", "30"))
NOMINAL_AH = float(os.environ.get("NOMINAL_AH", "50"))
CUTOFF_SOC = float(os.environ.get("CUTOFF_SOC", "30"))
SOH_EVERY = 10      # cicli fra due letture soh (lo stato di salute cambia lentamente)
DETAIL_EVERY = 20   # cicli fra due letture di pwr N, stat N e registro eventi
INFO_EVERY = 120    # cicli fra due letture di info N (dati quasi statici)
FIELDS = ["ts", "id", "volt", "curr", "temp", "vlow", "vhigh", "soc", "base", "volt_st", "curr_st", "temp_st"]
# contatori di stat N salvati una volta al giorno, per vedere se gli eventi aumentano
STAT_KEYS = ["CYCLE Times", "Dsg Cap", "Pwr Coulomb", "Bat OV Times", "Bat HV Times", "Bat LV Times", "Bat UV Times",
             "COC Times", "COC2 Times", "COCA Times", "DOC Times", "DOC2 Times", "DOCA Times", "SC Times",
             "Shut Times", "Reset Times", "SOH Times", "LifeWarn Times", "LifeAlarm Times"]
WAKE = bytes.fromhex("7E3230303134363832433030343835323046434333300D")  # risveglio console a 1200 baud

latest = {"ts": None, "modules": [], "error": "in attesa della prima lettura", "details": {}, "log": [],
          "config": {"nominal_ah": NOMINAL_AH, "cutoff_soc": CUTOFF_SOC, "interval": INTERVAL}}


def command(s, cmd, timeout=6):
    s.reset_input_buffer()
    s.write((cmd + "\r").encode())
    buf, end = b"", time.time() + timeout
    while time.time() < end and b"pylon>" not in (buf.split(cmd.encode(), 1)[-1] if cmd else buf):
        buf += s.read(s.in_waiting or 1)
    return buf.decode(errors="replace")


def open_console():
    s = serial.Serial(SERIAL, 115200, timeout=0.2)
    if "pylon" not in command(s, "", 2).lower():
        s.baudrate = 1200
        s.write(WAKE)
        time.sleep(1)
        s.baudrate = 115200
        time.sleep(0.5)
        command(s, "", 2)
    return s


def parse_pwr(text):
    mods = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 13 or not f[0].isdigit() or f[8] == "Absent":
            continue
        m = {"id": int(f[0]), "volt": int(f[1]) / 1000, "curr": int(f[2]) / 1000, "temp": int(f[3]) / 1000,
             "tlow": int(f[4]) / 1000, "thigh": int(f[5]) / 1000, "vlow": int(f[6]), "vhigh": int(f[7]),
             "soc": int(f[12].rstrip("%")), "base": f[8], "volt_st": f[9], "curr_st": f[10], "temp_st": f[11]}
        if len(f) >= 19:  # orologio BMS, stati batteria e temperatura MOSFET
            m.update(clock=f"{f[13]} {f[14]}", bv_st=f[15], bt_st=f[16], mos_temp=int(f[17]) / 1000, mos_st=f[18])
        mods.append(m)
    return mods


def parse_kv(text):
    """Righe `Chiave : valore [unità]` di pwr N, stat N e info N."""
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition(":")
        if sep and k.strip() and v.strip() and not k.strip().startswith(("pylon", "Command")):
            out[k.strip()] = " ".join(v.split())
    return out


def read_log(s, pages=4):
    """Registro eventi del modulo collegato (il master): legge le prime pagine e poi esce dalla paginazione."""
    s.reset_input_buffer()
    s.write(b"log\r")
    buf, handled, end = b"", 0, time.time() + 20
    while time.time() < end and b"pylon>" not in buf.split(b"log", 1)[-1]:
        buf += s.read(s.in_waiting or 1)
        n = buf.count(b"Press [Enter]")
        if n > handled:
            handled = n
            s.write(b"\r" if handled < pages else b"q")
    command(s, "", 2)  # riallinea il prompt
    entries, cur = [], {}
    for line in buf.decode(errors="replace").splitlines():
        k, sep, v = line.partition(":")
        k = k.strip()
        if sep and k in ("Index", "Time", "ModID", "Code", "Info"):
            if k == "Index" and cur:
                entries.append(cur)
                cur = {}
            cur[k.lower()] = v.strip()
    return entries + ([cur] if cur else [])


def parse_table(text, min_cols):
    """Righe numerate 0..14 delle tabelle `bat N` e `soh N`."""
    return [f for f in (l.split() for l in text.splitlines()) if len(f) >= min_cols and f[0].isdigit() and f[1].isdigit()]


def month_file(ts):
    return os.path.join(DATA, f"pylontech-{ts[:7]}.csv")


def append_log(ts, mods):
    path = month_file(ts)
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.DictWriter(fh, FIELDS, extrasaction="ignore")
        if new:
            w.writeheader()
        for m in mods:
            w.writerow({"ts": ts, **m})


def append_stats(ts, details):
    path = os.path.join(DATA, f"pylontech-stat-{ts[:7]}.csv")
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["ts", "id"] + STAT_KEYS)
        for mid, d in sorted(details.items()):
            stat = d.get("stat", {})
            if stat:
                w.writerow([ts, mid] + [stat.get(k, "") for k in STAT_KEYS])


def stats_history(days):
    """Ultima riga di contatori per modulo e per giorno."""
    first = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    for path in sorted(glob.glob(os.path.join(DATA, "pylontech-stat-????-??.csv"))):
        if path[-11:-4] < first[:7]:
            continue
        with open(path) as fh:
            for r in csv.DictReader(fh):
                if r["ts"][:10] >= first:
                    out.setdefault(r["id"], {})[r["ts"][:10]] = {k: r.get(k, "") for k in STAT_KEYS}
    return {mid: sorted(days_.items()) for mid, days_ in out.items()}


def migrate_legacy():
    old = os.path.join(DATA, "pylontech-log.csv")
    if os.path.exists(old):
        with open(old) as fh:
            first = next(csv.DictReader(fh), None)
        target = month_file(first["ts"]) if first else None
        if target and not os.path.exists(target):
            os.replace(old, target)


def poller():
    s, cycle, soh, stat_day = None, 0, {}, None
    details = latest["details"]
    while True:
        try:
            s = s or open_console()
            mods = parse_pwr(command(s, "pwr"))
            if not mods:
                raise RuntimeError("risposta pwr vuota: il cavo è sul modulo master (1)?")
            for m in mods:
                mid = m["id"]
                rows = parse_table(command(s, f"bat {mid}"), 12)
                if cycle % SOH_EVERY == 0:
                    soh[mid] = {int(r[0]): r[3] for r in parse_table(command(s, f"soh {mid}"), 4)}
                m["cells"] = [{"n": int(r[0]), "v": int(r[1]), "t": int(r[3]) / 1000, "bal": r[-1] == "Y",
                               "soh": soh.get(mid, {}).get(int(r[0]), "?")} for r in rows]
                if rows and rows[0][9].isdigit():
                    m["remain_mah"] = int(rows[0][9])
                d = details.setdefault(mid, {})
                if cycle % DETAIL_EVERY == 0:
                    d["pwr"] = parse_kv(command(s, f"pwr {mid}"))
                    d["stat"] = parse_kv(command(s, f"stat {mid}", 10))
                    d["ts"] = datetime.now().isoformat(timespec="seconds")
                if cycle % INFO_EVERY == 0:
                    d["info"] = parse_kv(command(s, f"info {mid}"))
            if cycle % DETAIL_EVERY == 0:
                latest["log"] = read_log(s)
            ts = datetime.now().isoformat(timespec="seconds")
            latest.update(ts=ts, modules=mods, error=None)
            append_log(ts, mods)
            if stat_day != ts[:10] and any(d.get("stat") for d in details.values()):
                append_stats(ts, details)
                stat_day = ts[:10]
            cycle += 1
        except Exception as e:
            latest["error"] = f"{type(e).__name__}: {e}"
            if s:
                s.close()
            s = None
        time.sleep(INTERVAL)


def history(hours, points=360):
    since = datetime.now() - timedelta(hours=hours)
    first_month = since.strftime("%Y-%m")
    files = sorted(f for f in glob.glob(os.path.join(DATA, "pylontech-????-??.csv")) if f[-11:-4] >= first_month)
    bucket = max(INTERVAL, hours * 3600 / points)
    acc = {}  # (id, bucket) -> [n, soc, delta, power]
    for path in files:
        with open(path) as fh:
            for r in csv.DictReader(fh):
                t = datetime.fromisoformat(r["ts"])
                if t < since:
                    continue
                a = acc.setdefault((int(r["id"]), int(t.timestamp() // bucket)), [0, 0, 0, 0])
                a[0] += 1
                a[1] += int(r["soc"])
                a[2] += int(r["vhigh"]) - int(r["vlow"])
                a[3] += float(r["volt"]) * float(r["curr"])
    series, total = {}, {}
    for (mid, b), (n, soc, delta, power) in sorted(acc.items(), key=lambda kv: kv[0][1]):
        t = int(b * bucket * 1000)
        series.setdefault(mid, []).append([t, round(soc / n, 1), round(delta / n), round(power / n)])
        total[t] = total.get(t, 0) + power / n
    return {"bucket": bucket, "series": series, "total": [[t, round(p)] for t, p in sorted(total.items())]}


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype):
        data = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/api/latest":
            self.send(json.dumps(latest), "application/json")
        elif self.path.startswith("/api/history"):
            try:
                hours = min(max(float(self.path.partition("hours=")[2] or 24), 0.5), 24 * 31)
            except ValueError:
                hours = 24
            self.send(json.dumps(history(hours)), "application/json")
        elif self.path.startswith("/api/stats"):
            try:
                days = min(max(int(self.path.partition("days=")[2] or 30), 1), 366)
            except ValueError:
                days = 30
            self.send(json.dumps(stats_history(days)), "application/json")
        elif self.path == "/":
            self.send(PAGE, "text/html; charset=utf-8")
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


PAGE = """<!doctype html><html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Banco batterie</title>
<style>
:root{color-scheme:light;
--bg:#e8ecf0;--panel:#ffffff;--panel2:#f4f6f8;--ink:#17212b;--ink2:#4c5a68;--muted:#7a8794;--rule:#d0d7de;--rule2:#e7ebef;
--accent:#00707f;--ok:#2b8a3e;--warn:#b7791f;--crit:#c0392b;--fill:#55677a;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--low:#d64545;--high:#2a78d6;--neutral:#eef1f4}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;
--bg:#0d1318;--panel:#141c23;--panel2:#19222a;--ink:#e1e7ed;--ink2:#a2afbb;--muted:#738190;--rule:#26313b;--rule2:#1d2730;
--accent:#2fb0bf;--ok:#3fb950;--warn:#d9a03a;--crit:#e5534b;--fill:#8698a9;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--low:#e66767;--high:#3987e5;--neutral:#24303a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 "Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;font-variant-numeric:tabular-nums}
.top{background:var(--panel);border-top:3px solid var(--accent);border-bottom:1px solid var(--rule)}
.top .in{max-width:1320px;margin:auto;padding:12px 20px;display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}
.top h1{margin:0;font-size:18px;font-weight:600;letter-spacing:-.01em}.top .sub{font-size:13px;color:var(--ink2)}
.conn{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink2)}.dot{width:9px;height:9px;border-radius:50%;background:var(--muted)}
.dot.on{background:var(--ok);box-shadow:0 0 0 3px color-mix(in srgb,var(--ok) 22%,transparent)}.dot.off{background:var(--crit)}
main{max-width:1320px;margin:auto;padding:16px 20px 32px;display:grid;gap:14px}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:3px}
.ph{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:10px 16px;border-bottom:1px solid var(--rule2);flex-wrap:wrap}
.ph h2{margin:0;font-size:14px;font-weight:600}.ph .note{font-size:12px;color:var(--muted)}
.kpi{display:grid;grid-template-columns:repeat(4,1fr)}.kpi>div{padding:14px 18px;border-left:1px solid var(--rule2)}.kpi>div:first-child{border-left:0}
.kpi .l{font-size:12.5px;color:var(--ink2)}.kpi .v{font-size:30px;font-weight:600;letter-spacing:-.02em;line-height:1.15;margin:4px 0 2px}
.kpi .v small{font-size:15px;font-weight:500;color:var(--ink2);margin-left:3px}.kpi .s{font-size:12px;color:var(--muted)}
.dir{display:inline-block;font-size:12px;font-weight:600;padding:1px 7px;border-radius:2px;margin-left:6px;vertical-align:4px;background:var(--panel2);color:var(--ink2);border:1px solid var(--rule)}
.dir.dis{color:var(--warn);border-color:color-mix(in srgb,var(--warn) 45%,var(--rule))}.dir.chg{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,var(--rule))}
#alerts:empty{display:none}#alerts{display:grid;gap:0}
.al{display:grid;grid-template-columns:26px 1fr auto;align-items:center;gap:10px;padding:9px 16px;border-top:1px solid var(--rule2);font-size:13.5px}.al:first-child{border-top:0}
.al .ic{width:20px;height:20px;border-radius:2px;display:grid;place-items:center;font-size:12px;font-weight:700;color:#fff}
.al.crit .ic{background:var(--crit)}.al.warn .ic{background:var(--warn)}.al .m{font-size:12px;color:var(--muted)}
.rack .hdr,.rack .row{display:grid;grid-template-columns:132px 140px 68px 64px 92px 1fr 70px;gap:14px;align-items:center;padding:0 16px}
.rack .hdr{font-size:12px;color:var(--muted);padding-top:9px;padding-bottom:7px;border-bottom:1px solid var(--rule2)}
.rack .row{padding-top:12px;padding-bottom:12px;border-bottom:1px solid var(--rule2)}.rack .row:last-of-type{border-bottom:0}
.rack .r{text-align:right}.mid{display:flex;align-items:center;gap:8px;font-weight:600}.mid .key{width:4px;height:28px;border-radius:1px}
.mid .st{display:block;font-size:12px;font-weight:500}.st.ok{color:var(--ok)}.st.warn{color:var(--warn)}.st.crit{color:var(--crit)}
.socw{display:flex;align-items:center;gap:10px}.socb{flex:1;height:14px;background:var(--panel2);border:1px solid var(--rule);border-radius:2px;position:relative;overflow:hidden}
.socb i{position:absolute;inset:0 auto 0 0;background:var(--fill)}.socb b{position:absolute;top:-2px;bottom:-2px;width:0;border-left:1px dashed var(--ink2);opacity:.6}
.socv{font-size:17px;font-weight:600;width:46px;text-align:right}
.cells{display:grid;grid-template-columns:repeat(15,minmax(0,1fr));gap:2px}
.cell{height:34px;border-radius:2px;display:flex;align-items:center;justify-content:center;font-size:11px;color:var(--ink);position:relative;cursor:default;outline-offset:1px}
.cell.abn{box-shadow:inset 0 0 0 2px var(--crit)}.cell.abn::before{content:"!";position:absolute;top:1px;left:3px;font-size:10px;font-weight:700;color:var(--crit)}
.cell:hover,.cell:focus-visible{outline:2px solid var(--ink)}
.delta{font-weight:600}.delta.warn{color:var(--warn)}
.foot{display:flex;flex-wrap:wrap;gap:12px 32px;align-items:center;padding:10px 16px;border-top:1px solid var(--rule2);background:var(--panel2);font-size:12px;color:var(--ink2)}
.grad{display:inline-block;width:150px;height:10px;border-radius:2px;vertical-align:middle;margin:0 8px;background:linear-gradient(to right,var(--low),var(--neutral),var(--high));border:1px solid var(--rule)}
.abnk{display:inline-block;width:14px;height:12px;border-radius:2px;box-shadow:inset 0 0 0 2px var(--crit);vertical-align:middle;margin-right:6px}
.seg{display:inline-flex;border:1px solid var(--rule);border-radius:3px;overflow:hidden}.seg button{font:inherit;font-size:12.5px;padding:5px 12px;border:0;border-left:1px solid var(--rule);background:var(--panel);color:var(--ink2);cursor:pointer}
.seg button:first-child{border-left:0}.seg button[aria-pressed=true]{background:var(--ink);color:var(--panel)}.seg button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.chart{padding:12px 16px 10px;border-top:1px solid var(--rule2)}.chart:first-of-type{border-top:0}
.ch{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:6px}.ch h3{margin:0;font-size:13px;font-weight:600}
.legend{display:flex;gap:14px;font-size:12px;color:var(--ink2);flex-wrap:wrap}.lk{display:inline-block;width:14px;height:2px;border-radius:1px;vertical-align:middle;margin-right:5px}
svg{display:block;width:100%;height:170px;overflow:visible}svg text{fill:var(--muted);font-size:11px}
#charts.dim{opacity:.55}
#tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--rule);box-shadow:0 4px 14px rgba(0,0,0,.16);border-radius:3px;padding:7px 10px;font-size:12px;display:none;z-index:9;min-width:130px}
#tip .t{color:var(--muted);margin-bottom:3px}#tip .row{display:flex;justify-content:space-between;gap:14px;align-items:center}#tip b{font-weight:600}
.err{color:var(--crit)}
.more{font:inherit;font-size:12px;margin-top:4px;padding:2px 8px;border:1px solid var(--rule);border-radius:2px;background:var(--panel);color:var(--ink2);cursor:pointer}
.more:hover{border-color:var(--ink2)}.more:focus-visible{outline:2px solid var(--accent)}.more[aria-expanded=true]{background:var(--ink);color:var(--panel);border-color:var(--ink)}
.det{background:var(--panel2);border-bottom:1px solid var(--rule2);padding:14px 16px 16px;display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:14px 24px}
.det section{min-width:0}.det h4{margin:0 0 6px;font-size:12.5px;font-weight:600;color:var(--ink);padding-bottom:4px;border-bottom:1px solid var(--rule)}
.det dl{display:grid;grid-template-columns:1fr auto;gap:3px 12px;margin:0;font-size:12.5px}.det dt{color:var(--ink2)}.det dd{margin:0;text-align:right;font-weight:500}
.det dd.hot{color:var(--warn);font-weight:600}.det dd.bad{color:var(--crit);font-weight:600}.det dd small{color:var(--muted);font-weight:400;margin-left:4px}
.det .wide{grid-column:1/-1}.det .cnt{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:0 28px}.det .kv{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font-size:12.5px;padding:3px 0;border-bottom:1px solid var(--rule2)}.det .kv .k{color:var(--ink2)}.det .kv b{font-weight:500;white-space:nowrap}.det .kv b.hot{color:var(--warn);font-weight:600}.det .kv b.bad{color:var(--crit);font-weight:600}.det .kv small{color:var(--muted);font-weight:400;margin-left:6px}
.det .codes{font-size:11.5px;color:var(--muted);line-height:1.6;word-break:break-word}.det .stamp{grid-column:1/-1;font-size:12px;color:var(--muted)}
.log{width:100%;border-collapse:collapse;font-size:12.5px}.log th{text-align:left;font-weight:500;color:var(--muted);padding:7px 16px;border-bottom:1px solid var(--rule2)}
.log td{padding:6px 16px;border-bottom:1px solid var(--rule2)}.log tr:last-child td{border-bottom:0}.log td.c{color:var(--muted)}
@media (max-width:980px){
 .kpi{grid-template-columns:repeat(2,1fr)}.kpi>div:nth-child(3){border-left:0}.kpi>div:nth-child(n+3){border-top:1px solid var(--rule2)}
 .kpi .v{font-size:24px}.rack .hdr{display:none}
 .rack .row{grid-template-columns:repeat(3,1fr);grid-template-areas:"id id d" "soc soc soc" "v c t" "cells cells cells"}
 .rack .row>.c-id{grid-area:id}.rack .row>.c-soc{grid-area:soc}.rack .row>.c-v{grid-area:v}.rack .row>.c-c{grid-area:c}.rack .row>.c-t{grid-area:t}
 .rack .row>.c-cells{grid-area:cells}.rack .row>.c-d{grid-area:d}.rack .r{text-align:left}.rack .row>.c-d{text-align:right}
 .rack .row [data-l]::before{content:attr(data-l);display:block;font-size:11px;color:var(--muted);font-weight:400}
 .cells{grid-template-columns:repeat(8,minmax(0,1fr))}
}
@media (prefers-reduced-motion:no-preference){#charts{transition:opacity .2s}}
</style></head><body>
<header class="top"><div class="in">
<div><h1>Banco batterie</h1><div class="sub" id="sub">Pylontech</div></div>
<div class="conn" role="status"><span class="dot" id="dot"></span><span id="ts">In attesa della prima lettura</span></div>
</div></header>
<main>
<section class="panel kpi" id="kpi" aria-label="Riepilogo del banco"></section>
<section class="panel" id="alerts" aria-label="Avvisi"></section>
<section class="panel rack" aria-label="Moduli">
<div class="ph"><h2>Moduli e celle</h2><span class="note">Dall'alto in basso come nel rack. Il modulo 1 è il master collegato all'inverter.</span></div>
<div class="hdr"><span>Modulo</span><span>Carica</span><span class="r">Tensione</span><span class="r">Corrente</span><span class="r">Temp. celle</span><span>Tensione delle 15 celle, mV</span><span class="r">Scarto celle</span></div>
<div id="rows"></div>
<div class="foot">
<span>Celle, scostamento dalla mediana del modulo:<span class="grad"></span>da −60 mV a +60 mV</span>
<span><span class="abnk"></span>Cella con stato di salute anomalo segnalato dal BMS</span>
<span>La linea tratteggiata nella barra di carica indica la soglia di passaggio alla rete</span>
</div></section>
<section class="panel" aria-label="Registro eventi">
<div class="ph"><h2>Registro eventi del master</h2><span class="note" id="lognote">Ultimi eventi registrati dal BMS del modulo 1</span></div>
<div id="log"></div></section>
<section class="panel" aria-label="Andamento">
<div class="ph"><h2>Andamento</h2>
<div class="seg" role="group" aria-label="Periodo"><button data-h="6">6 ore</button><button data-h="24" aria-pressed="true">24 ore</button><button data-h="168">7 giorni</button><button data-h="720">30 giorni</button></div></div>
<div id="charts">
<div class="chart"><div class="ch"><h3>Carica per modulo, %</h3><div class="legend" id="l-soc"></div></div><svg id="c-soc" role="img" aria-label="Carica per modulo nel tempo"></svg></div>
<div class="chart"><div class="ch"><h3>Scarto fra cella più alta e più bassa, mV</h3><div class="legend" id="l-delta"></div></div><svg id="c-delta" role="img" aria-label="Scarto celle per modulo nel tempo"></svg></div>
<div class="chart"><div class="ch"><h3>Potenza del banco, W</h3><div class="legend"><span>sopra lo zero carica, sotto lo zero scarica</span></div></div><svg id="c-pow" role="img" aria-label="Potenza del banco nel tempo"></svg></div>
</div></section>
</main><div id="tip" role="tooltip"></div>
<script>
const SC=['--s1','--s2','--s3','--s4'],css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const col=id=>css(SC[(id-1)%SC.length]),tip=document.getElementById('tip');
const el=(tag,attrs={},text)=>{const e=document.createElement(tag);for(const k in attrs)e.setAttribute(k,attrs[k]);if(text!=null)e.textContent=text;return e};
const svgEl=(tag,attrs={})=>{const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const k in attrs)e.setAttribute(k,attrs[k]);return e};
const fmt=(n,d=0)=>n.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
const dur=h=>!isFinite(h)?'—':h>=48?fmt(h/24,1)+' giorni':h>=1?Math.floor(h)+' h '+String(Math.round(h%1*60)).padStart(2,'0')+' min':Math.round(h*60)+' min';
function showTip(x,y,title,rows){tip.replaceChildren(el('div',{class:'t'},title));
  for(const [c,label,val] of rows){const r=el('div',{class:'row'}),l=el('span');if(c){const k=el('span',{class:'lk'});k.style.background=c;l.append(k)}
    l.append(document.createTextNode(label));r.append(l,el('b',{},val));tip.append(r)}
  tip.style.display='block';const w=tip.offsetWidth,h=tip.offsetHeight;
  tip.style.left=Math.min(x+14,innerWidth-w-8)+'px';tip.style.top=Math.max(8,Math.min(y+14,innerHeight-h-8))+'px'}
const hideTip=()=>tip.style.display='none';

let cfg={nominal_ah:50,cutoff_soc:30,interval:30},det={},open=new Set(),lastMods=[];
async function load(){
  let d;try{d=await (await fetch('/api/latest')).json()}catch(e){conn(null,'Monitor non raggiungibile');return}
  cfg=d.config||cfg;const m=d.modules||[];
  const dn=(((d.details||{})[1]||{}).info||{})['Device name'],model=dn?'Pylontech '+dn:'Pylontech';
  document.getElementById('sub').textContent=m.length?`${model}, ${m.length} moduli, ${fmt(m.length*cfg.nominal_ah*48/1000,1)} kWh nominali`:'Pylontech';
  det=d.details||{};lastMods=m;conn(d.ts,d.error);kpi(m);alerts(m);rows(m);logView(d.log||[],m);
}
function conn(ts,err){const dot=document.getElementById('dot'),t=document.getElementById('ts');
  const age=ts?(Date.now()-Date.parse(ts))/1000:Infinity, fresh=age<cfg.interval*3&&!err;
  dot.className='dot '+(fresh?'on':'off');
  t.replaceChildren(document.createTextNode(ts?'Aggiornato alle '+new Date(ts).toLocaleTimeString('it-IT'):'Nessuna lettura'));
  if(err)t.append(el('span',{class:'err'},'. '+err));else if(!fresh&&ts)t.append(el('span',{class:'err'},'. Dati non aggiornati'))}
function status(x,avg){const d=x.vhigh-x.vlow,bad=(x.cells||[]).some(c=>c.soh==='Abnormal')||[x.volt_st,x.curr_st,x.temp_st].some(s=>s!=='Normal');
  return bad?['crit','Anomalia']:(Math.abs(x.soc-avg)>20||d>50)?['warn','Attenzione']:['ok','Normale']}
function kpi(m){
  if(!m.length)return document.getElementById('kpi').replaceChildren();
  const p=m.reduce((a,x)=>a+x.volt*x.curr,0),avg=m.reduce((a,x)=>a+x.soc,0)/m.length;
  const above=m.reduce((a,x)=>a+Math.max(0,x.soc-cfg.cutoff_soc)/100*cfg.nominal_ah*x.volt,0)/1000;
  const toFull=m.reduce((a,x)=>a+(100-x.soc)/100*cfg.nominal_ah*x.volt,0)/1000;
  const mode=p<-20?['dis','Scarica']:p>20?['chg','Carica']:['','Ferma'];
  const t=p<-20?['Autonomia fino al '+cfg.cutoff_soc+'%',dur(above*1000/-p),'al carico attuale, poi passa alla rete']:p>20?['Tempo per la carica completa',dur(toFull*1000/p),'alla potenza di carica attuale']:['Autonomia','—','batteria ferma'];
  const cell=(l,v,unit,s,extra)=>{const c=el('div'),vv=el('div',{class:'v'},v);if(unit)vv.append(el('small',{},unit));if(extra)vv.append(extra);c.append(el('div',{class:'l'},l),vv,el('div',{class:'s'},s));return c};
  document.getElementById('kpi').replaceChildren(
    cell('Potenza',fmt(Math.abs(p)),'W','somma dei '+m.length+' moduli',el('span',{class:'dir '+mode[0]},mode[1])),
    cell('Carica media',fmt(avg),'%','minimo '+Math.min(...m.map(x=>x.soc))+'%, massimo '+Math.max(...m.map(x=>x.soc))+'%'),
    cell('Energia utilizzabile',fmt(above,1),'kWh','sopra la soglia del '+cfg.cutoff_soc+'%'),
    cell(t[0],t[1],'',t[2]))
}
function alerts(m){
  const out=[],avg=m.reduce((a,x)=>a+x.soc,0)/(m.length||1);
  const add=(lvl,text,meta)=>{const r=el('div',{class:'al '+lvl,role:'alert'});r.append(el('span',{class:'ic','aria-hidden':'true'},lvl==='crit'?'✕':'!'),el('span',{},text),el('span',{class:'m'},meta));out.push(r)};
  for(const x of m){const d=x.vhigh-x.vlow,st=[x.volt_st,x.curr_st,x.temp_st].filter(s=>s!=='Normal'),bad=(x.cells||[]).filter(c=>c.soh==='Abnormal');
    if(st.length)add('crit',`Modulo ${x.id}: il BMS segnala ${st.join(', ')}`,'Anomalia');
    if(bad.length)add('crit',`Modulo ${x.id}: stato di salute anomalo sulla cella ${bad.map(c=>c.n).join(', ')}`,'Anomalia');
    if(Math.abs(x.soc-avg)>20)add('warn',`Modulo ${x.id}: carica al ${x.soc}%, la media del banco è ${fmt(avg)}%`,'Attenzione');
    if(d>50)add('warn',`Modulo ${x.id}: scarto fra le celle di ${d} mV`,'Attenzione')}
  document.getElementById('alerts').replaceChildren(...out)
}
const cellColor=dev=>`color-mix(in oklab, var(${dev<0?'--low':'--high'}) ${(Math.min(Math.abs(dev)/60,1)*100).toFixed(0)}%, var(--neutral))`;
function rows(m){
  const avg=m.reduce((a,x)=>a+x.soc,0)/(m.length||1);
  document.getElementById('rows').replaceChildren(...m.flatMap(x=>{
    const r=el('div',{class:'row'}),[sc,stxt]=status(x,avg),d=x.vhigh-x.vlow;
    const id=el('div',{class:'c-id mid'}),k=el('span',{class:'key'});k.style.background=col(x.id);
    const nm=el('div',{},'Modulo '+x.id);nm.append(el('span',{class:'st '+sc},stxt+(x.base?', '+({Dischg:'in scarica',Charge:'in carica',Idle:'a riposo'}[x.base]||x.base):'')));
    const btn=el('button',{class:'more','aria-expanded':String(open.has(x.id)),'aria-controls':'det-'+x.id},open.has(x.id)?'Chiudi dettagli':'Dettagli');
    btn.addEventListener('click',()=>{open.has(x.id)?open.delete(x.id):open.add(x.id);rows(lastMods)});nm.append(btn);id.append(k,nm);
    const soc=el('div',{class:'c-soc socw'}),b=el('div',{class:'socb',role:'img','aria-label':'Carica '+x.soc+'%'}),i=el('i'),th=el('b');
    i.style.width=x.soc+'%';th.style.left=cfg.cutoff_soc+'%';b.append(i,th);soc.append(b,el('span',{class:'socv'},x.soc+'%'));
    const cells=el('div',{class:'c-cells cells',role:'list','aria-label':'Tensioni delle celle del modulo '+x.id});
    const vs=(x.cells||[]).map(z=>z.v).sort((a,b)=>a-b),med=vs[Math.floor(vs.length/2)];
    for(const z of x.cells||[]){const dev=z.v-med,c=el('div',{class:'cell'+(z.soh==='Abnormal'?' abn':''),role:'listitem',tabindex:0,
      'aria-label':`Cella ${z.n}: ${z.v} mV, ${dev>=0?'+':''}${dev} mV dalla mediana, salute ${z.soh}`},String(z.v));
      c.style.background=cellColor(dev);
      const show=e=>{const rc=e.target.getBoundingClientRect();showTip(e.clientX||rc.right,e.clientY||rc.bottom,`Modulo ${x.id}, cella ${z.n}`,
        [[null,'Tensione',z.v+' mV'],[null,'Dalla mediana',(dev>=0?'+':'')+dev+' mV'],[null,'Salute',z.soh==='?'?'in lettura':z.soh==='Abnormal'?'anomala':'normale'],[null,'Bilanciamento',z.bal?'attivo':'no']])};
      c.addEventListener('pointermove',show);c.addEventListener('focus',show);c.addEventListener('pointerleave',hideTip);c.addEventListener('blur',hideTip);cells.append(c)}
    r.append(id,soc,el('div',{class:'c-v r','data-l':'Tensione'},fmt(x.volt,2)+' V'),el('div',{class:'c-c r','data-l':'Corrente'},fmt(x.curr,1)+' A'),
      el('div',{class:'c-t r','data-l':'Temp. celle'},x.tlow!=null?fmt(x.tlow,1)+'–'+fmt(x.thigh,1)+' °C':fmt(x.temp,1)+' °C'),cells,el('div',{class:'c-d r delta'+(d>50?' warn':''),'data-l':'Scarto celle'},d+' mV'));
    return open.has(x.id)?[r,detail(x)]:[r]}))
}

/* ---- dettaglio modulo ---- */
const LBL={'CYCLE Times':'Cicli completi','Dsg Cap':'Scarica totale','Pwr Coulomb':'Contatore Pwr Coulomb','Charge Times':'Cariche (contatore BMS)',
 'Bat OV Times':'Cella in sovratensione','Bat HV Times':'Cella a tensione alta','Bat LV Times':'Cella a tensione bassa','Bat UV Times':'Cella in sottotensione',
 'Pwr OV Times':'Modulo in sovratensione','Pwr HV Times':'Modulo a tensione alta','Pwr LV Times':'Modulo a tensione bassa','Pwr UV Times':'Modulo in sottotensione',
 'COC Times':'Sovracorrente in carica','COC2 Times':'Sovracorrente in carica, livello 2','COCA Times':'Avviso sovracorrente in carica',
 'DOC Times':'Sovracorrente in scarica','DOC2 Times':'Sovracorrente in scarica, livello 2','DOCA Times':'Avviso sovracorrente in scarica','SC Times':'Cortocircuito',
 'COT Times':'Temperatura alta in carica','CUT Times':'Temperatura bassa in carica','DOT Times':'Temperatura alta in scarica','DUT Times':'Temperatura bassa in scarica',
 'CHT Times':'Avviso temperatura alta in carica','CLT Times':'Avviso temperatura bassa in carica','DHT Times':'Avviso temperatura alta in scarica','DLT Times':'Avviso temperatura bassa in scarica',
 'Shut Times':'Spegnimenti','Reset Times':'Riavvii','SOH Times':'Eventi salute celle','LifeWarn Times':'Avvisi di fine vita','LifeAlarm Times':'Allarmi di fine vita','Discharge Cnt.':'Scariche (contatore)','Charge Cnt.':'Cariche (contatore)','Status Cnt.':'Cambi di stato','Idle Times':'Periodi a riposo'};
const NEUTRAL=new Set(['Discharge Cnt.','Charge Cnt.','Status Cnt.','Idle Times','LV Cnt','HT Cnt','LT Cnt','HT@0.5C Cnt','LT@0.5C Cnt']);
const SKIP=new Set(['Device address','Data Items','HisData Items','Pwr Percent','SOH','CYCLE Times','Dsg Cap','Pwr Coulomb','Charge Times']);
const BAD=new Set(['SC Times','Bat UV Times','Pwr UV Times','LifeAlarm Times','COC2 Times','DOC2 Times']);
const num=v=>parseInt(String(v||'').split(' ')[0],10);
function dl(pairs){const d=el('dl');for(const [k,v,cls,small] of pairs){if(v==null||v==='')continue;const dd=el('dd',cls?{class:cls}:{},String(v));if(small)dd.append(el('small',{},small));d.append(el('dt',{},k),dd)}return d}
function sec(title,body,wide){const s=el('section',wide?{class:'wide'}:{});s.append(el('h4',{},title),body);return s}
function delta7(id,key){const h=statsHist[id];if(!h||h.length<2)return '';const a=num(h[0][1][key]),b=num(h[h.length-1][1][key]);
  return isNaN(a)||isNaN(b)?'':(b-a>0?'+'+fmt(b-a):'±0')+' da '+new Date(h[0][0]).toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit'})}
function detail(x){
  const D=det[x.id]||{},P=D.pwr||{},S=D.stat||{},I=D.info||{},box=el('div',{class:'det',id:'det-'+x.id});
  if(!D.ts){box.append(el('div',{class:'stamp'},'Dettagli in lettura: arrivano entro un paio di minuti.'));return box}
  const cap=num(P['Total Coulomb']),dsg=num(S['Dsg Cap']);
  box.append(sec('Capacità e vita',dl([
    ['Cicli completi',S['CYCLE Times']?fmt(num(S['CYCLE Times'])):'',null,delta7(x.id,'CYCLE Times')],
    ['Capacità nominale',cap?fmt(cap/1000,0)+' Ah':''],
    ['Carica residua',x.remain_mah!=null?fmt(x.remain_mah/1000,1)+' Ah':''],
    ['Scaricati in totale',dsg?fmt(dsg/1000,0)+' Ah':'',null,dsg?'circa '+fmt(dsg/1000*48/1e6,1)+' MWh':''],
    ['Contatore Pwr Coulomb',S['Pwr Coulomb']?fmt(num(S['Pwr Coulomb'])):''],
    ['Avvisi di fine vita',S['LifeWarn Times'],num(S['LifeWarn Times'])>0?'hot':''],
    ['Allarmi di fine vita',S['LifeAlarm Times'],num(S['LifeAlarm Times'])>0?'bad':'']])));
  const okv=v=>!v||/^(Normal|OFF|0x0)$/.test(v)?'':/Abnormal|Fault|0x[1-9a-f]/i.test(v)?'bad':'hot';
  box.append(sec('Stato del BMS',dl([['Livello di carica',P['Coul. Status'],okv(P['Coul. Status'])],['Salute del modulo',P['Soh. Status'],okv(P['Soh. Status'])],
    ['Riscaldatore',P['Heater Status']],['Eventi batteria',P['Bat Events'],okv(P['Bat Events'])],['Eventi modulo',P['Power Events'],okv(P['Power Events'])],
    ['Guasto di sistema',P['System Fault'],okv(P['System Fault'])],['Tensione massima',P['Max Voltage']?fmt(num(P['Max Voltage'])/1000,1)+' V':'']])));
  const ct=(x.cells||[]).map(c=>c.t).filter(t=>t!=null);
  const clk=x.clock?(()=>{const t=new Date(x.clock.replace(' ','T'));if(isNaN(t))return [x.clock,''];
    const off=(t-Date.now())/36e5;return [x.clock,Math.abs(off)>0.1?(off>0?'avanti di ':'indietro di ')+dur(Math.abs(off)):'in orario']})():null;
  box.append(sec('Temperature e orologio',dl([['Temperatura scheda BMS',fmt(x.temp,1)+' °C'],['Celle, minima e massima',x.tlow!=null?fmt(x.tlow,1)+' / '+fmt(x.thigh,1)+' °C':''],
    ['Sensori celle',ct.length?fmt(Math.min(...ct),1)+' / '+fmt(Math.max(...ct),1)+' °C':''],
    ['MOSFET di potenza',x.mos_temp!=null?fmt(x.mos_temp,1)+' °C':'',x.mos_st&&x.mos_st!=='Normal'?'bad':'',x.mos_st&&x.mos_st!=='Normal'?x.mos_st:''],
    ['Orologio interno',clk?clk[0]:'',clk&&clk[1].startsWith('avanti')||clk&&clk[1].startsWith('indietro')?'hot':'',clk?clk[1]:'']])));
  box.append(sec('Identità',dl([['Numero di serie',I['Barcode']],['Modello',I['Device name']?I['Device name']+(I['Specification']?', '+I['Specification']:''):''],
    ['Firmware',I['Main Soft version']],['Software / boot / comunicazione',[I['Soft  version']||I['Soft version'],I['Boot  version']||I['Boot version'],I['Comm version']].filter(Boolean).join(' / ')],
    ['Data firmware',I['Release Date']],['Scheda',[I['Board version'],I['Board']].filter(Boolean).join(' ')],
    ['Corrente massima carica / scarica',I['Max Charge Curr']?fmt(num(I['Max Charge Curr'])/1000)+' / '+fmt(Math.abs(num(I['Max Dischg Curr']))/1000)+' A':'']])));
  const keys=Object.keys(S).filter(k=>!SKIP.has(k)),cnt=el('div',{class:'cnt'}),rank=k=>NEUTRAL.has(k)?2:LBL[k]?0:1;
  keys.sort((a,b)=>rank(a)-rank(b));
  for(const k of keys){const v=num(S[k]),it=el('div',{class:'kv'}),b=el('b',{class:v>0&&!NEUTRAL.has(k)?(BAD.has(k)?'bad':'hot'):''},isNaN(v)?S[k]:fmt(v));
    const d7=delta7(x.id,k);if(d7)b.append(el('small',{},d7));it.append(el('span',{class:'k',title:k},LBL[k]||k),b);cnt.append(it)}
  box.append(sec('Contatori di protezione dall’installazione',cnt,true));
  if(P['Protect ENA'])box.append(sec('Protezioni abilitate nel BMS',el('div',{class:'codes'},P['Protect ENA']),true));
  box.append(el('div',{class:'stamp'},'Dettagli letti alle '+new Date(D.ts).toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'})+', aggiornati ogni 10 minuti. In arancio i contatori di protezione diversi da zero; passa il mouse su un nome per il codice originale del BMS.'));
  return box
}
const LOGIT={'The device start discharging.':'Inizio scarica','The device start charging.':'Inizio carica'};
function logView(L,m){const box=document.getElementById('log');
  if(!L.length){box.replaceChildren(el('div',{class:'stamp',style:'padding:10px 16px;color:var(--muted);font-size:12.5px'},'Registro in lettura: arriva entro un paio di minuti.'));return}
  const master=m.find(x=>x.id===1),t=el('table',{class:'log'}),hd=el('tr');for(const h of ['Ora del BMS','Evento','Modulo interno','Codice'])hd.append(el('th',{},h));t.append(hd);
  for(const e of L){const tr=el('tr');tr.append(el('td',{},e.time||''),el('td',{},LOGIT[(e.info||'').trim()]||e.info||''),el('td',{class:'c'},e.modid||''),el('td',{class:'c'},e.code||''));t.append(tr)}
  box.replaceChildren(t);
  if(master&&master.clock)document.getElementById('lognote').textContent='Orari dell’orologio interno del BMS del modulo 1, che non coincide con l’ora reale (vedi Dettagli del modulo 1)'}
let statsHist={};
async function loadStats(){try{statsHist=await (await fetch('/api/stats?days=8')).json()}catch(e){}}

function niceTicks(lo,hi,n=4){const span=hi-lo||1,s0=span/n,mag=10**Math.floor(Math.log10(s0)),step=[1,2,2.5,5,10].map(s=>s*mag).find(s=>s>=s0);
  const out=[];for(let v=Math.ceil(lo/step)*step;v<=hi+1e-9;v+=step)out.push(+v.toFixed(6));return out}
function drawChart(svg,series,opt){
  svg.replaceChildren();const W=svg.clientWidth||800,H=170,L=46,R=30,T=6,B=20;svg.setAttribute('viewBox',`0 0 ${W} ${H}`);
  const pts=series.flatMap(s=>s.points);if(!pts.length){const t=svgEl('text',{x:L,y:H/2});t.textContent='Nessun dato nel periodo scelto';svg.append(t);return}
  const t0=Math.min(...pts.map(p=>p[0])),t1=Math.max(...pts.map(p=>p[0]),t0+1);
  let lo=opt.min??Math.min(...pts.map(p=>p[1])),hi=opt.max??Math.max(...pts.map(p=>p[1]));if(opt.zero){lo=Math.min(lo,0);hi=Math.max(hi,0)}if(hi===lo){hi+=1;lo-=1}
  const ticks=niceTicks(lo,hi);lo=Math.min(lo,ticks[0]);hi=Math.max(hi,ticks[ticks.length-1]);
  const X=t=>L+(t-t0)/(t1-t0)*(W-L-R),Y=v=>T+(hi-v)/(hi-lo)*(H-T-B);
  for(const v of ticks){svg.append(svgEl('line',{x1:L,x2:W-R,y1:Y(v),y2:Y(v),stroke:css(v===0&&opt.zero?'--muted':'--rule2'),'stroke-width':1}));
    const tx=svgEl('text',{x:L-8,y:Y(v)+4,'text-anchor':'end'});tx.textContent=fmt(v);svg.append(tx)}
  if(opt.ref!=null){svg.append(svgEl('line',{x1:L,x2:W-R,y1:Y(opt.ref),y2:Y(opt.ref),stroke:css('--ink2'),'stroke-dasharray':'4 4','stroke-width':1,opacity:.6}))}
  const days=(t1-t0)>36*3600e3,n=W<500?2:4;
  for(let i=0;i<=n;i++){const t=t0+(t1-t0)*i/n,d=new Date(t),tx=svgEl('text',{x:X(t),y:H-3,'text-anchor':i===0?'start':i===n?'end':'middle'});
    tx.textContent=(days?d.toLocaleDateString('it-IT',{day:'2-digit',month:'2-digit'})+' ':'')+d.toLocaleTimeString('it-IT',{hour:'2-digit',minute:'2-digit'});svg.append(tx)}
  const labels=[];
  for(const s of series){if(!s.points.length)continue;const ps=s.points.map(p=>X(p[0]).toFixed(1)+','+Y(p[1]).toFixed(1));
    if(s.area){svg.append(svgEl('polygon',{points:`${X(s.points[0][0])},${Y(0)} ${ps.join(' ')} ${X(s.points[s.points.length-1][0])},${Y(0)}`,fill:s.color,opacity:.14}))}
    svg.append(svgEl('polyline',{fill:'none',stroke:s.color,'stroke-width':2,'stroke-linejoin':'round','stroke-linecap':'round',points:ps.join(' ')}));
    if(s.label){const p=s.points[s.points.length-1];labels.push({x:X(p[0])+5,y:Y(p[1])+4,t:s.label})}}
  labels.sort((a,b)=>a.y-b.y).forEach((l,i,a)=>{if(i&&l.y-a[i-1].y<12)l.y=a[i-1].y+12;const tx=svgEl('text',{x:l.x,y:l.y});tx.textContent=l.t;tx.style.fill=css('--ink2');svg.append(tx)});
  const cross=svgEl('line',{y1:T,y2:H-B,stroke:css('--ink2'),'stroke-width':1,visibility:'hidden'});svg.append(cross);
  const hit=svgEl('rect',{x:L,y:0,width:W-L-R,height:H,fill:'transparent'});svg.append(hit);
  const near=(ps,t)=>{let a=0,b=ps.length-1;while(b-a>1){const mm=(a+b)>>1;ps[mm][0]<t?a=mm:b=mm}return Math.abs(ps[a][0]-t)<Math.abs(ps[b][0]-t)?ps[a]:ps[b]};
  hit.addEventListener('pointermove',e=>{const r=svg.getBoundingClientRect(),t=t0+((e.clientX-r.left)*W/r.width-L)/(W-L-R)*(t1-t0);
    const rs=series.filter(s=>s.points.length).map(s=>{const p=near(s.points,t);return [s.color,s.name,fmt(p[1])+' '+opt.unit,p[0]]});
    const tt=rs.length?rs[0][3]:t;cross.setAttribute('x1',X(tt));cross.setAttribute('x2',X(tt));cross.setAttribute('visibility','visible');
    showTip(e.clientX,e.clientY,new Date(tt).toLocaleString('it-IT',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'}),rs.map(x=>x.slice(0,3)))});
  hit.addEventListener('pointerleave',()=>{cross.setAttribute('visibility','hidden');hideTip()});
}
function legend(id,ids){document.getElementById(id).replaceChildren(...ids.map(i=>{const s=el('span'),k=el('span',{class:'lk'});k.style.background=col(i);s.append(k,document.createTextNode('Modulo '+i));return s}))}
let hours=24,hist=null;
async function charts(){const wrap=document.getElementById('charts');wrap.classList.add('dim');
  try{hist=await (await fetch('/api/history?hours='+hours)).json()}catch(e){return}finally{wrap.classList.remove('dim')}render()}
function render(){if(!hist)return;const ids=Object.keys(hist.series).map(Number).sort((a,b)=>a-b);
  const mk=k=>ids.map(i=>({name:'Modulo '+i,label:'M'+i,color:col(i),points:hist.series[i].map(p=>[p[0],p[k]])}));
  drawChart(document.getElementById('c-soc'),mk(1),{unit:'%',min:0,max:100,ref:cfg.cutoff_soc});legend('l-soc',ids);
  drawChart(document.getElementById('c-delta'),mk(2),{unit:'mV',min:0});legend('l-delta',ids);
  drawChart(document.getElementById('c-pow'),[{name:'Banco',color:css('--accent'),area:true,points:hist.total}],{unit:'W',zero:true})}
document.querySelectorAll('.seg button').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('.seg button').forEach(x=>x.setAttribute('aria-pressed',x===b));hours=+b.dataset.h;charts()}));
addEventListener('resize',render);matchMedia('(prefers-color-scheme: dark)').addEventListener('change',()=>{render();load()});
loadStats().then(load);charts();setInterval(load,10000);setInterval(charts,60000);setInterval(loadStats,600000);
</script></body></html>"""

if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    migrate_legacy()
    threading.Thread(target=poller, daemon=True).start()
    print(f"Monitor su http://{HOST}:{PORT} (lettura ogni {INTERVAL}s, dati in {DATA})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
