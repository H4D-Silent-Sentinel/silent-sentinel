import json

import pytest

from cuas.config import Site
from cuas.io import parse_rx_line
from cuas.packet import Packet, PktType, RadarPacket, RadarPlot, decode_any

# Bytes from firmware/node/packet.h (RadarPacket, radar_seal) compiled on the host.
C_BYTES = "c5150702010285ffc801f72c01ffff04000000000000903a"


def test_matches_firmware_layout():
    p = RadarPacket(7, 513, [RadarPlot(-1.23, 4.56, -2.25), RadarPlot(3.0, -0.01, 1.0)])
    assert p.encode().hex() == C_BYTES
    d = RadarPacket.decode(bytes.fromhex(C_BYTES))
    assert d.radar_id == 7 and d.seq == 513 and len(d.targets) == 2
    assert d.targets[0] == RadarPlot(-1.23, 4.56, -2.25)


def test_heartbeat_and_limits():
    hb = RadarPacket.decode(RadarPacket(1, 0, []).encode())
    assert hb.targets == []
    big = RadarPacket.decode(RadarPacket(1, 0, [RadarPlot(500, -500, 99)] * 5).encode())
    assert len(big.targets) == 3 and big.targets[0].x_m == pytest.approx(327.67) and big.targets[0].speed_mps == 31.75


def test_bad_crc_rejected():
    b = bytearray(bytes.fromhex(C_BYTES))
    b[8] ^= 1
    with pytest.raises(ValueError):
        RadarPacket.decode(bytes(b))


def test_dispatch():
    assert isinstance(decode_any(bytes.fromhex(C_BYTES)), RadarPacket)
    node = Packet(PktType.HEARTBEAT, 3, seq=1).encode()
    assert isinstance(decode_any(node), Packet)
    with pytest.raises(ValueError):
        Packet.decode(bytes.fromhex(C_BYTES))
    pkt = parse_rx_line(f"PKT -80 7.5 {C_BYTES}")
    assert isinstance(pkt, RadarPacket) and pkt.rssi == -80


def test_site_radars(tmp_path):
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"origin": [40.8, -73.96], "nodes": [{"id": 1, "lat": 40.8, "lon": -73.96}],
                             "radars": [{"id": 1, "lat": 40.8, "lon": -73.9599, "yaw_deg": 90}]}))
    s = Site.load(f)
    assert s.radars[1].yaw_deg == 90 and s.radars[1].max_range_m == 8.0
    assert Site.load(f).cameras == {}
