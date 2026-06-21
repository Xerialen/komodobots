"""Egocentric geometry (C3).

Transforms world-frame positions/velocities into the observer's own frame, so the
agent sees relative geometry (forward/left/up, bearing, pitch, distance) rather than
absolute world coords — the representation that generalizes across spawn points and
makes a policy translation/rotation invariant.

QuakeWorld angle convention: yaw in degrees, 0 = +x (east), 90 = +y (north),
measured counter-clockwise in the XY plane. Pitch in degrees, positive = looking down
(Quake's inverted pitch); callers pass whatever their state uses — only the relative
pitch geometry below is computed from positions, independent of that convention.
"""
from __future__ import annotations

import logging
import math



LOGGER = logging.getLogger(__name__)
def egocentric_xy(target_xy, observer_xy, observer_yaw_deg: float) -> tuple[float, float]:
    """Rotate the world XY offset (target - observer) into the observer frame.

    Returns (forward, left): forward is along the observer's yaw, left is +90 deg
    from it. This is a rotation of the world delta by -yaw.
    """
    dx = target_xy[0] - observer_xy[0]
    dy = target_xy[1] - observer_xy[1]
    c = math.cos(math.radians(observer_yaw_deg))
    s = math.sin(math.radians(observer_yaw_deg))
    forward = dx * c + dy * s
    left = -dx * s + dy * c
    return (forward, left)


def egocentric_vec(vec_xy, observer_yaw_deg: float) -> tuple[float, float]:
    """Rotate a world-frame XY vector (e.g. a velocity) into the observer frame.
    Same rotation as egocentric_xy but with no translation."""
    c = math.cos(math.radians(observer_yaw_deg))
    s = math.sin(math.radians(observer_yaw_deg))
    return (vec_xy[0] * c + vec_xy[1] * s, -vec_xy[0] * s + vec_xy[1] * c)


def rel_distance(target_pos, observer_pos) -> float:
    """Euclidean distance in world units (3D)."""
    return math.dist(target_pos, observer_pos)


def rel_bearing_deg(target_pos, observer_pos, observer_yaw_deg: float) -> float:
    """Horizontal bearing to target in the observer frame, degrees in (-180,180].
    0 = directly ahead, +90 = to the left. Feed to sincos() for the model."""
    fwd, left = egocentric_xy(target_pos[:2], observer_pos[:2], observer_yaw_deg)
    return math.degrees(math.atan2(left, fwd))


def rel_pitch_deg(target_pos, observer_pos) -> float:
    """Elevation angle to target, degrees in [-90,90]. Positive = target is above
    the observer. Computed purely from positions (convention-independent)."""
    dz = target_pos[2] - observer_pos[2]
    horiz = math.dist(target_pos[:2], observer_pos[:2])
    return math.degrees(math.atan2(dz, horiz)) if horiz > 1e-9 else (90.0 if dz > 0 else -90.0 if dz < 0 else 0.0)
