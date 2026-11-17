import pytest

from cuas.io import parse_rx_line
from cuas.packet import FLAG_CONFIRMED, SIZE, Packet, PktType, crc16


def test_crc_known_vector():
    assert crc16(b"123456789") == 0x29B1  # CRC-16/CCITT-FALSE check value


def test_roundtrip():
    p = Packet(PktType.DETECTION, 5, seq=65535, uptime_ms=123456, flags=FLAG_CONFIRMED, f0_hz=212.3,
               f0_rate_hz_s=-4.2, level_db=57.8, score_db=11.5, n_harm=9, confidence=77, floor_db=31.2)
    b = p.encode()
    assert len(b) == SIZE == 24
    q = Packet.decode(b)
    assert (q.node_id, q.seq, q.f0_hz, q.f0_rate_hz_s, q.level_db, q.confidence, q.confirmed) == \
           (5, 65535, 212.3, -4.2, 57.8, 77, True)


def test_corruption_rejected():
    b = bytearray(Packet(PktType.HEARTBEAT, 1).encode())
    b[10] ^= 0x40
    with pytest.raises(ValueError):
        Packet.decode(bytes(b))


def test_base_rx_line():
    hexs = Packet(PktType.DETECTION, 3, f0_hz=200, flags=1).encode().hex()
    p = parse_rx_line(f"PKT -71 8.5 {hexs}")
    assert p.node_id == 3 and p.rssi == -71 and p.snr == 8.5
    assert parse_rx_line("HELLO silent-sentinel-base v1") is None
