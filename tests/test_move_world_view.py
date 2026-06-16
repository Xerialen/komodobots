"""Bot-program T0.4 -- the shared world-view module is the single source of
truth for MoveMLP's 6 features, and the refactor that extracted it changed NO
values (bit-for-bit identical to the pre-T0.4 inline computation).

Why this test matters: docs/18 wall #2 requires ONE world-view built the SAME
way offline (dataset builder) and live (T0.6 sidecar). If the shared module
drifted from the original computation, the policy would see train/serve skew.
This test is the foundation the T0.5 offline==live golden-vector parity test
pins against.

Three layers of proof:
  1. GOLDEN VECTOR -- hardcoded exact expected outputs for representative
     frames, so the precise numbers are nailed down (independently recomputed
     in the PR, not just "module == module").
  2. REFACTOR PARITY -- a local copy of the PRE-T0.4 inline formula
     (byte-for-byte from build_dataset / eval_openloop) must produce IDENTICAL
     output to the shared module across an aggressive case sweep.
  3. WIRING -- the offline dataset builder and the evaluators import THIS
     module's function (so there is genuinely one source of truth). Guarded so
     the core proof still runs on the stdlib-only CI floor even though the
     builder pulls in numpy/pmove_sim.

Pure stdlib (unittest + math) so it runs in .github/workflows/pr-tests.yml.
"""
import math
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import move_world_view as mwv  # noqa: E402


def _pre_t0_4_inline(vx, vy, vz, yaw, pitch):
    """Byte-for-byte the feature computation as it existed BEFORE T0.4, inline in
    build_dataset._features_and_labels and eval_openloop.state_features. Kept
    here as the reference oracle so the refactor is proven value-preserving.
    DO NOT 'simplify' to call the shared module -- that would defeat the test.
    """
    def wrap180(d):
        return (d + 180.0) % 360.0 - 180.0

    hsp = math.hypot(vx, vy)
    moving = 1.0 if hsp >= 1.0 else 0.0
    if moving:
        vhead = math.degrees(math.atan2(vy, vx))
        lvm = math.radians(wrap180(yaw - vhead))
        lvm_sin, lvm_cos = math.sin(lvm), math.cos(lvm)
    else:
        lvm_sin, lvm_cos = 0.0, 0.0
    return (hsp / 320.0, vz / 320.0, lvm_sin, lvm_cos, moving, pitch / 90.0)


# Golden frames: (name, (vx, vy, vz, yaw, pitch)) -> exact expected feature tuple.
# Recomputed independently; the assertion below pins these to the bit.
GOLDEN = {
    # typical dm3 strafe-jump frame
    "moving_typical": (
        (240.0, 180.0, 90.0, 30.0, -5.0),
        (0.9375, 0.28125, -0.11961524227066316, 0.992820323027551,
         1.0, -0.05555555555555555),
    ),
    # standstill: heading undefined -> lvm zeroed, moving=0
    "standstill": (
        (0.0, 0.0, 0.0, 45.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ),
    # just below the moving epsilon -> treated as not moving
    "near_zero_below_eps": (
        (0.5, 0.5, 10.0, 90.0, 0.0),
        (0.002209708691207961, 0.03125, 0.0, 0.0, 0.0, 0.0),
    ),
    # exactly at the epsilon (hsp == 1.0) -> moving=1, heading along +x
    "exactly_eps": (
        (1.0, 0.0, 0.0, 0.0, 0.0),
        (0.003125, 0.0, 0.0, 1.0, 1.0, 0.0),
    ),
    # near the angle-wrap boundary (~+/-180 deg between view and velocity)
    "wrap_boundary": (
        (-100.0, -0.0, 0.0, 179.0, 12.0),
        (0.3125, 0.0, -0.01745240643728351, 0.9998476951563913,
         1.0, 0.13333333333333333),
    ),
    # fast diagonal strafe, steep pitch, downward vz
    "fast_strafe": (
        (320.0, 320.0, -90.0, 10.0, 88.0),
        (1.4142135623730951, -0.28125, -0.573576436351046,
         0.8191520442889918, 1.0, 0.9777777777777777),
    ),
}


class TestSharedWorldViewContract(unittest.TestCase):
    def test_feature_names_and_dim(self):
        self.assertEqual(
            mwv.FEATURE_NAMES,
            ["hspeed/320", "vz/320", "lvm_sin", "lvm_cos", "moving", "pitch/90"],
        )
        self.assertEqual(mwv.FEATURE_DIM, 6)
        self.assertEqual(len(mwv.FEATURE_NAMES), mwv.FEATURE_DIM)

    def test_output_length_matches_dim(self):
        for _name, (args, _exp) in GOLDEN.items():
            self.assertEqual(len(mwv.state_features(*args)), mwv.FEATURE_DIM)

    def test_wrap180_matches_reference(self):
        for d in (-540.0, -180.0, -1.0, 0.0, 1.0, 179.0, 180.0, 181.0, 360.0, 540.0):
            self.assertEqual(mwv.wrap180(d), (d + 180.0) % 360.0 - 180.0)


class TestGoldenVector(unittest.TestCase):
    """Layer 1: the exact numbers are pinned."""

    def test_golden_vectors_exact(self):
        for name, (args, expected) in GOLDEN.items():
            got = mwv.state_features(*args)
            self.assertEqual(
                got, expected,
                msg=f"golden mismatch for {name}: got {got!r} expected {expected!r}",
            )

    def test_standstill_zeroes_heading(self):
        # |v_h| below eps -> lvm sin/cos and moving are all 0.0 (heading invalid)
        f = mwv.state_features(0.0, 0.0, 250.0, 123.0, 7.0)
        self.assertEqual(f[2], 0.0)   # lvm_sin
        self.assertEqual(f[3], 0.0)   # lvm_cos
        self.assertEqual(f[4], 0.0)   # moving
        # vz and pitch are still normalised even when not moving
        self.assertAlmostEqual(f[1], 250.0 / 320.0)
        self.assertAlmostEqual(f[5], 7.0 / 90.0)


class TestRefactorBitForBitParity(unittest.TestCase):
    """Layer 2: the shared module reproduces the PRE-T0.4 inline formula exactly.

    This is the proof that the T0.4 extraction was refactor-only (no value
    change) -- the precondition for the T0.5 offline==live parity gate.
    """

    def test_matches_inline_on_golden_cases(self):
        for name, (args, _expected) in GOLDEN.items():
            self.assertEqual(
                mwv.state_features(*args), _pre_t0_4_inline(*args),
                msg=f"refactor changed values for {name}",
            )

    def test_matches_inline_on_case_sweep(self):
        # Aggressive deterministic sweep across velocity directions/magnitudes,
        # yaw all the way around, pitch range, and the |v_h| epsilon boundary.
        speeds = [0.0, 0.4, 0.999, 1.0, 1.001, 37.5, 240.0, 320.0, 700.0]
        headings = [0.0, 23.0, 90.0, 134.0, 180.0, 226.0, 270.0, 359.0]
        yaws = [-179.0, -90.0, -0.0, 0.0, 45.0, 90.0, 178.0, 180.0, 359.0]
        pitches = [-90.0, -30.0, 0.0, 17.0, 89.0]
        vzs = [-320.0, -90.0, 0.0, 110.0, 400.0]
        checked = 0
        for sp in speeds:
            for hd in headings:
                vx = sp * math.cos(math.radians(hd))
                vy = sp * math.sin(math.radians(hd))
                for vz in vzs:
                    for yaw in yaws:
                        for pitch in pitches:
                            got = mwv.state_features(vx, vy, vz, yaw, pitch)
                            ref = _pre_t0_4_inline(vx, vy, vz, yaw, pitch)
                            self.assertEqual(
                                got, ref,
                                msg=(f"mismatch vx={vx} vy={vy} vz={vz} "
                                     f"yaw={yaw} pitch={pitch}: {got!r} != {ref!r}"),
                            )
                            checked += 1
        # guard: make sure the sweep actually ran the intended breadth
        self.assertEqual(checked,
                         len(speeds) * len(headings) * len(vzs)
                         * len(yaws) * len(pitches))
        self.assertGreater(checked, 10000)


class TestCallersImportSharedModule(unittest.TestCase):
    """Layer 3: the offline builder and evaluators use THIS module's function,
    so there is genuinely a single source of truth (not parallel copies).

    Guarded: the dataset builder / evaluators import numpy + pmove_sim, which are
    not present on the stdlib-only CI runner, so a missing heavy dep skips rather
    than fails. The bit-for-bit proof above does not depend on this.
    """

    def _import_module_from(self, rel_path, name):
        import importlib.util
        path = REPO / rel_path
        self.assertTrue(path.exists(), f"missing {rel_path}")
        # the move-bc modules expect their own dir + scripts on sys.path
        sys.path.insert(0, str(path.parent))
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_build_dataset_uses_shared_state_features(self):
        try:
            bd = self._import_module_from(
                "experiments/stage2/move-bc-train/build_dataset.py", "build_dataset")
        except ImportError as e:
            self.skipTest(f"heavy dep unavailable ({e}); core parity proven above")
        # the builder's state_features IS the shared one (same object)
        self.assertIs(bd.state_features, mwv.state_features)
        self.assertIs(bd.wrap180, mwv.wrap180)

    def test_eval_openloop_reexports_shared(self):
        try:
            eo = self._import_module_from(
                "experiments/stage2/move-bc-train/eval_openloop.py", "eval_openloop")
        except ImportError as e:
            self.skipTest(f"heavy dep unavailable ({e}); core parity proven above")
        self.assertIs(eo.state_features, mwv.state_features)
        self.assertIs(eo.wrap180, mwv.wrap180)


if __name__ == "__main__":
    unittest.main()
