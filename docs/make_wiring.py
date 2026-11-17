"""Generates docs/wiring.html (schematic + wiring tables) from the pin map.

Pin assignments come from firmware/node/config.h; edit there first, then here.
Run: python docs/make_wiring.py
"""
from pathlib import Path

# Net -> (label, css color var)
NETS = {
    "3V3": ("3V3", "--n-pwr"), "GND": ("GND", "--n-gnd"),
    "BCLK0": ("BCLK0 · IO4", "--n-bclk"), "WS0": ("WS0 · IO5", "--n-ws"), "SD0": ("SD0 · IO6", "--n-sd"),
    "BCLK1": ("BCLK1 · IO7", "--n-bclk"), "WS1": ("WS1 · IO15", "--n-ws"), "SD1": ("SD1 · IO16", "--n-sd"),
    "SCK": ("SCK · IO12", "--n-spi"), "MISO": ("MISO · IO13", "--n-spi"), "MOSI": ("MOSI · IO11", "--n-spi"),
    "CS": ("CS · IO10", "--n-ctl"), "RST": ("RST · IO9", "--n-ctl"), "DIO0": ("G0 · IO8", "--n-ctl"),
}

# ESP32-S3-DevKitC-1 header J1 (left side, USB ports at the bottom), top -> bottom
J1 = ["3V3", "3V3", "RST", "4", "5", "6", "7", "15", "16", "17", "18", "8", "3", "46",
      "9", "10", "11", "12", "13", "14", "5V", "GND"]
J1_NET = {"3V3": "3V3", "4": "BCLK0", "5": "WS0", "6": "SD0", "7": "BCLK1", "15": "WS1",
          "16": "SD1", "8": "DIO0", "9": "RST", "10": "CS", "11": "MOSI", "12": "SCK",
          "13": "MISO", "GND": "GND"}

MIC_PINS = ["3V", "GND", "BCLK", "DOUT", "LRCL", "SEL"]
MICS = [  # name, bus, side
    ("M0", 0, "L"), ("M1", 0, "R"), ("M2", 1, "L"), ("M3", 1, "R"),
]
LORA_PINS = [("VIN", "3V3"), ("GND", "GND"), ("EN", None), ("G0", "DIO0"), ("SCK", "SCK"),
             ("MISO", "MISO"), ("MOSI", "MOSI"), ("CS", "CS"), ("RST", "RST")]


def mic_net(pin, bus, side):
    return {"3V": "3V3", "GND": "GND", "BCLK": f"BCLK{bus}", "DOUT": f"SD{bus}",
            "LRCL": f"WS{bus}", "SEL": "GND" if side == "L" else "3V3"}[pin]


def tag(x, y, net, anchor="end"):
    label, var = NETS[net]
    w = 10 + 7.0 * len(label)
    rx = x - w if anchor == "end" else x
    return (f'<g class="tag"><rect x="{rx:.1f}" y="{y-10}" width="{w:.1f}" height="20" rx="10" '
            f'style="stroke:var({var});fill:var({var})" fill-opacity="0.16"/>'
            f'<text x="{rx + w/2:.1f}" y="{y+4}" text-anchor="middle">{label}</text></g>')


def svg():
    out = []
    W, H = 1080, 672
    # --- ESP32 board
    bx, by, pitch = 470, 70, 24
    bh = pitch * len(J1) + 20
    out.append(f'<rect class="board" x="{bx}" y="{by-20}" width="170" height="{bh+20}" rx="6"/>')
    out.append(f'<text class="part" x="{bx+85}" y="{by-30}" text-anchor="middle">ESP32-S3-DevKitC-1</text>')
    out.append(f'<text class="sub" x="{bx+100}" y="{by+bh/2-6}" text-anchor="middle">header J1</text>')
    out.append(f'<text class="sub" x="{bx+100}" y="{by+bh/2+10}" text-anchor="middle">(left edge)</text>')
    out.append(f'<rect class="usb" x="{bx+40}" y="{by+bh-6}" width="30" height="14" rx="3"/>'
               f'<rect class="usb" x="{bx+100}" y="{by+bh-6}" width="30" height="14" rx="3"/>'
               f'<text class="tiny" x="{bx+55}" y="{by+bh+22}" text-anchor="middle">COM</text>'
               f'<text class="tiny" x="{bx+115}" y="{by+bh+22}" text-anchor="middle">USB</text>')
    for i, p in enumerate(J1):
        y = by + i * pitch
        net = J1_NET.get(p)
        if p == "3V3" and i == 1:
            net = None  # one 3V3 pin is enough
        cls = "pin used" if net else "pin"
        lbl = p if not p.isdigit() else f"IO{p}"
        out.append(f'<circle class="{cls}" cx="{bx}" cy="{y}" r="4"/>')
        out.append(f'<text class="pinlbl{" on" if net else ""}" x="{bx+10}" y="{y+4}">{lbl}</text>')
        if net:
            out.append(f'<line class="wire" x1="{bx-4}" y1="{y}" x2="{bx-36}" y2="{y}" style="stroke:var({NETS[net][1]})"/>')
            out.append(tag(bx - 40, y, net))
    # --- mics (left column)
    for m, (name, bus, side) in enumerate(MICS):
        mx, my = 20, 40 + m * 146
        out.append(f'<rect class="part-box" x="{mx}" y="{my}" width="150" height="{len(MIC_PINS)*18+28}" rx="6"/>')
        out.append(f'<text class="part" x="{mx+10}" y="{my+18}">{name}</text>')
        out.append(f'<text class="sub" x="{mx+140}" y="{my+18}" text-anchor="end">bus {bus} · {"left" if side=="L" else "right"}</text>')
        for j, p in enumerate(MIC_PINS):
            y = my + 36 + j * 18
            net = mic_net(p, bus, side)
            out.append(f'<text class="pinlbl on" x="{mx+140}" y="{y+4}" text-anchor="end">{p}</text>')
            out.append(f'<circle class="pin used" cx="{mx+150}" cy="{y}" r="3.5"/>')
            out.append(f'<line class="wire" x1="{mx+154}" y1="{y}" x2="{mx+176}" y2="{y}" style="stroke:var({NETS[net][1]})"/>')
            out.append(tag(mx + 178, y, net, anchor="start"))
    # --- LoRa (right)
    lx, ly = 860, 200
    out.append(f'<rect class="part-box" x="{lx}" y="{ly}" width="170" height="{len(LORA_PINS)*22+40}" rx="6"/>')
    out.append(f'<text class="part" x="{lx+85}" y="{ly-12}" text-anchor="middle">RFM95W 915 MHz</text>')
    for j, (p, net) in enumerate(LORA_PINS):
        y = ly + 24 + j * 22
        out.append(f'<circle class="pin{" used" if net else ""}" cx="{lx}" cy="{y}" r="3.5"/>')
        out.append(f'<text class="pinlbl{" on" if net else ""}" x="{lx+10}" y="{y+4}">{p}</text>')
        if net:
            out.append(f'<line class="wire" x1="{lx-4}" y1="{y}" x2="{lx-24}" y2="{y}" style="stroke:var({NETS[net][1]})"/>')
            out.append(tag(lx - 26, y, net))
        else:
            out.append(f'<text class="tiny" x="{lx-10}" y="{y+4}" text-anchor="end">leave open</text>')
    ay = ly + len(LORA_PINS) * 22 + 40
    out.append(f'<text class="pinlbl on" x="{lx+120}" y="{ly+24+4}">ANT</text>')
    out.append(f'<path class="ant" d="M{lx+170} {ly+24} h20 v-110"/>')
    out.append(f'<text class="sub" x="{lx+190}" y="{ly-94}" text-anchor="end">78 mm wire antenna</text>')
    out.append(f'<text class="tiny" x="{lx+85}" y="{ay+18}" text-anchor="middle">VIN to 3V3, never 5V:</text>')
    out.append(f'<text class="tiny" x="{lx+85}" y="{ay+32}" text-anchor="middle">VIN sets the SPI logic level</text>')
    return (f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Node schematic: four ICS-43434 microphones '
            f'and an RFM95W radio wired to an ESP32-S3 by net label">' + "".join(out) + "</svg>")


def row(cells, head=False):
    t = "th" if head else "td"
    return "<tr>" + "".join(f"<{t}>{c}</{t}>" for c in cells) + "</tr>"


def chip(net):
    label, var = NETS[net]
    return f'<span class="chip" style="--c:var({var})">{label}</span>'


def mic_table():
    rows = [row(["Mic pin", "M0 (bus 0, left)", "M1 (bus 0, right)", "M2 (bus 1, left)", "M3 (bus 1, right)"], True)]
    for p in MIC_PINS:
        rows.append(row([f"<code>{p}</code>"] + [chip(mic_net(p, b, s)) for _, b, s in MICS]))
    return "<table>" + "".join(rows) + "</table>"


def lora_table():
    rows = [row(["RFM95W pin", "ESP32-S3 pin", "Notes"], True)]
    notes = {"VIN": "3V3 pin, not 5V", "GND": "", "EN": "Leave open (pulled up on the board)",
             "G0": "Interrupt: tells the ESP32 a packet finished", "SCK": "", "MISO": "",
             "MOSI": "", "CS": "", "RST": ""}
    for p, net in LORA_PINS:
        rows.append(row([f"<code>{p}</code>", chip(net) if net else "—", notes[p]]))
    rows.append(row(["<code>ANT</code>", "—", "Solder a 78 mm straight wire to the ANT pad. Never transmit without it."]))
    return "<table>" + "".join(rows) + "</table>"


HTML = """<title>Silent Sentinel Wiring</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@500;600&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
/* Layout: engineering sheet. Title block, full-width schematic, then build tables in reading order. */
:root {
  --bg: #f2f5f6; --panel: #ffffff; --fg: #14202a; --muted: #566674; --line: #c6d1d8; --accent: #1d5fb8;
  --warn-bg: #fff3d6; --warn-fg: #6b4a00;
  --n-pwr: #d23b2f; --n-gnd: #3b4650; --n-bclk: #c98a00; --n-ws: #2f8f46; --n-sd: #2a6fd6;
  --n-spi: #8a4fc4; --n-ctl: #c2477e;
  --display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0d1318; --panel: #151e25; --fg: #e2e9ee; --muted: #94a3af; --line: #2c3a45; --accent: #6ea8ff;
  --warn-bg: #3a2e10; --warn-fg: #f3d58a;
  --n-pwr: #ff6b5e; --n-gnd: #a9b6c1; --n-bclk: #f0b429; --n-ws: #5cc77a; --n-sd: #6ea8ff;
  --n-spi: #b98cf0; --n-ctl: #f07bb0; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0d1318; --panel: #151e25; --fg: #e2e9ee; --muted: #94a3af; --line: #2c3a45; --accent: #6ea8ff;
  --warn-bg: #3a2e10; --warn-fg: #f3d58a;
  --n-pwr: #ff6b5e; --n-gnd: #a9b6c1; --n-bclk: #f0b429; --n-ws: #5cc77a; --n-sd: #6ea8ff;
  --n-spi: #b98cf0; --n-ctl: #f07bb0; color-scheme: dark }
body { background: var(--bg); color: var(--fg); font-family: var(--body); font-size: 15px; line-height: 1.55; }
.wrap { max-width: 1120px; margin: 0 auto; padding-block: 28px 64px;
  padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
  display: grid; gap: 28px; }
header { display: grid; grid-template-columns: 1fr auto; gap: 8px 24px; align-items: end;
  border-bottom: 2px solid var(--fg); padding-bottom: 14px; }
h1 { font-family: var(--display); font-weight: 600; font-size: clamp(28px, 5vw, 40px); line-height: 1.05; margin: 0; text-wrap: balance; }
h2 { font-family: var(--display); font-weight: 600; font-size: 22px; margin: 0 0 10px; text-wrap: balance; }
.meta { font-family: var(--mono); font-size: 12px; color: var(--muted); text-align: right; display: grid; gap: 2px; }
.lede { color: var(--muted); max-width: 68ch; margin: 6px 0 0; grid-column: 1 / -1; }
section { min-width: 0; }
.sheet { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow-x: auto; padding: 8px; }
.sheet svg { display: block; min-width: 860px; width: 100%; height: auto; }
svg text { font-family: var(--mono); font-size: 11.5px; fill: var(--fg); }
svg .part { font-family: var(--display); font-size: 15px; font-weight: 600; }
svg .sub { fill: var(--muted); font-size: 11px; }
svg .tiny { fill: var(--muted); font-size: 10.5px; }
svg .pinlbl { fill: var(--muted); }
svg .pinlbl.on { fill: var(--fg); font-weight: 500; }
svg .board { fill: var(--bg); stroke: var(--fg); stroke-width: 1.5; }
svg .part-box { fill: var(--bg); stroke: var(--fg); stroke-width: 1.2; }
svg .usb { fill: var(--panel); stroke: var(--muted); }
svg .pin { fill: var(--panel); stroke: var(--muted); stroke-width: 1.2; }
svg .pin.used { fill: var(--fg); stroke: var(--fg); }
svg .wire { stroke-width: 2.5; stroke-linecap: round; }
svg .tag rect { stroke-width: 1.4; }
svg .tag text { font-size: 11px; font-weight: 500; }
svg .ant { fill: none; stroke: var(--fg); stroke-width: 2; stroke-dasharray: 4 3; }
.cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 480px), 1fr)); gap: 28px; }
.tbl { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-family: var(--display); font-weight: 600; font-size: 13px; letter-spacing: .03em; color: var(--muted); }
code, .chip { font-family: var(--mono); font-size: 13px; }
.chip { display: inline-block; white-space: nowrap; padding: 1px 9px; border-radius: 99px;
  border: 1.4px solid var(--c); background: color-mix(in srgb, var(--c) 15%, transparent); }
.note { background: var(--warn-bg); color: var(--warn-fg); border-radius: 8px; padding: 12px 16px; }
.note strong { font-weight: 600; }
ol, ul { margin: 0; padding-left: 22px; display: grid; gap: 8px; }
li { max-width: 72ch; }
.legend { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
p { margin: 0 0 10px; max-width: 72ch; }
</style>
<div class="wrap">
<header>
  <div><h1>Silent Sentinel node wiring</h1></div>
  <div class="meta"><span>REV A1 · 2026-11-17</span><span>firmware/node/config.h</span></div>
  <p class="lede">One listening node: ESP32-S3-DevKitC-1 N16R8, four ICS-43434 I2S microphones on two buses, and an RFM95W LoRa radio. Wires are drawn as net labels: every tag with the same name is one wire run. The base receiver is the same build with the microphones left off.</p>
</header>

<section>
  <h2>Schematic</h2>
  <div class="sheet">%SVG%</div>
  <div class="legend">
    <span class="chip" style="--c:var(--n-pwr)">3V3 power</span>
    <span class="chip" style="--c:var(--n-gnd)">ground</span>
    <span class="chip" style="--c:var(--n-bclk)">I2S bit clock</span>
    <span class="chip" style="--c:var(--n-ws)">I2S word select</span>
    <span class="chip" style="--c:var(--n-sd)">I2S data</span>
    <span class="chip" style="--c:var(--n-spi)">SPI</span>
    <span class="chip" style="--c:var(--n-ctl)">radio control</span>
  </div>
</section>

<div class="note"><strong>3.3 V only.</strong> The microphones are 3.6 V max, and the RFM95W drives its SPI lines at whatever voltage is on VIN. Feed both from the DevKit's <code>3V3</code> pin. Nothing goes to <code>5V</code>.</div>

<div class="cols">
<section>
  <h2>Microphones</h2>
  <p>Each bus carries two mics that share BCLK, WS and the data line. <code>SEL</code> picks the half of the frame a mic talks in: tied to GND it is the left channel, tied to 3V3 the right. Getting SEL wrong makes two mics talk over each other.</p>
  <div class="tbl">%MICS%</div>
</section>
<section>
  <h2>LoRa radio</h2>
  <p>The RFM95W uses SPI plus two control lines. G0 is the radio's interrupt line; RST lets the ESP32 reset it at boot.</p>
  <div class="tbl">%LORA%</div>
</section>
</div>

<div class="cols">
<section>
  <h2>Build order</h2>
  <ol>
    <li>Solder headers on the 4 mic breakouts and the RFM95W. Solder a 78 mm straight wire to the RFM95W <code>ANT</code> pad.</li>
    <li>Seat the DevKit across the breadboard's center channel with its USB ports at the bottom, so header J1 matches the drawing. Run 3V3 and GND to the breadboard rails.</li>
    <li>Plug the DevKit into the laptop (either USB-C port) and flash <code>firmware/node</code>. A new board runs a factory LED demo: for the first flash, hold <strong>BOOT</strong>, tap <strong>RST</strong>, release BOOT. With nothing else wired, the console prints a <code>WARN</code> line about the radio. That confirms the board and toolchain work.</li>
    <li>Wire the RFM95W. Reboot, type <code>info</code>: it should say <code>lora=ok</code>.</li>
    <li>Wire bus 0 (M0, M1). Type <code>debug 1</code> and whistle or play a tone: the level column should jump.</li>
    <li>Wire bus 1 (M2, M3) the same way on IO7 / IO15 / IO16.</li>
    <li>Set the node number with <code>id 1</code> … <code>id 6</code>. It is saved in flash.</li>
  </ol>
</section>
<section>
  <h2>Placement on the board</h2>
  <ul>
    <li>Spread the four mics in a square about 5 cm on a side, sound ports facing up and clear of wires. The ICS-43434 hears through a hole in its PCB, so don't cover it.</li>
    <li>Keep mic wires short (under ~15 cm). Long I2S clock runs pick up noise.</li>
    <li>Point the antenna straight up and keep it away from the mic wiring.</li>
    <li>Outdoors, a foam windscreen over each mic matters more than anything in software.</li>
  </ul>
  <h2 style="margin-top:22px">Base receiver</h2>
  <p>A second DevKit with only the RFM95W wired, exactly as in the table. Flash <code>firmware/base_rx</code> and leave it plugged into the base laptop.</p>
</section>
</div>
</div>
"""

if __name__ == "__main__":
    out = HTML.replace("%SVG%", svg()).replace("%MICS%", mic_table()).replace("%LORA%", lora_table())
    p = Path(__file__).with_name("wiring.html")
    p.write_text(out)
    print("wrote", p)
