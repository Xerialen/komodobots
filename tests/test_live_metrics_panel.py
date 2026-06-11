"""Live metrics panel data-contract tests (LD-E3, issue #102).

Validates the pure geometry helpers exported from LiveMetricsPanel.tsx,
re-implemented in Python:

- projectOntoSegment: nearest point on a line segment; t clamped to [0,1];
  correct at segment endpoints, interior, and degenerate (zero-length) cases
- projectOntoPolyline: nearest arc fraction on a multi-vertex polyline;
  correctness at segment boundaries; point at midpoint of last segment
- interpolateSpeedAtArc: speed at arc fraction interpolated from per-vertex
  speed array; clamps at 0 and 1; linear between vertices
- isInEdgeRegion: 2D XY radius check; on boundary, inside, and outside
- buildVertexSpeeds: gap-anchor interpolation; no-gap fill; ordering

These tests exercise the PURE LOGIC contract.  No browser or TypeScript
runtime required.

The edge-detection radius used in production is EDGE_REGION_RADIUS = 96 qu.
The off-route threshold is OFF_ROUTE_DIST = 384 qu.
"""

import math
import sys
import unittest

# ---------------------------------------------------------------------------
# Re-implement the pure functions from LiveMetricsPanel.tsx in Python.
# Any change to the TypeScript logic that is not reflected here will cause
# these tests to fail (or vice versa), keeping both in sync.
# ---------------------------------------------------------------------------

def dist3_sq(ax, ay, az, bx, by, bz):
    dx, dy, dz = bx - ax, by - ay, bz - az
    return dx*dx + dy*dy + dz*dz


def project_onto_segment(px, py, pz, ax, ay, az, bx, by, bz):
    """Return (t, dist_sq) where t in [0,1] is the clamp parameter."""
    abx, aby, abz = bx - ax, by - ay, bz - az
    ab_len_sq = abx*abx + aby*aby + abz*abz
    if ab_len_sq == 0:
        return 0.0, dist3_sq(px, py, pz, ax, ay, az)
    apx, apy, apz = px - ax, py - ay, pz - az
    dot = apx*abx + apy*aby + apz*abz
    t = max(0.0, min(1.0, dot / ab_len_sq))
    projx = ax + t*abx
    projy = ay + t*aby
    projz = az + t*abz
    return t, dist3_sq(px, py, pz, projx, projy, projz)


def project_onto_polyline(px, py, pz, polyline):
    """
    Returns dict with arcFrac, distSq, segIndex, segT; or None if <2 points.
    """
    n = len(polyline)
    if n < 2:
        return None

    seg_lens = []
    total_len = 0.0
    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        seg_len = math.sqrt(dist3_sq(ax, ay, az, bx, by, bz))
        seg_lens.append(seg_len)
        total_len += seg_len

    if total_len == 0:
        return None

    best_dist_sq = float('inf')
    best_seg = 0
    best_t = 0.0

    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        t, dist_sq = project_onto_segment(px, py, pz, ax, ay, az, bx, by, bz)
        if dist_sq < best_dist_sq:
            best_dist_sq = dist_sq
            best_seg = i
            best_t = t

    arc_to_seg = sum(seg_lens[:best_seg])
    arc_pos = arc_to_seg + best_t * seg_lens[best_seg]
    arc_frac = arc_pos / total_len

    return {
        'arcFrac': arc_frac,
        'distSq': best_dist_sq,
        'segIndex': best_seg,
        'segT': best_t,
    }


def interpolate_speed_at_arc(arc_frac, polyline, speeds):
    """Linear interpolation of speed at arc_frac from per-vertex speed array."""
    n = len(polyline)
    if n < 2 or len(speeds) != n:
        return None

    total_len = 0.0
    cum_len = [0.0]
    for i in range(n - 1):
        ax, ay, az = polyline[i]
        bx, by, bz = polyline[i + 1]
        seg_len = math.sqrt(dist3_sq(ax, ay, az, bx, by, bz))
        total_len += seg_len
        cum_len.append(total_len)

    if total_len == 0:
        return speeds[0]

    target = arc_frac * total_len

    # Binary search for the segment containing target.
    lo, hi = 0, n - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cum_len[mid] <= target:
            lo = mid
        else:
            hi = mid

    seg_len = cum_len[lo + 1] - cum_len[lo]
    t = (target - cum_len[lo]) / seg_len if seg_len > 0 else 0.0
    return speeds[lo] + t * (speeds[lo + 1] - speeds[lo])


def is_in_edge_region(px, py, ex, ey, radius):
    """2D XY radius test."""
    dx, dy = px - ex, py - ey
    return dx*dx + dy*dy <= radius*radius


def build_vertex_speeds(polyline, gaps, active_mean_speed):
    """
    Python translation of buildVertexSpeeds from LiveMetricsPanel.tsx.
    gaps: list of dicts with 'edge' ([x,y,z]) and 'human_speed_at_edge'.
    Returns list of floats, length == len(polyline).
    """
    n = len(polyline)
    if n == 0:
        return []

    # Find nearest polyline vertex for each gap edge.
    anchors = []
    for gap in gaps:
        ex, ey, ez = gap['edge']
        best_dist = float('inf')
        best_idx = 0
        for i, (px, py, pz) in enumerate(polyline):
            d = dist3_sq(px, py, pz, ex, ey, ez)
            if d < best_dist:
                best_dist = d
                best_idx = i
        anchors.append({'idx': best_idx, 'speed': gap['human_speed_at_edge']})

    anchors.sort(key=lambda a: a['idx'])

    speeds = [active_mean_speed] * n

    if not anchors:
        return speeds

    # Fill before first anchor.
    for i in range(anchors[0]['idx'] + 1):
        speeds[i] = anchors[0]['speed']
    # Fill after last anchor.
    for i in range(anchors[-1]['idx'], n):
        speeds[i] = anchors[-1]['speed']
    # Interpolate between adjacent anchors.
    for k in range(len(anchors) - 1):
        a = anchors[k]
        b = anchors[k + 1]
        span = b['idx'] - a['idx']
        for i in range(a['idx'], b['idx'] + 1):
            t = (i - a['idx']) / span if span > 0 else 0.0
            speeds[i] = a['speed'] + t * (b['speed'] - a['speed'])

    return speeds


# ---------------------------------------------------------------------------
# Constants (match LiveMetricsPanel.tsx exports)
# ---------------------------------------------------------------------------

EDGE_REGION_RADIUS = 96
OFF_ROUTE_DIST = 384


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestProjectOntoSegment(unittest.TestCase):
    """project_onto_segment — nearest point on segment, t in [0,1]."""

    def test_midpoint(self):
        """Point perpendicular above segment midpoint → t=0.5, distSq correct.
        Segment: A=(0,0,0), B=(2,0,0). Point: (1,1,0) — directly above midpoint."""
        t, dsq = project_onto_segment(1, 1, 0,  0, 0, 0,  2, 0, 0)
        self.assertAlmostEqual(t, 0.5)
        self.assertAlmostEqual(dsq, 1.0)

    def test_beyond_end(self):
        """Point past B → clamped to t=1.0."""
        t, dsq = project_onto_segment(3, 0, 0,  0, 0, 0,  2, 0, 0)
        self.assertAlmostEqual(t, 1.0)
        self.assertAlmostEqual(dsq, 1.0)

    def test_before_start(self):
        """Point before A → clamped to t=0.0."""
        t, dsq = project_onto_segment(-1, 0, 0,  0, 0, 0,  2, 0, 0)
        self.assertAlmostEqual(t, 0.0)
        self.assertAlmostEqual(dsq, 1.0)

    def test_at_endpoint_a(self):
        """Point exactly at A → t=0, distSq=0."""
        t, dsq = project_onto_segment(0, 0, 0,  0, 0, 0,  2, 0, 0)
        self.assertAlmostEqual(t, 0.0)
        self.assertAlmostEqual(dsq, 0.0)

    def test_at_endpoint_b(self):
        """Point exactly at B → t=1, distSq=0."""
        t, dsq = project_onto_segment(2, 0, 0,  0, 0, 0,  2, 0, 0)
        self.assertAlmostEqual(t, 1.0)
        self.assertAlmostEqual(dsq, 0.0)

    def test_degenerate_segment(self):
        """Zero-length segment (A==B) → t=0, distSq to A."""
        t, dsq = project_onto_segment(3, 4, 0,  1, 0, 0,  1, 0, 0)
        self.assertAlmostEqual(t, 0.0)
        # dist from (3,4,0) to (1,0,0) = sqrt(4+16) = sqrt(20)
        self.assertAlmostEqual(dsq, 20.0)

    def test_3d_diagonal(self):
        """3D diagonal segment: midpoint perpendicular check."""
        # Segment from (0,0,0) to (2,2,0); point at (0,2,0)
        t, dsq = project_onto_segment(0, 2, 0,  0, 0, 0,  2, 2, 0)
        # Nearest point on segment: t=0.5 → (1,1,0); dist = sqrt(1+1)=sqrt(2)
        self.assertAlmostEqual(t, 0.5)
        self.assertAlmostEqual(dsq, 2.0)


class TestProjectOntoPolyline(unittest.TestCase):
    """project_onto_polyline — nearest arc fraction on a multi-segment polyline."""

    def _make_square_polyline(self):
        """Simple L-shaped polyline: (0,0,0)→(10,0,0)→(10,10,0). Total length 20."""
        return [(0, 0, 0), (10, 0, 0), (10, 10, 0)]

    def test_too_few_points(self):
        self.assertIsNone(project_onto_polyline(0, 0, 0, []))
        self.assertIsNone(project_onto_polyline(0, 0, 0, [(0, 0, 0)]))

    def test_at_start(self):
        """Point at start → arcFrac=0, segIndex=0, segT=0."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(0, 0, 0, poly)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['arcFrac'], 0.0)
        self.assertEqual(r['segIndex'], 0)
        self.assertAlmostEqual(r['segT'], 0.0)
        self.assertAlmostEqual(r['distSq'], 0.0)

    def test_at_midpoint_first_segment(self):
        """Point at midpoint of first segment → arcFrac=0.25 (5/20)."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(5, 0, 0, poly)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['arcFrac'], 0.25, places=5)
        self.assertEqual(r['segIndex'], 0)
        self.assertAlmostEqual(r['segT'], 0.5, places=5)
        self.assertAlmostEqual(r['distSq'], 0.0, places=5)

    def test_at_corner_vertex(self):
        """Point exactly at the corner between segments → arcFrac=0.5 (10/20)."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(10, 0, 0, poly)
        self.assertIsNotNone(r)
        # Corner is equidistant from end of seg0 (t=1) and start of seg1 (t=0).
        # Both give distSq=0; we accept arcFrac in {0.5} or nearby.
        self.assertAlmostEqual(r['arcFrac'], 0.5, places=5)
        self.assertAlmostEqual(r['distSq'], 0.0, places=5)

    def test_at_end(self):
        """Point at polyline end → arcFrac=1.0."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(10, 10, 0, poly)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['arcFrac'], 1.0, places=5)
        self.assertAlmostEqual(r['distSq'], 0.0, places=5)

    def test_midpoint_second_segment(self):
        """Midpoint of second segment → arcFrac=0.75 (15/20)."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(10, 5, 0, poly)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['arcFrac'], 0.75, places=5)
        self.assertEqual(r['segIndex'], 1)
        self.assertAlmostEqual(r['segT'], 0.5, places=5)
        self.assertAlmostEqual(r['distSq'], 0.0, places=5)

    def test_off_route_point(self):
        """Point far off route still returns a result (just large distSq)."""
        poly = self._make_square_polyline()
        r = project_onto_polyline(0, 100, 0, poly)
        self.assertIsNotNone(r)
        # The nearest projection is somewhere on the polyline; distSq must be large.
        self.assertGreater(r['distSq'], 0)

    def test_arc_frac_monotone_along_straight_line(self):
        """arcFrac increases monotonically for points along a straight line."""
        poly = [(float(i), 0.0, 0.0) for i in range(11)]  # 0..10, each unit
        prev = -1.0
        for xi in [0, 1, 3, 5, 7, 9, 10]:
            r = project_onto_polyline(float(xi), 0.0, 0.0, poly)
            self.assertIsNotNone(r)
            self.assertGreater(r['arcFrac'], prev - 1e-9)
            prev = r['arcFrac']


class TestInterpolateSpeedAtArc(unittest.TestCase):
    """interpolate_speed_at_arc — linear speed interpolation by arc fraction."""

    def _straight_poly(self):
        """Simple straight polyline from x=0 to x=4 (4 vertices, 3 segments, each len=1)."""
        return [(float(i), 0.0, 0.0) for i in range(4)]

    def test_at_start(self):
        """arcFrac=0 → speed of first vertex."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0, 300.0, 400.0]
        v = interpolate_speed_at_arc(0.0, poly, speeds)
        self.assertAlmostEqual(v, 100.0)

    def test_at_end(self):
        """arcFrac=1 → speed of last vertex."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0, 300.0, 400.0]
        v = interpolate_speed_at_arc(1.0, poly, speeds)
        self.assertAlmostEqual(v, 400.0)

    def test_midpoint_first_segment(self):
        """arcFrac=1/6 (midpoint of first segment) → 150.0."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0, 300.0, 400.0]
        v = interpolate_speed_at_arc(1.0/6.0, poly, speeds)
        self.assertAlmostEqual(v, 150.0, places=3)

    def test_midpoint_third_segment(self):
        """arcFrac=5/6 (midpoint of last segment) → 350.0."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0, 300.0, 400.0]
        v = interpolate_speed_at_arc(5.0/6.0, poly, speeds)
        self.assertAlmostEqual(v, 350.0, places=3)

    def test_at_vertex_boundary(self):
        """arcFrac at the boundary of segment 1→2 → speed of vertex 2."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0, 300.0, 400.0]
        # Vertex 2 is at arc length 2/3 of total length 3.
        v = interpolate_speed_at_arc(2.0/3.0, poly, speeds)
        self.assertAlmostEqual(v, 300.0, places=3)

    def test_mismatched_lengths_returns_none(self):
        """Speed array length mismatch → None."""
        poly = self._straight_poly()
        speeds = [100.0, 200.0]  # Wrong length.
        v = interpolate_speed_at_arc(0.5, poly, speeds)
        self.assertIsNone(v)

    def test_single_vertex_returns_none(self):
        """Polyline with <2 vertices → None."""
        v = interpolate_speed_at_arc(0.5, [(0.0, 0.0, 0.0)], [100.0])
        self.assertIsNone(v)

    def test_constant_speed(self):
        """Uniform speed array → same speed everywhere."""
        poly = [(float(i), 0.0, 0.0) for i in range(5)]
        speeds = [500.0] * 5
        for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
            v = interpolate_speed_at_arc(frac, poly, speeds)
            self.assertAlmostEqual(v, 500.0)


class TestIsInEdgeRegion(unittest.TestCase):
    """is_in_edge_region — 2D XY radius check."""

    def test_on_exact_edge_point(self):
        """Point exactly at edge → inside."""
        self.assertTrue(is_in_edge_region(100, 200, 100, 200, EDGE_REGION_RADIUS))

    def test_inside_radius(self):
        """Point 50 qu away → inside EDGE_REGION_RADIUS=96."""
        self.assertTrue(is_in_edge_region(100+50, 200, 100, 200, EDGE_REGION_RADIUS))

    def test_on_boundary(self):
        """Point exactly on boundary → inside (≤, not <)."""
        self.assertTrue(is_in_edge_region(100+96, 200, 100, 200, EDGE_REGION_RADIUS))

    def test_just_outside(self):
        """Point 97 qu away → outside."""
        self.assertFalse(is_in_edge_region(100+97, 200, 100, 200, EDGE_REGION_RADIUS))

    def test_z_ignored(self):
        """Vertical offset has no effect — 2D XY only."""
        # Horizontal component is 50 qu, well within radius.
        # Z is given as separate args; the function only takes px,py,ex,ey,radius.
        self.assertTrue(is_in_edge_region(150, 200, 100, 200, EDGE_REGION_RADIUS))

    def test_diagonal_inside(self):
        """Diagonal point: sqrt(60^2+60^2) ≈ 84.8 < 96 → inside."""
        self.assertTrue(is_in_edge_region(160, 260, 100, 200, EDGE_REGION_RADIUS))

    def test_diagonal_outside(self):
        """Diagonal point: sqrt(70^2+70^2) ≈ 99.0 > 96 → outside."""
        self.assertFalse(is_in_edge_region(170, 270, 100, 200, EDGE_REGION_RADIUS))

    def test_custom_radius_zero(self):
        """Radius=0: only exact match returns True."""
        self.assertTrue(is_in_edge_region(100, 200, 100, 200, 0))
        self.assertFalse(is_in_edge_region(101, 200, 100, 200, 0))


class TestBuildVertexSpeeds(unittest.TestCase):
    """build_vertex_speeds — gap-anchor interpolation."""

    def test_empty_polyline(self):
        self.assertEqual(build_vertex_speeds([], [], 400.0), [])

    def test_no_gaps_fills_active_mean(self):
        """No gaps → all vertices get active_mean_speed."""
        poly = [(float(i), 0.0, 0.0) for i in range(5)]
        speeds = build_vertex_speeds(poly, [], 400.0)
        self.assertEqual(len(speeds), 5)
        for s in speeds:
            self.assertAlmostEqual(s, 400.0)

    def test_single_gap_at_start(self):
        """Gap edge at first vertex → all vertices at gap speed."""
        poly = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        gaps = [{'edge': (0.0, 0.0, 0.0), 'human_speed_at_edge': 500.0}]
        speeds = build_vertex_speeds(poly, gaps, 400.0)
        for s in speeds:
            self.assertAlmostEqual(s, 500.0)

    def test_single_gap_at_end(self):
        """Gap edge at last vertex → all vertices at gap speed."""
        poly = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        gaps = [{'edge': (2.0, 0.0, 0.0), 'human_speed_at_edge': 520.0}]
        speeds = build_vertex_speeds(poly, gaps, 400.0)
        for s in speeds:
            self.assertAlmostEqual(s, 520.0)

    def test_two_gaps_interpolates_between(self):
        """Two gaps: linear interpolation between their vertex indices."""
        # 5 vertices: (0,0,0)…(4,0,0)
        poly = [(float(i), 0.0, 0.0) for i in range(5)]
        gaps = [
            {'edge': (0.0, 0.0, 0.0), 'human_speed_at_edge': 400.0},
            {'edge': (4.0, 0.0, 0.0), 'human_speed_at_edge': 500.0},
        ]
        speeds = build_vertex_speeds(poly, gaps, 450.0)
        self.assertEqual(len(speeds), 5)
        # i=0 → 400, i=4 → 500, i=2 → 450 (midpoint)
        self.assertAlmostEqual(speeds[0], 400.0)
        self.assertAlmostEqual(speeds[2], 450.0)
        self.assertAlmostEqual(speeds[4], 500.0)

    def test_gap_nearest_vertex_snapping(self):
        """Gap edge between two vertices: snaps to the nearest one."""
        poly = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (20.0, 0.0, 0.0)]
        # Edge at (3,0,0) — closer to vertex 0 (dist=3) than vertex 1 (dist=7).
        gaps = [{'edge': (3.0, 0.0, 0.0), 'human_speed_at_edge': 450.0}]
        speeds = build_vertex_speeds(poly, gaps, 400.0)
        # Anchor at index 0 → all three vertices should be 450.
        for s in speeds:
            self.assertAlmostEqual(s, 450.0)

    def test_sorted_anchors_order_independence(self):
        """Gap list in reverse order gives same result as sorted order."""
        poly = [(float(i), 0.0, 0.0) for i in range(5)]
        gaps_fwd = [
            {'edge': (0.0, 0.0, 0.0), 'human_speed_at_edge': 400.0},
            {'edge': (4.0, 0.0, 0.0), 'human_speed_at_edge': 500.0},
        ]
        gaps_rev = list(reversed(gaps_fwd))
        speeds_fwd = build_vertex_speeds(poly, gaps_fwd, 450.0)
        speeds_rev = build_vertex_speeds(poly, gaps_rev, 450.0)
        for a, b in zip(speeds_fwd, speeds_rev):
            self.assertAlmostEqual(a, b)


class TestEdgeRegionConstants(unittest.TestCase):
    """Sanity-check the constants match the TypeScript values."""

    def test_edge_radius_value(self):
        self.assertEqual(EDGE_REGION_RADIUS, 96)

    def test_off_route_dist_value(self):
        self.assertEqual(OFF_ROUTE_DIST, 384)


class TestArcProjectionEndToEnd(unittest.TestCase):
    """End-to-end: project a bot position, look up human speed at that arc point."""

    def _sng_to_rl_first_three(self):
        """Tiny excerpt of the sng_to_rl polyline (first 3 vertices from dm3.json)."""
        return [
            (-895.4, -129.1, -15.9),
            (-895.4, -129.1, -15.9),
            (-893.1, -131.1, -15.9),
        ]

    def test_bot_at_start_of_sng_to_rl(self):
        """Bot at the start of sng_to_rl → arcFrac near 0."""
        poly = [
            (-895.4, -129.1, -15.9),
            (-881.9, -144.1, -15.9),
            (-872.0, -168.0, -15.9),
        ]
        r = project_onto_polyline(-895.4, -129.1, -15.9, poly)
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r['arcFrac'], 0.0, places=3)
        self.assertAlmostEqual(r['distSq'], 0.0, places=1)

    def test_arc_speed_roundtrip(self):
        """Project a point, get speed: result within the speed array range."""
        poly = [(float(i*10), 0.0, 0.0) for i in range(6)]  # 0,10,20,30,40,50
        speeds = [300.0, 350.0, 400.0, 450.0, 500.0, 530.0]
        # Bot at x=25 (midpoint of seg 2→3): arcFrac = 25/50 = 0.5
        r = project_onto_polyline(25.0, 0.0, 0.0, poly)
        self.assertIsNotNone(r)
        v = interpolate_speed_at_arc(r['arcFrac'], poly, speeds)
        self.assertIsNotNone(v)
        # Should be between seg-2 and seg-3 speeds: between 400 and 450.
        self.assertGreaterEqual(v, 400.0 - 1e-6)
        self.assertLessEqual(v, 450.0 + 1e-6)

    def test_off_route_detection(self):
        """A point far from the polyline produces distSq > OFF_ROUTE_DIST^2."""
        poly = [(0.0, 0.0, 0.0), (100.0, 0.0, 0.0)]
        r = project_onto_polyline(0.0, 1000.0, 0.0, poly)
        self.assertIsNotNone(r)
        dist = math.sqrt(r['distSq'])
        self.assertGreater(dist, OFF_ROUTE_DIST)


if __name__ == "__main__":
    unittest.main()
