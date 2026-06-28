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

/* Squared min (x,y) distance from (x,y) to base highway h's polyline (point-to-segment). */
static double mhw_line_dist2(int h, double x, double y)
{
    int    n = MHW_NPTS[h];
    double best = DBL_MAX;
    int    i;

    if (n <= 0)
    {
        return DBL_MAX;
    }
    if (n == 1)
    {
        return mhw_dist2(x, y, MHW_PTS[h][0][0], MHW_PTS[h][0][1]);
    }
    for (i = 0; i + 1 < n; i++)
    {
        double d2 = mhw_seg_dist2(x, y,
                                  MHW_PTS[h][i][0],     MHW_PTS[h][i][1],
                                  MHW_PTS[h][i + 1][0], MHW_PTS[h][i + 1][1]);
        if (d2 < best) { best = d2; }
    }
    return best;
}

double mhw_nearest_base_highway(double x, double y, int *which)
{
    double best = DBL_MAX;
    int    best_i = -1;
    int    h;

    for (h = 0; h < MHW_N_BASE; h++)
    {
        double d2 = mhw_line_dist2(h, x, y);
        if (d2 < best) { best = d2; best_i = h; }
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
    int    h;

    if ((slot < 0) || (slot >= MHW_MAX_SLOTS))
    {
        return 0;            /* out of range -> stock Commander */
    }

    if (engaged[slot])
    {
        /* Stay engaged on the SPECIFIC highway we latched (engaged_which), with hysteresis, until
         * a yield-back condition trips: drifted off ITS line, arrived at ITS end, or lost the
         * Commander's intent toward ITS end. No "nearest changed" check -- the engaged highway is
         * tracked explicitly, so a momentarily-closer overlapping corridor cannot churn it. */
        int    w = engaged_which[slot];
        double d2 = mhw_line_dist2(w, bx, by);
        double end2 = mhw_dist2(bx, by, MHW_END[w][0], MHW_END[w][1]);
        double goalend2 = have_goal ? mhw_dist2(gx, gy, MHW_END[w][0], MHW_END[w][1]) : DBL_MAX;
        if ((d2 > (MHW_R_OFF * MHW_R_OFF))
            || (end2 <= (MHW_R_ARRIVE * MHW_R_ARRIVE))
            || (!have_goal)
            || (goalend2 > (MHW_R_GOAL * MHW_R_GOAL)))
        {
            engaged[slot] = 0;
        }
        return engaged[slot];
    }

    /* Disengaged: select by INTENT first. Among base highways whose END the Commander's goal is
     * heading for (within R_GOAL), pick the one whose polyline is nearest the bot, and engage it
     * iff that nearest is within R_ON. Intent-first (not global-nearest-first) so that on
     * overlapping dm3 corridors the bot latches the highway it actually intends to run -- not
     * whichever line happens to be a quu closer. Requires a goal (no intent -> Commander). */
    if (!have_goal)
    {
        return 0;
    }
    {
        int    best_h = -1;
        double best_d2 = DBL_MAX;
        for (h = 0; h < MHW_N_BASE; h++)
        {
            double goalend2 = mhw_dist2(gx, gy, MHW_END[h][0], MHW_END[h][1]);
            /* Arrival is a STICKY yield-back: a highway whose end the bot is already sitting at
             * (within R_ARRIVE) is excluded from fresh engagement, so the arrival-disengage above
             * cannot immediately re-latch (the endpoint is on the polyline, so it would otherwise
             * pass d2 <= R_ON). Commander keeps control until the bot moves off the endpoint toward
             * a goal/highway it has not arrived at. Drift-disengage is unaffected (re-engage there
             * still just needs to come back within R_ON, away from the end). */
            if (goalend2 <= (MHW_R_GOAL * MHW_R_GOAL)
                && mhw_dist2(bx, by, MHW_END[h][0], MHW_END[h][1]) > (MHW_R_ARRIVE * MHW_R_ARRIVE))
            {
                double d2 = mhw_line_dist2(h, bx, by);
                if (d2 < best_d2) { best_d2 = d2; best_h = h; }
            }
        }
        if ((best_h >= 0) && (best_d2 <= (MHW_R_ON * MHW_R_ON)))
        {
            engaged[slot] = 1;
            engaged_which[slot] = best_h;
        }
    }
    return engaged[slot];
}

#endif /* !Q3_VM */
