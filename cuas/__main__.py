"""Silent Sentinel base station CLI.

  python -m cuas run    --site sites/x.json --serial /dev/cu.usbserial-XXXX [--map] [--cot URL]
  python -m cuas sim    --site sites/x.json [--map] [--speed 4] [--no-camera]
  python -m cuas listen --site sites/x.json [--map]   # laptop microphone acts as node 1 (demo / backup)
  python -m cuas detect recording.wav           # run the node detector on a recording
  python -m cuas ports                          # list serial ports
"""
from __future__ import annotations

import argparse
import sys
import time


def _outputs(args, base):
    if args.cot:
        from .cot import CotSender
        cot = CotSender(args.cot)
        base.on_track.append(lambda tr: tr["confirmed"] and cot.track(tr, base.site.frame))
        base.on_node.append(lambda node, s: node and cot.node(node, s))
        print(f"cot: sending to {args.cot}")
    if args.map:
        from .mapserver import serve
        serve(base, port=args.map_port)


def cmd_run(args):
    from .base import Base
    from .config import Site
    from .io import CueSender, serial_reader, visual_listener
    site = Site.load(args.site)
    base = Base(site)
    _outputs(args, base)
    if args.serial:
        serial_reader(args.serial, base)
    vis = visual_listener(base, args.visual_port)
    base.on_track.append(CueSender(base, vis.peers, args.jetson or []))
    print(f"Silent Sentinel base running: {len(site.nodes)} nodes. Ctrl-C to stop.")
    try:
        last_print = 0.0
        while True:
            # fuse as soon as data arrives; the 0.1 s timeout also flushes held-back acoustic fixes
            base.wait_update(0.1)
            snap = base.step()
            if time.time() - last_print >= 1.0:
                last_print = time.time()
                line = " | ".join(f"T{t['id']} ±{t['sigma_m']:.0f}m {'/'.join(t['sources'])}"
                                  for t in snap if t["confirmed"])
                print(time.strftime("%H:%M:%S"), line or "no tracks", flush=True)
    except KeyboardInterrupt:
        pass


def cmd_sim(args):
    from .base import Base
    from .config import Site
    from .sim.scenario import DEFAULT_PATH, DroneSim, NetworkSim, run
    site = Site.load(args.site)
    if args.no_camera:
        site.cameras = {}
    base = Base(site)
    _outputs(args, base)
    drones = [DroneSim(DEFAULT_PATH, speed=args.drone_speed)]
    if args.two:
        drones.append(DroneSim([(200, 150), (50, 60), (-40, -80), (-200, -160)], f0=290, speed=6))
    sim = NetworkSim(site, drones, seed=args.seed)

    def tick(t, snap):
        conf = [s for s in snap if s["confirmed"]]
        print(f"t={t:5.0f}s  " + (" | ".join(
            f"T{s['id']} ({s['e']:6.0f},{s['n']:6.0f}) ±{s['sigma_m']:4.0f}m {'+'.join(s['sources'])}"
            for s in conf) or "no confirmed tracks"))

    log = run(site, base, sim, on_tick=tick if not args.quiet else None,
              realtime=args.speed if args.map else 0)
    import numpy as np
    for k in range(len(drones)):
        e = np.array([r["err"][k] for r in log if r["err"][k] is not None])
        fin = e[np.isfinite(e)]
        print(f"drone {k + 1}: tracked {len(fin)}/{len(e)} s, median error "
              f"{np.median(fin) if len(fin) else float('nan'):.0f} m, 90% {np.percentile(fin, 90) if len(fin) else float('nan'):.0f} m")
    if args.map:
        print("sim finished; map stays up. Ctrl-C to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def cmd_listen(args):
    """Laptop microphone as a listening node: same detector, same packets."""
    import queue

    import numpy as np
    import sounddevice as sd

    from .base import Base
    from .config import Site
    from .detector import FS, HOP, CombDetector
    from .reporter import Reporter

    site = Site.load(args.site)
    node_id = args.node or next(iter(site.nodes))
    base = Base(site)
    _outputs(args, base)
    det, rep = CombDetector(), Reporter(node_id)
    q: queue.Queue = queue.Queue()
    stream = sd.InputStream(samplerate=FS, channels=1, blocksize=HOP, dtype="float32",
                            callback=lambda data, *_: q.put(data[:, 0].copy()))
    stream.start()  # keep `stream` referenced: if it's garbage-collected PortAudio crashes
    print(f"listening on the laptop microphone as node {node_id}. Ctrl-C to stop.")
    t0, last_step = time.time(), 0.0
    try:
        while True:
            x = q.get()
            r = det.process(np.repeat(x[None, :] * args.gain, 4, axis=0))
            now = time.time()
            for pkt in rep.update(r, int((now - t0) * 1000)):
                base.on_packet(pkt, now)
            if now - last_step >= 0.25:
                base.step(now)
                last_step = now
            bar = "#" * int(max(0, min(40, r.score * 2)))
            state = "DRONE" if r.confirmed else ("hit  " if r.hit else "     ")
            print(f"\r{state} f0 {r.f0:6.1f} Hz  comb {r.score:5.1f} dB  harmonics {r.n_harm:2d}  "
                  f"level {r.level_db:5.1f}  {bar:<40}", end="", flush=True)
    except KeyboardInterrupt:
        print()


def cmd_detect(args):
    import numpy as np
    from scipy.io import wavfile
    from scipy.signal import resample_poly
    from .detector import FS, CombDetector
    sr, x = wavfile.read(args.wav)
    x = x.astype(np.float64)
    if x.dtype.kind in "iu" or np.max(np.abs(x)) > 1.5:
        x /= 32768.0 if np.max(np.abs(x)) < 40000 else 2 ** 31
    x = np.atleast_2d(x.T) if x.ndim > 1 else x[None, :]
    if sr != FS:
        from math import gcd
        g = gcd(FS, sr)
        x = resample_poly(x, FS // g, sr // g, axis=1)
    x = x[:4] if x.shape[0] >= 4 else np.repeat(x[:1], 4, axis=0)
    det = CombDetector()
    was = False
    for r in det.run(x):
        t = r.frame * 2048 / FS
        if args.verbose:
            print(f"{t:7.2f}s hit={int(r.hit)} f0={r.f0:6.1f} score={r.score:5.1f} nh={r.n_harm:2d} "
                  f"lvl={r.level_db:5.1f} conf={r.confidence}")
        if r.confirmed and not was:
            print(f"{t:7.2f}s DRONE  f0={r.f0:.1f} Hz  level={r.level_db:.1f} dB  steady={r.steady}")
        if was and not r.confirmed:
            print(f"{t:7.2f}s lost")
        was = r.confirmed


def cmd_ports(_):
    from serial.tools import list_ports
    for p in list_ports.comports():
        print(p.device, "-", p.description)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cuas", description="Silent Sentinel base station")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def outputs(p):
        p.add_argument("--map", action="store_true", help="serve live map on localhost")
        p.add_argument("--map-port", type=int, default=8080)
        p.add_argument("--cot", nargs="?", const="udp://239.2.3.1:6969", help="send CoT to TAK (default SA multicast)")

    p = sub.add_parser("run"); p.add_argument("--site", required=True); p.add_argument("--serial")
    p.add_argument("--visual-port", type=int, default=47010)
    p.add_argument("--jetson", action="append", help="IP to send cues to (also auto-learned)")
    outputs(p); p.set_defaults(fn=cmd_run)

    p = sub.add_parser("sim"); p.add_argument("--site", required=True)
    p.add_argument("--speed", type=float, default=4.0, help="sim seconds per real second (with --map)")
    p.add_argument("--drone-speed", type=float, default=8.0)
    p.add_argument("--two", action="store_true", help="two drones")
    p.add_argument("--no-camera", action="store_true")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--quiet", action="store_true")
    outputs(p); p.set_defaults(fn=cmd_sim)

    p = sub.add_parser("listen"); p.add_argument("--site", required=True)
    p.add_argument("--node", type=int, help="node id to appear as (default: first in site)")
    p.add_argument("--gain", type=float, default=1.0)
    outputs(p); p.set_defaults(fn=cmd_listen)

    p = sub.add_parser("detect"); p.add_argument("wav"); p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(fn=cmd_detect)
    sub.add_parser("ports").set_defaults(fn=cmd_ports)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
