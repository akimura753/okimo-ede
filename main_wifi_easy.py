# main_wifi_easy.py  —  OKIMO EASY 人接近（Pico 2 W・Wi-Fi APモード）  ver wifi-easy-1.0
# ------------------------------------------------------------------------------------
# Pico 2 W が自分でアクセスポイント「OKIMO」を出す。スマホをその Wi-Fi につなぎ、
# ブラウザで方向（L/C/R）を Pico の URL に送ると、Pico が EASY のモールスリズムを
# 腰の電極（GP14）に打つ。EEG マーカーは GP15。USB もシリアルも使わない。
#
#   EASY 対応:  左 L → S(...)  正面 C → K(-.-)  右 R → M(--)
#   モールス符号化は Pico 内蔵。スマホは方向1文字を投げるだけ。
#
# 使い方:
#   1) main.py としてこのファイルを Pico 2 W に入れて起動
#   2) スマホの Wi-Fi 一覧で「OKIMO」に接続（パスワード: okimo1234）
#   3) スマホのブラウザで  http://192.168.4.1/  を開く（人接近ページから自動で叩かれる）
#
# HTTP エンドポイント（GET）:
#   /            → 稼働確認ページ（テストボタン付き）
#   /z?d=L|C|R   → その方向の EASY リズムを1回打つ（人接近ページが呼ぶ主エンドポイント）
#   /L /C /R     → 上の短縮形
#   /stim?ms=800 → 単発通電（テスト用）
#   /mark        → マーカーだけ打つ
#   /stop        → 停止
#   /ping        → "PONG"
#   /get         → 現在の設定(JSON)
#   /set?k=key&v=value  → 設定変更（例 /set?k=dot&v=250）  /save で保存
#
# 配線（今までと同じ）:
#   GP14(物理19) --330Ω--> 241B LED(+) / LED(-) --> GND    出力=刺激器 ch1 に直列
#   GP15(物理20) --330Ω--> 241B LED(+) / LED(-) --> GND    出力=刺激器 ch2（マーカー）
# ------------------------------------------------------------------------------------
import network, socket, time, json, machine
from machine import Pin

VERSION = "wifi-easy-1.0"

# ---------------- 設定 ----------------
PARAM_FILE = "okimo_wifi.json"
DEFAULTS = {
    "out_pin": 14, "mark_pin": 15, "active_high": 1,
    "dot": 250,            # 短点 ms（EASY はリズムの粗密が肝なので少し長め）
    "dash_ratio": 3,       # 長点 = dot × 3
    "gap_units": 3,        # 文字の後ろの間（短点単位）
    "repeats": 2,          # 1回の提示で符号を何回繰り返すか
    "count_repeats": 2,    # 人数（数字）の繰り返し回数
    "count_num_gap": 5,    # 複数桁のときの数字間の間（短点単位）
    "max_on_ms": 3000,
    "mark_mode": 1,        # 0=打たない 1=提示開始で1回
    "mark_ms": 100,
    # 方向→符号（EASY）。ここを変えれば割り当てを変更できる
    "letter_L": "S", "letter_C": "K", "letter_R": "M",
    "ap_ssid": "OKIMO", "ap_pass": "okimo1234",
}
P = dict(DEFAULTS)
def load_params():
    global P
    try:
        with open(PARAM_FILE) as f: d = json.load(f)
        c = dict(DEFAULTS)
        for k in DEFAULTS:
            if k in d: c[k] = d[k]
        P = c
    except Exception:
        P = dict(DEFAULTS)
def save_params():
    with open(PARAM_FILE, "w") as f: json.dump(P, f)
load_params()

MORSE = {'A':'.-','B':'-...','C':'-.-.','D':'-..','E':'.','F':'..-.','G':'--.','H':'....',
         'I':'..','J':'.---','K':'-.-','L':'.-..','M':'--','N':'-.','O':'---','P':'.--.',
         'Q':'--.-','R':'.-.','S':'...','T':'-','U':'..-','V':'...-','W':'.--','X':'-..-',
         'Y':'-.--','Z':'--..'}
DIGITS = {'0':'-----','1':'.----','2':'..---','3':'...--','4':'....-',
          '5':'.....','6':'-....','7':'--...','8':'---..','9':'----.'}

# ---------------- 出力 ----------------
try: led = Pin("LED", Pin.OUT)      # Pico 2 W の本体 LED は "LED"
except Exception:
    try: led = Pin(25, Pin.OUT)
    except Exception: led = None
out  = Pin(int(P["out_pin"]),  Pin.OUT)
mark = Pin(int(P["mark_pin"]), Pin.OUT)
def _lvl(v): return 1 if (v if P["active_high"] else (not v)) else 0
def set_out(v):
    out.value(_lvl(v))
    if led:
        try: led.value(1 if v else 0)
        except Exception: pass
def set_mark(v): mark.value(_lvl(v))
set_out(0); set_mark(0)

def letter_for(z):
    return {"L": P["letter_L"], "C": P["letter_C"], "R": P["letter_R"]}.get(z, "K")

def seq_for(letter, speed=1.0):
    """符号 → [on,off,on,off,...] ms 列（repeats 回）。speed>1 で短点・長点・休止すべてを速める"""
    u = int(P["dot"]) / float(speed); code = MORSE.get(letter.upper(), "-.-"); seq = []
    for r in range(int(P["repeats"])):
        for i, c in enumerate(code):
            seq.append(int(u * int(P["dash_ratio"])) if c == "-" else int(u))   # 長点/短点
            seq.append(int(u) if i < len(code) - 1 else int(int(P["gap_units"]) * u))  # 点間/字間
    return seq

def play_seq(seq, do_mark=True):
    """seq を今すぐ打つ（ブロッキング。1提示は数秒なので許容）"""
    if do_mark and int(P["mark_mode"]) == 1:
        set_mark(1); time.sleep_ms(int(P["mark_ms"])); set_mark(0)
    on = True
    for ms in seq:
        set_out(on); time.sleep_ms(min(int(ms), int(P["max_on_ms"]) if on else 60000))
        on = not on
    set_out(0)

def play_zone(z, speed=1.0):
    play_seq(seq_for(letter_for(z), speed))

def digit_seq(code, u):
    """1つの数字コード(.----等) → on/off ms 列"""
    seq = []
    for i, c in enumerate(code):
        seq.append(int(u * int(P["dash_ratio"])) if c == "-" else int(u))
        seq.append(int(u) if i < len(code) - 1 else int(int(P["gap_units"]) * u))
    return seq

def count_seq(n, speed=1.0):
    """人数 n（文字列可、複数桁対応）→ 数字モールスの on/off 列（count_repeats 回）"""
    u = int(P["dot"]) / float(speed); digits = str(n); seq = []
    for r in range(int(P["count_repeats"])):
        for j, ch in enumerate(digits):
            if ch in DIGITS:
                seq += digit_seq(DIGITS[ch], u)
                if j < len(digits) - 1:
                    seq.append(int(int(P["count_num_gap"]) * u))  # 数字間の間
        if r < int(P["count_repeats"]) - 1:
            seq.append(int(int(P["count_num_gap"]) * u))          # 繰り返し間の間
    return seq

def play_count(n, speed=1.0):
    play_seq(count_seq(n, speed))

# ---------------- Wi-Fi AP ----------------
def start_ap():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try: ap.config(essid=P["ap_ssid"], password=P["ap_pass"])
    except Exception: ap.config(essid=P["ap_ssid"])
    for _ in range(20):
        if ap.active(): break
        time.sleep_ms(200)
    print("AP:", P["ap_ssid"], ap.ifconfig())
    return ap

ap = start_ap()

PAGE = """<!DOCTYPE html><html lang=ja><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>OKIMO EASY (Pico)</title>
<style>body{font-family:sans-serif;margin:16px;font-size:18px}
button{font-size:20px;padding:14px 20px;margin:6px;border-radius:12px;border:1px solid #888}
#log{margin-top:12px;color:#555;font-size:14px;white-space:pre-wrap}</style></head><body>
<h2>OKIMO EASY 稼働中</h2>
<p>方向テスト（腰に通電が来ます）:</p>
<button onclick=z('L')>左 S ...</button>
<button onclick=z('C')>正面 K -.-</button>
<button onclick=z('R')>右 M --</button><br>
<button onclick="g('/count?n=1')">1人</button>
<button onclick="g('/count?n=2')">2人</button>
<button onclick="g('/count?n=3')">3人</button><br>
<button onclick=g('/stim?ms=800')>単発通電</button>
<button onclick=g('/mark')>マーク</button>
<button onclick=g('/stop')>停止</button>
<div id=log></div>
<script>
function log(t){document.getElementById('log').textContent=t+"\\n"+document.getElementById('log').textContent}
async function g(p){try{const r=await fetch(p);log(p+' -> '+(await r.text()).trim())}catch(e){log('ERR '+e)}}
function z(d){g('/z?d='+d)}
</script></body></html>"""

def parse_qs(path):
    q = {}
    if "?" in path:
        _, qs = path.split("?", 1)
        for kv in qs.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1); q[k] = v
    return q

def handle(path):
    p = path.split("?")[0]
    q = parse_qs(path)
    if p == "/" or p == "/index.html":
        return ("text/html", PAGE)
    if p == "/ping":
        return ("text/plain", "PONG " + VERSION)
    if p == "/z":
        d = q.get("d", "C").upper()[:1]
        speed = 2.0 if q.get("fast", "0") in ("1", "true") else float(q.get("speed", "1") or "1")
        if d in ("L", "C", "R"): play_zone(d, speed); return ("text/plain", "OK z=%s x%.1f" % (d, speed))
        return ("text/plain", "ERR d")
    if p in ("/L", "/C", "/R"):
        d = p[1]; play_zone(d); return ("text/plain", "OK " + d)
    if p == "/count":
        n = q.get("n", "1")
        if n.isdigit() and len(n) <= 3:
            play_count(n); return ("text/plain", "OK count=" + n)
        return ("text/plain", "ERR n")
    if p == "/stim":
        ms = int(q.get("ms", "800")); play_seq([min(ms, int(P["max_on_ms"])), 10], do_mark=True)
        return ("text/plain", "OK stim " + str(ms))
    if p == "/mark":
        set_mark(1); time.sleep_ms(int(P["mark_ms"])); set_mark(0); return ("text/plain", "OK mark")
    if p == "/stop":
        set_out(0); set_mark(0); return ("text/plain", "OK stop")
    if p == "/get":
        return ("application/json", json.dumps(P))
    if p == "/set":
        k = q.get("k", ""); v = q.get("v", "")
        if k in DEFAULTS:
            try:
                P[k] = v if isinstance(DEFAULTS[k], str) else type(DEFAULTS[k])(float(v))
                return ("text/plain", "OK %s=%s" % (k, P[k]))
            except Exception as e:
                return ("text/plain", "ERR val " + str(e))
        return ("text/plain", "ERR key")
    if p == "/save":
        save_params(); return ("text/plain", "OK saved")
    return ("text/plain", "ERR path " + p)

# ---------------- HTTP サーバ ----------------
addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(addr); s.listen(4)
print("OKIMO WiFi EASY READY", VERSION, "-> http://192.168.4.1/")

while True:
    try:
        cl, a = s.accept()
        cl.settimeout(3)
        req = b""
        while b"\r\n\r\n" not in req and len(req) < 1024:
            chunk = cl.recv(256)
            if not chunk: break
            req += chunk
        line = req.split(b"\r\n", 1)[0].decode("utf-8", "ignore")
        path = "/"
        parts = line.split(" ")
        if len(parts) >= 2: path = parts[1]
        ctype, body = handle(path)
        cl.send("HTTP/1.1 200 OK\r\nContent-Type: %s\r\nConnection: close\r\nAccess-Control-Allow-Origin: *\r\n\r\n" % ctype)
        cl.send(body)
        cl.close()
    except Exception as e:
        try:
            cl.send("HTTP/1.1 500 ERR\r\nConnection: close\r\n\r\n" + repr(e)); cl.close()
        except Exception: pass
