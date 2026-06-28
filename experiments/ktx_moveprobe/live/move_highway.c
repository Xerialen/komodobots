/* See move_highway.h. The geometric handoff gate the KTX live mode consults to decide whether the
 * bot is on a trained base highway (yield to the Motor Cortex) or off it (stock Commander drives). */
#include "move_highway.h"

/* Native-only: under Q3_VM there is no live handoff (the whole live mode is native-only), so this
 * TU is a no-op there. The standalone test harness compiles with Q3_VM undefined. */
#ifndef Q3_VM

#include <float.h>

/* Generated base-highway geometry: MHW_N_BASE, MHW_MAX_PTS, MHW_NPTS[], MHW_END[][2],
 * MHW_PTS[][MHW_MAX_PTS][2]. AUTO-GENERATED -- regenerate via
 * experiments/route_observatory/gen_route_canon_header.py, never hand-edit. */
#include "route_canon_dm3.h"

/* Slots 0..7 (matches the live mode's MSHM_MAX_SLOTS). Kept local so this unit stays free of the
 * shm transport's types. */
#define MHW_MAX_SLOTS 8

/* Squared distance from point (px,py) to segment [(ax,ay),(bx,by)]. */
static double mhw_seg_dist2(double px, double py,
                            double ax, double ay, double bx, double by)
{
    double dx = bx - ax, dy = by - ay;
    double l2 = dx * dx + dy * dy;
    double t, cx, cy;
    if (l2 <= 0.0)            /* degenerate segment (duplicate trajectory points) -> point */
    {
        dx = px - ax; dy = py - ay;
        return dx * dx + dy * dy;
    }
    t = ((px - ax) * dx + (py - ay) * dy) / l2;
    if (t < 0.0) t = 0.0;
    else if (t > 1.0) t = 1.0;
    cx = ax + t * dx; cy = ay + t * dy;
    dx = px - cx; dy = py - cy;
    return dx * dx + dy * dy;
}

/* Squared distance between two points. */
static double mhw_dist2(double ax, double ay, double bx, double by)
{
    double dx = ax - bx, dy = ay - by;
    return dx * dx + dy * dy;
}

double mhw_nearest_base_highway(double x, double y, int *which)
{
    double best = DBL_MAX;
    int    best_i = -1;
    int    h, i, n;

    for (h = 0; h < MHW_N_BASE; h++)
    {
        n = MHW_NPTS[h];
        if (n <= 0)
        {
            continue;
        }
        if (n == 1)
        {
            double d2 = mhw_dist2(x, y, MHW_PTS[h][0][0], MHW_PTS[h][0][1]);
            if (d2 < best) { best = d2; best_i = h; }
            continue;
        }
        for (i = 0; i + 1 < n; i++)
        {
            double d2 = mhw_seg_dist2(x, y,
                                      MHW_PTS[h][i][0],     MHW_PTS[h][i][1],
                                      MHW_PTS[h][i + 1][0], MHW_PTS[h][i + 1][1]);
            if (d2 < best) { best = d2; best_i = h; }
        }
    }
    if (which)
    {
        *which = best_i;
    }
    return best;
}

int mhw_handoff_engaged(int slot, double bx, double by, int have_goal, double gx, double gy)
{
    static int engaged[MHW_MAX_SLOTS];        /* C zero-init -> disengaged */
    static int engaged_which[MHW_MAX_SLOTS];
    int    which = -1;
    double d2, end2, goalend2;

    if ((slot < 0) || (slot >= MHW_MAX_SLOTS))
    {
        return 0;            /* out of range -> stock Commander */
    }

    d2 = mhw_nearest_base_highway(bx, by, &which);
    if (which < 0)
    {
        engaged[slot] = 0;   /* no base highways -> Commander */
        return 0;
    }
    end2 = mhw_dist2(bx, by, MHW_END[which][0], MHW_END[which][1]);
    goalend2 = have_goal ? mhw_dist2(gx, gy, MHW_END[which][0], MHW_END[which][1]) : DBL_MAX;

    if (engaged[slot])
    {
        /* Stay engaged (hysteresis) until a yield-back condition trips: drifted off the line,
         * arrived at the end, lost the Commander's intent, or the nearest base highway changed. */
        if ((d2 > (MHW_R_OFF * MHW_R_OFF))
            || (end2 <= (MHW_R_ARRIVE * MHW_R_ARRIVE))
            || (!have_goal)
            || (goalend2 > (MHW_R_GOAL * MHW_R_GOAL))
            || (which != engaged_which[slot]))
        {
            engaged[slot] = 0;
        }
    }
    else
    {
        /* Engage only with Commander intent (goal toward this highway's end) AND precise on-line
         * membership (within R_ON of the polyline). */
        if ((d2 <= (MHW_R_ON * MHW_R_ON))
            && have_goal
            && (goalend2 <= (MHW_R_GOAL * MHW_R_GOAL)))
        {
            engaged[slot] = 1;
            engaged_which[slot] = which;
        }
    }
    return engaged[slot];
}

#endif /* !Q3_VM */
