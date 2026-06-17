/* See move_world_view.h. Transliteration of scripts/move_world_view.py. */
#include "move_world_view.h"

/* Native-only: QVM has no libm (hypot/atan2/sin/cos), and the live world-view
 * is a native-only feature. Under Q3_VM this whole TU is a no-op. The parity
 * test (tests/test_live_c_parity.py) compiles with Q3_VM undefined. */
#ifndef Q3_VM

#include <math.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/* Python's `%` is a FLOORED modulo: a - floor(a/b)*b, so for a positive divisor
 * the result is always in [0, b). C's fmod takes the sign of the dividend, so
 * fmod(-20, 360) == -20 while Python's (-20) % 360 == 340. wrap180 feeds on
 * (yaw - vhead), which is routinely negative, so using fmod here would diverge
 * from move_world_view.py for any left-of-heading look. Replicate Python's `%`. */
static double py_mod(double a, double b)
{
    double r = fmod(a, b);
    if (r != 0.0 && ((r < 0.0) != (b < 0.0)))
    {
        r += b;
    }
    return r;
}

double mwv_wrap180(double d)
{
    /* move_world_view.wrap180: (d + 180.0) % 360.0 - 180.0 */
    return py_mod(d + 180.0, 360.0) - 180.0;
}

/* math.degrees / math.radians are a single multiply by a constant in CPython
 * (x * (180.0 / pi) / x * (pi / 180.0)); M_PI == CPython's Py_MATH_PI, so these
 * match bit-for-bit. */
static double deg(double r) { return r * (180.0 / M_PI); }
static double rad(double d) { return d * (M_PI / 180.0); }

void mwv_state_features(double vx, double vy, double vz,
                        double yaw, double pitch,
                        float out[MWV_FEATURE_DIM])
{
    double hsp = hypot(vx, vy);
    double moving = (hsp >= MWV_MOVING_EPS) ? 1.0 : 0.0;
    double lvm_sin, lvm_cos;

    if (moving != 0.0)
    {
        double vhead = deg(atan2(vy, vx));
        double lvm = rad(mwv_wrap180(yaw - vhead));
        lvm_sin = sin(lvm);
        lvm_cos = cos(lvm);
    }
    else
    {
        lvm_sin = 0.0;
        lvm_cos = 0.0;
    }

    out[0] = (float) (hsp / MWV_MAXSPEED);
    out[1] = (float) (vz / MWV_MAXSPEED);
    out[2] = (float) lvm_sin;
    out[3] = (float) lvm_cos;
    out[4] = (float) moving;
    out[5] = (float) (pitch / MWV_PITCH_NORM);
}

#endif /* !Q3_VM */
