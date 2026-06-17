"""CI coverage for the T0.5 PR-B offline recompute (scripts/diff_live_world_view.py).

The parity *evidence* is recorded on-box (experiments/ktx_moveprobe/evidence/
t0.5_golden_parity.json); this test locks the parser + diff logic that produced
it, so a regression in how KTX's dump lines are read/compared is caught in CI.
Stdlib only.
"""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import diff_live_world_view as d  # noqa: E402
import move_world_view as mwv  # noqa: E402


def _hex(x):
    return f"{struct.unpack('<I', struct.pack('<f', x))[0]:08x}"


def _dump_line(slot, req, vx, vy, vz, yaw, pitch, feats):
    ins = " ".join(_hex(v) for v in (vx, vy, vz, yaw, pitch))
    fs = " ".join(_hex(f) for f in feats)
    return f"[2026-01-01 00:00:00] [moveprobe-dump] slot {slot} req {req} in {ins} feat {fs}"


# A few representative live states (moving, standstill, left/right of heading).
CASES = [
    (1, 1, 0.0, 0.0, 0.0, 90.0, 0.0),
    (1, 2, 320.0, 0.0, -120.0, 13.5, -7.0),
    (2, 3, -210.0, 175.0, 40.0, -163.0, 22.0),
    (2, 4, 50.0, -300.0, 0.0, 270.0, 8.5),
]


class DiffLiveWorldViewTest(unittest.TestCase):
    def _faithful_dump(self):
        lines = []
        for slot, req, vx, vy, vz, yaw, pitch in CASES:
            feats = mwv.state_features(vx, vy, vz, yaw, pitch)
            lines.append(_dump_line(slot, req, vx, vy, vz, yaw, pitch, feats))
        return "\n".join(lines) + "\n"

    def test_faithful_dump_has_zero_mismatch(self):
        rows, slots, mism = d.check(self._faithful_dump())
        self.assertEqual(rows, len(CASES))
        self.assertEqual(slots, [1, 2])
        self.assertEqual(mism, [], "faithful dump must recompute bit-identical")

    def test_corrupted_feature_is_detected(self):
        # Flip the first feature's bits on one line -> exactly one mismatch.
        slot, req, vx, vy, vz, yaw, pitch = CASES[1]
        feats = list(mwv.state_features(vx, vy, vz, yaw, pitch))
        feats[0] = feats[0] + 1.0  # off by a whole unit -> different f32 bits
        bad = _dump_line(slot, req, vx, vy, vz, yaw, pitch, feats)
        good = _dump_line(*CASES[0], mwv.state_features(*CASES[0][2:]))
        rows, _, mism = d.check(good + "\n" + bad + "\n")
        self.assertEqual(rows, 2)
        self.assertEqual(len(mism), 1)
        self.assertEqual(mism[0]["req"], req)

    def test_inputs_round_trip_exact_f32(self):
        # The f32-hex decode is the exact bit pattern KTX wrote (float identity).
        for x in (320.0, -8.8, 0.00763, 175.84):
            self.assertEqual(d.f32_from_hex(_hex(x)), struct.unpack("<f", struct.pack("<f", x))[0])

    def test_non_dump_text_yields_no_rows(self):
        rows, slots, mism = d.check("nothing here\n[moveprobe-live] slot 1 LIVE fwd=1\n")
        self.assertEqual((rows, slots, mism), (0, [], []))


if __name__ == "__main__":
    unittest.main()
