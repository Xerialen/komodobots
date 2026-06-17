/* Shared world-view feature module -- C port (bot-program T0.3, docs/18 wall #2).
 *
 * BYTE-FOR-BYTE parity target: scripts/move_world_view.py:state_features (T0.4),
 * the single source of truth the offline dataset builder and the live MoveMLP
 * sidecar (scripts/move_policy_sidecar.py, T0.6) both use. KTX's live mode (T0.3)
 * writes the world-view from this C code; if it diverges from the Python module
 * the policy sees train/serve skew and gets confused. The CI byte-match gate
 * tests/test_live_c_parity.py pins this equality, so this file must stay a
 * line-for-line transliteration of the Python -- including Python's *floored*
 * modulo semantics in wrap180 (see move_world_view.c).
 *
 * Pure C + libm (hypot/atan2/sin/cos), no engine types, so the same translation
 * unit compiles standalone for the test harness AND inside the KTX .so (PR-B).
 */
#ifndef KOMODO_MOVE_WORLD_VIEW_H
#define KOMODO_MOVE_WORLD_VIEW_H

/* Feature vector order is load-bearing: it is the column order of the offline X
 * matrix and MoveMLP's input order (move_world_view.FEATURE_NAMES). */
#define MWV_FEATURE_DIM 6

/* Constants mirror move_world_view.py exactly. */
#define MWV_MAXSPEED   320.0  /* maxspeed / full-deflection normaliser (qu/s) */
#define MWV_MOVING_EPS 1.0    /* below this |v_h| the heading is undefined     */
#define MWV_PITCH_NORM 90.0   /* view-pitch normaliser (degrees)               */

/* Wrap an angle in degrees to (-180, 180], matching move_world_view.wrap180
 * (which uses Python's floored `%`, NOT C fmod -- see the .c). */
double mwv_wrap180(double d);

/* Compute the 6 world-view features for one frame's STATE, in FEATURE_NAMES
 * order: (hspeed/320, vz/320, lvm_sin, lvm_cos, moving, pitch/90).
 *
 * The body is computed in double (matching Python's math module, which operates
 * on C doubles) and written to `out` as float -- the f32 wire precision the shm
 * VIEW record stores (struct "<...6f...>"). So C and Python agree at the bits
 * that actually cross the transport.
 *
 *   vx, vy, vz : velocity components (qu/s)
 *   yaw        : view yaw   (degrees, angles[YAW])
 *   pitch      : view pitch (degrees, angles[PITCH])
 */
void mwv_state_features(double vx, double vy, double vz,
                        double yaw, double pitch,
                        float out[MWV_FEATURE_DIM]);

#endif /* KOMODO_MOVE_WORLD_VIEW_H */
