"""ml/tests/test_eval_believability.py — tests for the open-loop believability eval.

Two layers, mirroring ml/tests/test_broad_bc.py:
  * DEPS-FREE: the pure-python metric helpers in ml/eval_broad_believability.py —
    strafe-cadence sign-flip counting, cadence-per-min over airborne-moving ticks,
    jump/attack rates, move-class distributions, head agreement, distribution
    distance, anchor-band resolution + pass/fail, and the caveats block. These
    ALWAYS run with NO torch/numpy/duckdb (they are the contract this box can verify).
  * TORCH+DUCKDB: the end-to-end run_eval is SKIPPED here (needs a real checkpoint +
    catalog on the GPU host); a smoke import-only check asserts the module imports
    deps-free and that run_eval exists.

The metric math is factored OUT of the torch CLI precisely so it is importable and
checkable without the heavy deps — `compute_demo_metrics` is the exact function the
pinnacle run calls per demo after producing the policy's argmax predictions.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ML = HERE.parent
REPO_ROOT = ML.parent
sys.path.insert(0, str(ML))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import eval_broad_believability as EV   # noqa: E402  (deps-free at import time)

_HAVE_TORCH = importlib.util.find_spec("torch") is not None
_HAVE_DUCKDB = importlib.util.find_spec("duckdb") is not None


class TestSignFlipCount(unittest.TestCase):
    """count_sign_flips: the L/R strafe-cadence primitive (zeros skipped)."""

    def test_two_flips(self):
        # + + - - +  ->  (+->-) , (-->+)  = 2 reversals
        self.assertEqual(EV.count_sign_flips([+1, +1, -1, -1, +1]), 2)

    def test_zeros_are_skipped_not_breaking_rhythm(self):
        # zeros (no-strafe ticks) don't start/break a run: + 0 + 0 -  -> one flip
        self.assertEqual(EV.count_sign_flips([+1, 0, +1, 0, -1]), 1)

    def test_never_strafes_all_zero_is_zero(self):
        self.assertEqual(EV.count_sign_flips([0, 0, 0, 0]), 0)

    def test_held_one_direction_is_zero(self):
        # the believability red flag: strafe key never alternates -> 0 flips
        self.assertEqual(EV.count_sign_flips([+1, +1, +1, +1, +1]), 0)

    def test_alternating_every_tick(self):
        self.assertEqual(EV.count_sign_flips([+1, -1, +1, -1, +1]), 4)

    def test_empty(self):
        self.assertEqual(EV.count_sign_flips([]), 0)


class TestStrafeCadencePerMin(unittest.TestCase):
    def test_known_cadence_count_and_rate(self):
        # 4 flips over an eligible window. ticks_per_sec=10 -> the 5 eligible ticks
        # span 0.5 s -> 4 / 0.5 * 60 = 480 flips/min.
        signs = [+1, -1, +1, -1, +1]
        elig = [True] * 5
        out = EV.strafe_cadence_per_min(signs, elig, ticks_per_sec=10.0)
        self.assertEqual(out["flips"], 4)
        self.assertEqual(out["eligible_ticks"], 5)
        self.assertAlmostEqual(out["eligible_seconds"], 0.5)
        self.assertAlmostEqual(out["flips_per_min"], 480.0)

    def test_only_eligible_ticks_count(self):
        # ineligible (ground) ticks are dropped BEFORE counting flips: the two -1s
        # below are ground, so the eligible stream is [+1,+1,+1] -> 0 flips.
        signs = [+1, -1, +1, -1, +1]
        elig = [True, False, True, False, True]
        out = EV.strafe_cadence_per_min(signs, elig, ticks_per_sec=10.0)
        self.assertEqual(out["flips"], 0)
        self.assertEqual(out["eligible_ticks"], 3)
        self.assertAlmostEqual(out["flips_per_min"], 0.0)

    def test_degenerate_never_strafes_cadence_zero(self):
        # the believability red flag at the cadence level: never strafes -> rate 0.0
        out = EV.strafe_cadence_per_min([0, 0, 0, 0], [True] * 4, ticks_per_sec=77.0)
        self.assertEqual(out["flips"], 0)
        self.assertAlmostEqual(out["flips_per_min"], 0.0)

    def test_no_eligible_ticks_rate_zero(self):
        out = EV.strafe_cadence_per_min([+1, -1, +1], [False, False, False],
                                        ticks_per_sec=77.0)
        self.assertEqual(out["eligible_ticks"], 0)
        self.assertAlmostEqual(out["flips_per_min"], 0.0)


class TestBinRate(unittest.TestCase):
    def test_jump_rate_half(self):
        out = EV.bin_rate([1, 0, 1, 0])
        self.assertEqual(out["pressed"], 2)
        self.assertEqual(out["n"], 4)
        self.assertAlmostEqual(out["rate"], 0.5)

    def test_attack_rate_all_pressed(self):
        self.assertAlmostEqual(EV.bin_rate([1, 1, 1])["rate"], 1.0)

    def test_never_pressed(self):
        self.assertAlmostEqual(EV.bin_rate([0, 0, 0, 0])["rate"], 0.0)

    def test_empty_rate_zero(self):
        self.assertAlmostEqual(EV.bin_rate([])["rate"], 0.0)


class TestClassDistribution(unittest.TestCase):
    def test_three_way_counts_and_fracs(self):
        # classes 0/1/2 = back/none/fwd; here two none + one back + one fwd
        out = EV.class_distribution([1, 1, 0, 2], 3)
        self.assertEqual(out["counts"], [1, 2, 1])
        self.assertEqual(out["n"], 4)
        self.assertAlmostEqual(out["fracs"][1], 0.5)

    def test_out_of_range_ignored(self):
        out = EV.class_distribution([0, 1, 5, -1], 3)  # 5 and -1 are not valid classes
        self.assertEqual(out["counts"], [1, 1, 0])
        self.assertEqual(out["n"], 2)


class TestHeadAgreement(unittest.TestCase):
    def test_partial_agreement(self):
        out = EV.head_agreement([0, 1, 2, 1], [0, 1, 1, 1])  # 3/4 match
        self.assertEqual(out["agree"], 3)
        self.assertAlmostEqual(out["agreement"], 0.75)

    def test_perfect_and_zero(self):
        self.assertAlmostEqual(EV.head_agreement([1, 1], [1, 1])["agreement"], 1.0)
        self.assertAlmostEqual(EV.head_agreement([0, 0], [1, 1])["agreement"], 0.0)


class TestTotalVariation(unittest.TestCase):
    def test_identical_is_zero(self):
        self.assertAlmostEqual(EV.total_variation([0.2, 0.3, 0.5], [0.2, 0.3, 0.5]), 0.0)

    def test_disjoint_is_one(self):
        self.assertAlmostEqual(EV.total_variation([1.0, 0.0], [0.0, 1.0]), 1.0)

    def test_partial(self):
        # 0.5*(|0.5-0.25| + |0.5-0.75|) = 0.5*(0.25+0.25) = 0.25
        self.assertAlmostEqual(EV.total_variation([0.5, 0.5], [0.25, 0.75]), 0.25)


class TestAirborneMovingMask(unittest.TestCase):
    def test_airborne_and_moving_only(self):
        # tick eligible iff onground is falsey AND hspeed >= floor (80)
        onground = [True, False, False, False]
        hspeed = [600.0, 600.0, 50.0, 300.0]
        mask = EV.airborne_moving_mask(onground, hspeed)
        # t0 grounded -> F; t1 air+fast -> T; t2 air but slow -> F; t3 air+fast -> T
        self.assertEqual(mask, [False, True, False, True])

    def test_none_hspeed_is_not_moving(self):
        self.assertEqual(EV.airborne_moving_mask([False], [None]), [False])


class TestSideClassToSign(unittest.TestCase):
    def test_sign3_mapping(self):
        self.assertEqual(EV.side_class_to_sign(0), -1)  # left
        self.assertEqual(EV.side_class_to_sign(1), 0)   # none
        self.assertEqual(EV.side_class_to_sign(2), +1)  # right


class TestComputeDemoMetrics(unittest.TestCase):
    """The end-to-end per-demo metric assembly on a synthetic class stream — exactly
    what the pinnacle run feeds after argmax-ing the policy heads."""

    def _synthetic(self):
        # 6 ticks, all airborne-moving. side classes alternate L/R every tick while
        # airborne -> a strong strafe rhythm. jump pressed half, attack pressed once.
        pred = {
            "fwd":  [2, 2, 2, 2, 2, 2],          # always forward
            "side": [0, 2, 0, 2, 0, 2],          # L R L R L R -> alternating
            "up":   [1, 1, 1, 1, 1, 1],          # never up
            "jump": [1, 0, 1, 0, 1, 0],          # 50% jump
            "attack": [0, 0, 1, 0, 0, 0],        # 1/6 attack
        }
        human = {
            "fwd":  [2, 2, 2, 2, 2, 1],
            "side": [0, 2, 0, 2, 0, 0],
            "up":   [1, 1, 1, 1, 1, 1],
            "jump": [1, 0, 1, 0, 0, 0],
            "attack": [0, 0, 1, 0, 0, 1],
        }
        raw = {"onground": [False] * 6, "hspeed": [500.0] * 6}
        return pred, human, raw

    def test_strafe_cadence_present_and_distinct(self):
        pred, human, raw = self._synthetic()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        self.assertEqual(m["n_ticks"], 6)
        self.assertEqual(m["airborne_moving_ticks"], 6)
        # policy side alternates all 6 ticks -> 5 flips; human alternates 5 then holds
        self.assertEqual(m["strafe_cadence_per_min"]["policy"]["flips"], 5)
        self.assertEqual(m["strafe_cadence_per_min"]["human"]["flips"], 4)
        # 5 flips over 0.6 s eligible -> 500 flips/min
        self.assertAlmostEqual(
            m["strafe_cadence_per_min"]["policy"]["flips_per_min"], 500.0)

    def test_jump_attack_rates(self):
        pred, human, raw = self._synthetic()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        self.assertAlmostEqual(m["jump_rate"]["policy"]["rate"], 0.5)
        self.assertAlmostEqual(m["attack_rate"]["policy"]["rate"], round(1 / 6, 6))

    def test_move_class_dist_and_tv(self):
        pred, human, raw = self._synthetic()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        # policy fwd is all class-2 -> fracs [0,0,1]
        self.assertEqual(m["move_class_dist"]["fwd"]["policy"]["fracs"], [0.0, 0.0, 1.0])
        # tv distance between identical 'up' dists is 0
        self.assertAlmostEqual(m["move_class_dist"]["up"]["tv_distance"], 0.0)

    def test_head_agreement_block_present_for_all_heads(self):
        pred, human, raw = self._synthetic()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        for h in ["fwd", "side", "up", "jump", "attack"]:
            self.assertIn(h, m["head_agreement"])
        # 'up' identical -> agreement 1.0
        self.assertAlmostEqual(m["head_agreement"]["up"]["agreement"], 1.0)

    def test_degenerate_never_strafes_red_flag(self):
        # a bot that NEVER strafes (side always 'none') -> cadence 0 even though
        # airborne the whole time: the believability red flag surfaces as 0 flips/min.
        n = 8
        pred = {"fwd": [2] * n, "side": [1] * n, "up": [1] * n,
                "jump": [0] * n, "attack": [0] * n}
        human = {"fwd": [2] * n, "side": [0, 2] * (n // 2), "up": [1] * n,
                 "jump": [0] * n, "attack": [0] * n}
        raw = {"onground": [False] * n, "hspeed": [500.0] * n}
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=77.0)
        self.assertEqual(m["strafe_cadence_per_min"]["policy"]["flips"], 0)
        self.assertAlmostEqual(
            m["strafe_cadence_per_min"]["policy"]["flips_per_min"], 0.0)
        # while the human DID strafe -> non-zero, so the gap is visible
        self.assertGreater(
            m["strafe_cadence_per_min"]["human"]["flips"], 0)


class TestHumanWeightMasking(unittest.TestCase):
    """FIX B(2): weight==0 human rows (null/interpolated/zero-confidence labels — the
    trainer's loss-excluded frames, build_features.py) must be dropped from the HUMAN
    side numerator AND denominator. The fabricated all-idle label they carry otherwise
    inflates human idle/no-jump rates and corrupts head agreement. Policy stays unmasked."""

    def _stream(self):
        # 4 ticks. The LAST TWO are weight==0: their HUMAN labels are fabricated 'idle'
        # (jump not pressed, side none). The human ACTUALLY jumped on both valid ticks.
        pred = {"fwd": [2, 2, 2, 2], "side": [2, 0, 2, 0], "up": [1, 1, 1, 1],
                "jump": [1, 1, 1, 1], "attack": [0, 0, 0, 0]}
        human = {"fwd": [2, 2, 1, 1], "side": [2, 0, 1, 1], "up": [1, 1, 1, 1],
                 "jump": [1, 1, 0, 0], "attack": [0, 0, 0, 0]}   # last 2 = fabricated idle
        raw = {"onground": [False] * 4, "hspeed": [500.0] * 4}
        weight = [1.0, 1.0, 0.0, 0.0]
        return pred, human, raw, weight

    def test_human_jump_rate_excludes_zero_weight(self):
        pred, human, raw, weight = self._stream()
        # WITHOUT the mask: human jump = 2/4 = 0.5 (the fabricated idle rows drag it down)
        m_unmasked = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        self.assertAlmostEqual(m_unmasked["jump_rate"]["human"]["rate"], 0.5)
        # WITH the mask: only the 2 valid ticks count, both jump=1 -> 1.0
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0,
                                    human_weight=weight)
        self.assertAlmostEqual(m["jump_rate"]["human"]["rate"], 1.0)
        self.assertEqual(m["jump_rate"]["human"]["n"], 2)
        # policy jump rate is UNMASKED: 4/4 -> 1.0 over all 4 ticks
        self.assertAlmostEqual(m["jump_rate"]["policy"]["rate"], 1.0)
        self.assertEqual(m["jump_rate"]["policy"]["n"], 4)

    def test_human_move_class_dist_excludes_zero_weight(self):
        pred, human, raw, weight = self._stream()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0,
                                    human_weight=weight)
        # human 'side' over valid ticks only = [2,0] -> classes {0:1, 2:1}, none(1)=0.
        # the two fabricated 'none' rows are excluded, so frac[1] (none) is 0.0.
        hdist = m["move_class_dist"]["side"]["human"]
        self.assertEqual(hdist["n"], 2)
        self.assertEqual(hdist["counts"], [1, 0, 1])

    def test_human_strafe_cadence_excludes_zero_weight(self):
        pred, human, raw, weight = self._stream()
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0,
                                    human_weight=weight)
        # human eligible+valid side stream = [2,0] (R,L) -> exactly 1 flip; the two
        # fabricated 'none' rows neither add eligible ticks nor flips.
        hc = m["strafe_cadence_per_min"]["human"]
        self.assertEqual(hc["flips"], 1)
        self.assertEqual(hc["eligible_ticks"], 2)
        # policy eligible side = [2,0,2,0] over all 4 ticks -> 3 flips
        self.assertEqual(m["strafe_cadence_per_min"]["policy"]["flips"], 3)
        self.assertEqual(m["strafe_cadence_per_min"]["policy"]["eligible_ticks"], 4)

    def test_head_agreement_excludes_zero_weight(self):
        pred, human, raw, weight = self._stream()
        # jump head: pred all 1; human valid = [1,1] -> agreement 1.0 over 2 ticks.
        # WITHOUT mask the fabricated [0,0] human rows would drop agreement to 0.5.
        m = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0,
                                    human_weight=weight)
        self.assertAlmostEqual(m["head_agreement"]["jump"]["agreement"], 1.0)
        self.assertEqual(m["head_agreement"]["jump"]["n"], 2)
        m_unmasked = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        self.assertAlmostEqual(m_unmasked["head_agreement"]["jump"]["agreement"], 0.5)

    def test_default_none_is_backcompat(self):
        # human_weight=None (default) must behave EXACTLY as before (no masking).
        pred, human, raw, _ = self._stream()
        a = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0)
        b = EV.compute_demo_metrics(pred, human, raw, ticks_per_sec=10.0,
                                    human_weight=None)
        self.assertEqual(a, b)


class TestAggregateMetrics(unittest.TestCase):
    def test_flips_summed_per_demo_not_across_boundary(self):
        # REGRESSION (cross-demo teleport flip): demoA ENDS on +1 (right) and demoB
        # OPENS on -1 (left). Concatenating the streams and counting sign-flips ONCE
        # would see a +1 -> -1 reversal AT THE DEMO BOUNDARY and report 3 flips, but
        # that reversal never happened within either demo. The correct corpus flip
        # count is the SUM of each demo's own flips: demoA [.. +1 .. ] has its flips,
        # demoB [-1 ..] has its flips, and the boundary contributes NOTHING.
        #
        #   demoA side signs: [-1, +1]  -> 1 flip  (-1 -> +1)
        #   demoB side signs: [-1, +1]  -> 1 flip  (-1 -> +1)
        #   correct total = 2.   pooled-and-counted-once = 3 (the +1->-1 boundary).
        d = {
            "demoA": {
                "pred": {"fwd": [2, 2], "side": [0, 2], "up": [1, 1],
                         "jump": [1, 0], "attack": [0, 0]},
                "human": {"fwd": [2, 2], "side": [0, 2], "up": [1, 1],
                          "jump": [1, 0], "attack": [0, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
            },
            "demoB": {
                "pred": {"fwd": [2, 2], "side": [0, 2], "up": [1, 1],
                         "jump": [0, 0], "attack": [1, 0]},
                "human": {"fwd": [2, 2], "side": [0, 2], "up": [1, 1],
                          "jump": [0, 0], "attack": [1, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
            },
        }
        agg = EV.aggregate_metrics(d, ticks_per_sec=10.0)
        self.assertEqual(agg["n_ticks"], 4)
        # sum of per-demo flips = 1 + 1 = 2 (NOT 3 from the spurious +1->-1 boundary)
        self.assertEqual(agg["strafe_cadence_per_min"]["policy"]["flips"], 2)
        self.assertEqual(agg["strafe_cadence_per_min"]["human"]["flips"], 2)
        # eligible-tick count still pools across both demos (4 airborne-moving ticks),
        # so the rate uses the full corpus duration, only the flip COUNT is per-demo.
        self.assertEqual(agg["strafe_cadence_per_min"]["policy"]["eligible_ticks"], 4)
        # sanity: had it pooled-and-counted-once it would be 3 -> assert it is not.
        self.assertNotEqual(agg["strafe_cadence_per_min"]["policy"]["flips"], 3)

    def test_count_based_metrics_still_pool(self):
        # distributions / rates / agreement are plain counts and DO pool by
        # concatenation (no boundary artifact). Two demos, 2 ticks each.
        d = {
            "demoA": {
                "pred": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                         "jump": [1, 1], "attack": [0, 0]},
                "human": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                          "jump": [1, 1], "attack": [0, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
            },
            "demoB": {
                "pred": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                         "jump": [0, 0], "attack": [0, 0]},
                "human": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                          "jump": [0, 0], "attack": [0, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
            },
        }
        agg = EV.aggregate_metrics(d, ticks_per_sec=10.0)
        # jump pressed on 2 of 4 pooled ticks -> 0.5
        self.assertAlmostEqual(agg["jump_rate"]["policy"]["rate"], 0.5)

    def test_aggregate_masks_zero_weight_human_rows(self):
        # demoB's two ticks are weight==0 (e.g. interpolated frames the trainer drops).
        # Their HUMAN labels are fabricated 'idle' (side none / jump pressed-looking),
        # and must NOT count toward the pooled HUMAN jump rate. Only demoA's 2 valid
        # human ticks (both jump=1) count -> human jump rate 1.0, NOT 0.5.
        d = {
            "demoA": {
                "pred": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                         "jump": [1, 1], "attack": [0, 0]},
                "human": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                          "jump": [1, 1], "attack": [0, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
                "human_weight": [1.0, 1.0],
            },
            "demoB": {
                "pred": {"fwd": [2, 2], "side": [1, 1], "up": [1, 1],
                         "jump": [0, 0], "attack": [0, 0]},
                "human": {"fwd": [1, 1], "side": [1, 1], "up": [1, 1],
                          "jump": [0, 0], "attack": [0, 0]},
                "raw": {"onground": [False, False], "hspeed": [500.0, 500.0]},
                "human_weight": [0.0, 0.0],
            },
        }
        agg = EV.aggregate_metrics(d, ticks_per_sec=10.0)
        # human side: only demoA's 2 ticks valid, both jump=1 -> rate 1.0
        self.assertAlmostEqual(agg["jump_rate"]["human"]["rate"], 1.0)
        self.assertEqual(agg["jump_rate"]["human"]["n"], 2)
        # policy side is UNMASKED: jump pressed 2 of 4 pooled ticks -> 0.5
        self.assertAlmostEqual(agg["jump_rate"]["policy"]["rate"], 0.5)
        self.assertEqual(agg["jump_rate"]["policy"]["n"], 4)


class TestAnchorResolution(unittest.TestCase):
    def test_no_anchors_path(self):
        out = EV.resolve_strafe_anchor(None)
        self.assertIsNone(out["anchor_band"])
        self.assertIn("no --anchors", out["reason"])

    def test_real_anchor_has_no_strafe_band(self):
        # the SHIPPED dm3 4on4 anchor: movement plane has speed/air ratios +
        # airborne-run jump_cadence_per_min but NO L/R strafe band -> null + reason.
        anchors_path = REPO_ROOT / "references" / "dm3_4on4_anchors.json"
        if not anchors_path.exists():
            self.skipTest("dm3_4on4_anchors.json not present")
        out = EV.resolve_strafe_anchor(anchors_path)
        self.assertIsNone(out["anchor_band"])
        self.assertIn("strafe_cadence_per_min", out["reason"])
        self.assertIn("usercmd sidemove", out["reason"])

    def test_synthetic_anchor_with_band_resolves(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "anchors.json"
            p.write_text(json.dumps({
                "schema": "test.v1",
                "metrics": {"movement": {"fields": {"strafe_cadence_per_min": {
                    "pool": {"min": 120.0, "max": 240.0, "mean": 180.0}}}}},
            }), encoding="utf-8")
            out = EV.resolve_strafe_anchor(p)
            self.assertEqual(out["anchor_band"]["min"], 120.0)
            self.assertEqual(out["anchor_band"]["max"], 240.0)


class TestCadencePassFail(unittest.TestCase):
    def test_inside_band_passes(self):
        v = EV.cadence_pass_fail(180.0, {"min": 120.0, "max": 240.0})
        self.assertTrue(v["pass"])

    def test_outside_band_fails(self):
        v = EV.cadence_pass_fail(50.0, {"min": 120.0, "max": 240.0})
        self.assertFalse(v["pass"])

    def test_no_band_is_null_verdict(self):
        v = EV.cadence_pass_fail(180.0, None)
        self.assertIsNone(v["pass"])
        self.assertIn("no strafe-cadence anchor band", v["note"])


class TestCaveats(unittest.TestCase):
    def test_caveats_mark_open_loop_and_na_metrics(self):
        strafe_anchor = EV.resolve_strafe_anchor(None)
        cav = EV.build_caveats(strafe_anchor)
        self.assertEqual(cav["eval_mode"], "open_loop")
        self.assertEqual(cav["aim_head"], "NOT_CLONED")
        # the three N/A-open-loop gates must each be present with a reason
        self.assertIn("G-MV1_face_and_run", cav["na_metrics"])
        self.assertIn("G-MV4_speed_band", cav["na_metrics"])
        self.assertIn("route_retention", cav["na_metrics"])
        for k, v in cav["na_metrics"].items():
            self.assertIn("N/A-open-loop", v)


@unittest.skipUnless(_HAVE_TORCH and _HAVE_DUCKDB,
                     "run_eval needs torch + duckdb (pinnacle GPU host)")
class TestRunEvalGated(unittest.TestCase):
    """End-to-end is exercised on pinnacle with a real checkpoint + catalog. Here we
    only assert the entrypoint exists; a full fixture run is the orchestrator's job."""

    def test_run_eval_callable(self):
        self.assertTrue(callable(EV.run_eval))


class TestModuleImportsDepsFree(unittest.TestCase):
    """Guard: the module + its metric helpers import on bare stdlib (no torch etc.)."""

    def test_helpers_importable_and_run_eval_present(self):
        self.assertTrue(callable(EV.compute_demo_metrics))
        self.assertTrue(callable(EV.strafe_cadence_per_min))
        self.assertTrue(hasattr(EV, "run_eval"))


if __name__ == "__main__":
    unittest.main()
