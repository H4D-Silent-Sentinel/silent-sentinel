"""Generates docs/breadboard.html: hole-by-hole layout for the first node on a
full-size (63-row) breadboard. Pins match firmware/node/config.h.
Run: python docs/make_breadboard.py
"""
from pathlib import Path

P = 14  # hole pitch, px
TOP = 56
COLS = "abcdefghij"


def col_x(c: str) -> float:
    base = 80 + 3 * P
    i = COLS.index(c)
    return base + i * P + (2 * P if i >= 5 else 0)  # centre channel between e and f


RAIL = {"L-": 80, "L+": 80 + P, "R+": col_x("j") + 3 * P, "R-": col_x("j") + 4 * P}


def row_y(r: int) -> float:
    return TOP + (r - 1) * P


def hole(spec: str):
    """'a43' or 'L+12'."""
    if spec[:2] in RAIL:
        return RAIL[spec[:2]], row_y(int(spec[2:]))
    return col_x(spec[0]), row_y(int(spec[1:]))


# ESP32-S3-DevKitC-1 header J1, top -> bottom (USB ports at the bottom)
J1 = ["3V3", "3V3", "RST", "IO4", "IO5", "IO6", "IO7", "IO15", "IO16", "IO17", "IO18", "IO8", "IO3",
      "IO46", "IO9", "IO10", "IO11", "IO12", "IO13", "IO14", "5V", "GND"]
ESP_TOP = 40  # J1 pin 1 (3V3) sits in b40 ... GND in b61
ESP_ROW = {name if name not in ("3V3",) else f"3V3_{i}": ESP_TOP + i for i, name in enumerate(J1)}
ESP_ROW["3V3"] = ESP_TOP


def esp(pin):  # free hole beside an ESP32 pin
    return f"a{ESP_ROW[pin]}"


MIC_PINS = ["SEL", "LRCL", "DOUT", "BCLK", "GND", "3V"]  # order printed on the board (team-verified)
M_TOP = 1
LORA_PINS = ["VIN", "GND", "EN", "G0", "SCK", "MISO", "MOSI", "CS", "RST"]
L_TOP = 21

# Demo build (17 Nov): one mic (M1) in j1-j6 + RFM95W in j21-j29, wires from column h
# (h is two holes from the parts, so jumper heads fit). No rails used.
# (from, to, color var, colour name, label, step)
WIRES = [
    ("h6", esp("3V3_1"), "--c-red", "Red", "Mic 3V → ESP32 3V3", 1),
    ("h5", esp("GND"), "--c-black", "Black", "Mic GND → ESP32 GND", 1),
    ("h1", esp("3V3"), "--c-orange", "Orange", "Mic SEL → 3V3 (sets it as the right-channel mic)", 1),
    ("h4", esp("IO4"), "--c-yellow", "Yellow", "BCLK → IO4", 1),
    ("h2", esp("IO5"), "--c-green", "Green", "LRCL → IO5", 1),
    ("h3", esp("IO6"), "--c-blue", "Blue", "DOUT → IO6", 1),
    ("f6", f"f{L_TOP}", "--c-red", "Red", "Radio VIN ← mic 3V row", 2),
    ("f5", f"f{L_TOP + 1}", "--c-black", "Black", "Radio GND ← mic GND row", 2),
    (f"h{L_TOP + 3}", esp("IO8"), "--c-white", "White", "G0 → IO8", 2),
    (f"h{L_TOP + 4}", esp("IO12"), "--c-purple", "Purple", "SCK → IO12", 2),
    (f"h{L_TOP + 5}", esp("IO13"), "--c-gray", "Gray", "MISO → IO13", 2),
    (f"h{L_TOP + 6}", esp("IO11"), "--c-blue", "Blue", "MOSI → IO11", 2),
    (f"h{L_TOP + 7}", esp("IO10"), "--c-orange", "Orange", "CS → IO10", 2),
    (f"h{L_TOP + 8}", esp("IO9"), "--c-yellow", "Yellow", "RST → IO9", 2),
]


def svg():
    o = []
    W = 470
    H = int(row_y(63) + 60)
    bx0, bx1 = RAIL["L-"] - 18, RAIL["R-"] + 18
    o.append(f'<rect class="bb" x="{bx0}" y="{TOP-30}" width="{bx1-bx0}" height="{row_y(63)-TOP+50}" rx="8"/>')
    o.append(f'<rect class="channel" x="{col_x("e")+P*0.55}" y="{TOP-16}" width="{P*0.9}" height="{row_y(63)-TOP+32}" rx="3"/>')
    # rail lines
    for k, cls in (("L-", "neg"), ("L+", "pos"), ("R+", "pos"), ("R-", "neg")):
        o.append(f'<line class="rail {cls}" x1="{RAIL[k]}" y1="{TOP-14}" x2="{RAIL[k]}" y2="{row_y(63)+14}"/>')
        o.append(f'<text class="raillbl {cls}" x="{RAIL[k]}" y="{TOP-18}" text-anchor="middle">{k[1]}</text>')
    # holes
    for r in range(1, 64):
        y = row_y(r)
        for c in COLS:
            o.append(f'<circle class="hole" cx="{col_x(c)}" cy="{y}" r="2.2"/>')
        for k in RAIL:
            o.append(f'<circle class="hole" cx="{RAIL[k]}" cy="{y}" r="2.2"/>')
        if r == 1 or r % 5 == 0:
            o.append(f'<text class="rown" x="{col_x("a")-14}" y="{y+3.5}" text-anchor="end">{r}</text>')
            o.append(f'<text class="rown" x="{col_x("j")+14}" y="{y+3.5}">{r}</text>')
    for c in COLS:
        o.append(f'<text class="coln" x="{col_x(c)}" y="{TOP-18}" text-anchor="middle">{c}</text>')

    # ESP32 body: J1 in column b, PCB covers to the right; USB end hangs past row 61
    ex0, ex1 = col_x("b") - 9, col_x("j") + 9
    ey0, ey1 = row_y(ESP_TOP) - 12, row_y(ESP_TOP + 21) + 30
    o.append(f'<rect class="esp" x="{ex0}" y="{ey0}" width="{ex1-ex0}" height="{ey1-ey0}" rx="5"/>')
    o.append(f'<rect class="can" x="{col_x("e")}" y="{ey0+8}" width="{col_x("i")-col_x("e")+4}" height="{P*6}" rx="3"/>')
    o.append(f'<text class="parttxt" x="{(col_x("e")+col_x("i"))/2+2}" y="{ey0+8+P*3+4}" text-anchor="middle">ESP32-S3</text>')
    for i, name in enumerate(J1):
        x, y = col_x("b"), row_y(ESP_TOP + i)
        used = any(w[1] == f"a{ESP_TOP+i}" for w in WIRES)
        o.append(f'<rect class="pinsq{" on" if used else ""}" x="{x-3.5}" y="{y-3.5}" width="7" height="7"/>')
        o.append(f'<text class="pintxt{" on" if used else ""}" x="{x+8}" y="{y+3.5}">{name}</text>')
        o.append(f'<rect class="pinsq" x="{col_x("j")-3.5}" y="{y-3.5}" width="7" height="7"/>')
    for k, lab in ((0, "COM"), (1, "USB")):
        ux = col_x("d") + k * (P * 4.5)
        o.append(f'<rect class="usb" x="{ux}" y="{ey1-8}" width="{P*2.4}" height="16" rx="3"/>')
        o.append(f'<text class="tiny" x="{ux+P*1.2}" y="{ey1+20}" text-anchor="middle">{lab}</text>')
    o.append(f'<text class="parttxt" x="{(col_x("d")+col_x("i"))/2}" y="{row_y(52)}" text-anchor="middle">DevKitC-1</text>')
    o.append(f'<text class="tiny" x="{(col_x("d")+col_x("i"))/2}" y="{row_y(53)+2}" text-anchor="middle">J1 in column b</text>')

    # mics: header in column a (M0) / j (M1), PCB hangs out over the rails
    def mic(name, col, side):
        x = col_x(col)
        y0, y1 = row_y(M_TOP) - 10, row_y(M_TOP + 5) + 10
        bw = P * 3.4
        rx = x - bw + 7 if side == "L" else x - 7
        o.append(f'<rect class="mic" x="{rx}" y="{y0}" width="{bw}" height="{y1-y0}" rx="4"/>')
        cx = rx + bw / 2 + (-6 if side == "L" else 6)
        o.append(f'<circle class="port" cx="{cx}" cy="{(y0+y1)/2}" r="4"/>')
        o.append(f'<text class="partlbl" x="{rx + bw/2}" y="{y0-5}" text-anchor="middle">{name}</text>')
        for i, p in enumerate(MIC_PINS):
            y = row_y(M_TOP + i)
            o.append(f'<rect class="pinsq on" x="{x-3.5}" y="{y-3.5}" width="7" height="7"/>')
            tx = x - 9 if side == "L" else x + 9
            o.append(f'<text class="pintxt on micpin" x="{tx}" y="{y+3}" text-anchor="{"end" if side=="L" else "start"}">{p}</text>')
    mic("MIC", "j", "R")

    # LoRa: 9-pin header in column j, module hangs out to the right
    x = col_x("j")
    y0, y1 = row_y(L_TOP) - 10, row_y(L_TOP + 8) + 10
    bw = P * 6.2
    o.append(f'<rect class="lora" x="{x-7}" y="{y0}" width="{bw}" height="{y1-y0}" rx="4"/>')
    o.append(f'<text class="parttxt" x="{x-7+bw-8}" y="{(y0+y1)/2+4}" text-anchor="end" transform="rotate(-90 {x-7+bw-8} {(y0+y1)/2+4})">RFM95W</text>')
    for i, p in enumerate(LORA_PINS):
        y = row_y(L_TOP + i)
        o.append(f'<rect class="pinsq{" on" if p != "EN" else ""}" x="{x-3.5}" y="{y-3.5}" width="7" height="7"/>')
        o.append(f'<text class="pintxt on" x="{x+9}" y="{y+3}">{p}</text>')
    o.append(f'<path class="ant" d="M{x-7+bw} {row_y(L_TOP)} h18 v-70"/>')
    o.append(f'<text class="tiny" x="{x-7+bw+22}" y="{row_y(L_TOP)-74}">78 mm wire</text>')

    # wires
    mic_w = sorted([w for w in WIRES if w[5] == 1], key=lambda w: int(w[1][1:]))
    lora_w = sorted([w for w in WIRES if w[0][0] == "h" and w[5] == 2], key=lambda w: int(w[1][1:]))
    for a, b, var, *_ in WIRES:
        (x1, y1), (x2, y2) = hole(a), hole(b)
        if a[0] == "f" and b[0] == "f":  # radio power taps, run down beside column f
            lane = col_x("f") + (6 if a == "f6" else -6)
            d = f"M{x1} {y1} H{lane} V{y2} H{x2}"
        elif (a, b) in [(w[0], w[1]) for w in mic_w]:  # mic line down the centre channel
            k = [w[1] for w in mic_w].index(b)
            lane = col_x("e") + 6 + k * 4.5
            d = f"M{x1} {y1} H{lane} V{y2} H{x2}"
        else:  # radio line round the left of the board
            k = [w[1] for w in lora_w].index(b)
            lane = RAIL["L-"] - 26 + k * 4.5
            d = f"M{x1} {y1} H{lane} V{y2} H{x2}"
        o.append(f'<path class="wire" d="{d}" style="stroke:var({var})"/>')
        for x, y in ((x1, y1), (x2, y2)):
            o.append(f'<circle class="end" cx="{x}" cy="{y}" r="3.6" style="fill:var({var})"/>')
    return (f'<svg viewBox="-20 0 {W+20} {H}" role="img" aria-label="Breadboard layout for the first Silent Sentinel node">'
            + "".join(o) + "</svg>")


def table():
    steps = {1: "Microphone", 2: "LoRa radio (RFM95W)"}
    out = []
    for st, title in steps.items():
        rows = [w for w in WIRES if w[5] == st]
        out.append(f'<section class="step"><h3><span class="n">{st + 1}</span>{title}: {len(rows)} wires</h3>'
                   '<table><tr><th>Colour</th><th>From</th><th>To</th><th>What it does</th></tr>')
        for a, b, var, cname, lab, _ in rows:
            out.append(f'<tr><td><span class="sw" style="background:var({var})"></span>{cname}</td>'
                       f'<td><code>{a}</code></td><td><code>{b}</code></td><td>{lab}</td></tr>')
        out.append("</table></section>")
    return "".join(out)


HTML = """<title>Silent Sentinel Breadboard</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Layout: build sheet. Board drawing left, hole-by-hole steps right; stacks on phones. */
:root {
  --bg: #f2f5f6; --panel: #ffffff; --fg: #14202a; --muted: #566674; --line: #c6d1d8;
  --bb: #f7f4ec; --bb-edge: #d9d2c0; --hole: #b9b2a2; --channel: #e6e0d0;
  --esp: #1f2a33; --esp-fg: #e8eef2; --can: #9aa6b0; --mic: #2f6f4f; --lora: #2a4f8a; --later: #8a96a0;
  --pos: #d23b2f; --neg: #2a6fd6;
  --w-pwr: #d23b2f; --w-gnd: #20262c; --w-bclk: #d99500; --w-ws: #2f9a4c; --w-sd: #2a6fd6; --w-spi: #8a4fc4; --w-ctl: #c2477e;
  --c-red: #d23b2f; --c-black: #20262c; --c-orange: #ec7a1c; --c-yellow: #e0b100; --c-green: #2f9a4c; --c-blue: #2a6fd6;
  --c-white: #f4f4f0; --c-purple: #8a4fc4; --c-gray: #8a939b;
  --warn-bg: #fff3d6; --warn-fg: #6b4a00;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0d1318; --panel: #151e25; --fg: #e2e9ee; --muted: #94a3af; --line: #2c3a45;
  --bb: #e9e4d6; --bb-edge: #b9b2a2; --warn-bg: #3a2e10; --warn-fg: #f3d58a; --w-gnd: #20262c; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0d1318; --panel: #151e25; --fg: #e2e9ee; --muted: #94a3af; --line: #2c3a45;
  --bb: #e9e4d6; --bb-edge: #b9b2a2; --warn-bg: #3a2e10; --warn-fg: #f3d58a; --w-gnd: #20262c; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 15px; line-height: 1.5; }
.wrap { max-width: 1160px; margin: 0 auto; padding-block: 26px 60px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 22px; }
header { border-bottom: 2px solid var(--fg); padding-bottom: 12px; display: grid; gap: 6px; }
h1 { font-family: var(--display); font-weight: 600; font-size: clamp(26px, 4.6vw, 38px); line-height: 1.05; margin: 0; text-wrap: balance; }
h2, h3 { font-family: var(--display); font-weight: 600; margin: 0; text-wrap: balance; }
h3 { font-size: 19px; display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
.n { display: inline-grid; place-items: center; width: 26px; height: 26px; border-radius: 50%; background: var(--fg); color: var(--bg); font-size: 14px; }
.lede { color: var(--muted); max-width: 70ch; margin: 0; }
.grid { display: grid; grid-template-columns: minmax(0, 520px) minmax(0, 1fr); gap: 28px; align-items: start; }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } }
.sheet { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow-x: auto; padding: 6px; }
.sheet svg { display: block; width: 100%; min-width: 460px; height: auto; }
svg text { font-family: var(--mono); }
svg .bb { fill: var(--bb); stroke: var(--bb-edge); stroke-width: 1.5; }
svg .channel { fill: var(--channel); }
svg .hole { fill: var(--hole); }
svg .rail { stroke-width: 1.6; opacity: .75; }
svg .rail.pos, svg .raillbl.pos { stroke: var(--pos); fill: var(--pos); }
svg .rail.neg, svg .raillbl.neg { stroke: var(--neg); fill: var(--neg); }
svg .raillbl { font-size: 13px; font-weight: 600; stroke: none; }
svg .rown, svg .coln { fill: #7d7666; font-size: 9px; }
svg .esp { fill: var(--esp); opacity: .93; }
svg .can { fill: var(--can); opacity: .55; }
svg .usb { fill: #c8d0d6; stroke: #6b757d; }
svg .parttxt { fill: #ffffff; font-size: 11px; font-weight: 600; font-family: var(--display); }
svg .mic { fill: var(--mic); opacity: .9; }
svg .lora { fill: var(--lora); opacity: .9; }
svg .port { fill: #0b1a12; stroke: #cfe8da; stroke-width: 1; }
svg .later { fill: none; stroke: var(--later); stroke-dasharray: 5 4; stroke-width: 1.2; }
svg .tiny { fill: #5b6670; font-size: 9.5px; }
svg .partlbl { fill: #3a3226; font-size: 12px; font-weight: 600; font-family: var(--display); }
svg .esp ~ .tiny { fill: #5b6670; }
svg .pinsq { fill: #8f8a7c; }
svg .pinsq.on { fill: #e9c46a; stroke: #6b5a1d; stroke-width: .8; }
svg .pintxt { fill: #9aa6b0; font-size: 8.5px; }
svg .pintxt.on { fill: #ffffff; font-weight: 500; }
svg .micpin { fill: #ffffff; }
svg .wire { fill: none; stroke-width: 3; paint-order: stroke; stroke-linecap: round; opacity: .92; }
svg .end { stroke: #3a3226; stroke-width: .8; }
svg .ant { fill: none; stroke: #5b6670; stroke-width: 2; }
.steps { display: grid; gap: 22px; min-width: 0; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: middle; }
th { font-family: var(--display); font-size: 12.5px; letter-spacing: .04em; color: var(--muted); font-weight: 600; }
td:first-child, td:nth-child(2) { white-space: nowrap; }
code { font-family: var(--mono); font-size: 13px; }
.sw { display: inline-block; width: 14px; height: 6px; border-radius: 3px; margin-right: 8px; vertical-align: middle; }
.note { background: var(--warn-bg); color: var(--warn-fg); border-radius: 8px; padding: 12px 16px; }
.note p { margin: 0; }
.note p + p { margin-top: 6px; }
ol { margin: 0; padding-left: 20px; display: grid; gap: 6px; }
li { max-width: 70ch; }
</style>
<div class="wrap">
<header>
  <h1>Silent Sentinel: demo node on the breadboard</h1>
  <p class="lede">Turn the breadboard so row 1 is at the top and column a is on the left. Every jumper below goes from one hole to another, named by column letter and row number (for example <code>a43</code>). Holes in the same row on the same side of the centre channel (a–e, or f–j) are connected inside the board.</p>
</header>

<div class="note">
  <p><strong>Today's demo build:</strong> ESP32-S3, one ICS-43434 mic, one RFM95W radio. Nothing uses the + / − rails, and the KB2040 is not part of this build.</p>
  <p><strong>Wire from column h.</strong> Jumper heads are too thick to sit right beside the parts, and every hole f–i in a row is connected, so <code>h</code> works the same as <code>i</code>.</p>
</div>

<div class="grid">
  <div class="sheet">%SVG%</div>
  <div class="steps">
    <section>
      <h3><span class="n">1</span>Place the parts</h3>
      <ol>
        <li><strong>ESP32-S3:</strong> USB ports toward row 63, left header in <strong>column b, rows 40–61</strong>: <code>b40</code> = 3V3 … <code>b61</code> = GND. Every ESP32 wire plugs into the free hole beside it in column a.</li>
        <li><strong>Mic:</strong> 6 pins in <strong>column j, rows 1–6</strong>, SEL at <code>j1</code>, 3V at <code>j6</code>. Board hangs off the right edge over the rails.</li>
        <li><strong>RFM95W:</strong> 9-pin edge in <strong>column j, rows 21–29</strong>, VIN at <code>j21</code>, RST at <code>j29</code>. Module hangs off the right edge. 78 mm antenna wire on ANT. EN (row 23) stays unconnected.</li>
      </ol>
    </section>
    %TABLE%
    <section>
      <h3><span class="n">4</span>Check it</h3>
      <ol>
        <li>Plug the USB cable into the same port as before. The LED turns blue (listening).</li>
        <li>Tell Claude; it turns on the live readout. Whistle or play the demo drone sound near the mic: the level jumps, and the drone sound turns the LED red within about a second.</li>
      </ol>
    </section>
  </div>
</div>
</div>
"""

if __name__ == "__main__":
    out = HTML.replace("%SVG%", svg()).replace("%TABLE%", table())
    p = Path(__file__).with_name("breadboard.html")
    p.write_text(out)
    print("wrote", p)
