/* CLI harness for the C live unit (bot-program T0.3), driven by the CI parity
 * gate tests/test_live_c_parity.py. Each command exercises one production role
 * of the C side so Python can assert byte-for-byte agreement over a shared
 * /dev/shm region. Floats are printed as raw IEEE-754 hex (memcpy bits) so the
 * comparison is exact, not text-rounded.
 *
 * Commands:
 *   sizes
 *       print every layout constant (Python asserts == the sidecar module).
 *   features <vx> <vy> <vz> <yaw> <pitch>
 *       print the 6 world-view features as f32 hex bits.
 *   features_batch
 *       read "<vx> <vy> <vz> <yaw> <pitch>" lines from stdin until EOF; print
 *       one 6-hex-bits line per input (one subprocess for a whole grid).
 *   create <name>
 *       mshm_create the region (KTX owns creation); print "ok <REGION_SIZE>".
 *   write_view <name> <slot> <req_seq> <vx> <vy> <vz> <yaw> <pitch> <valid>
 *       compute the world-view in C and publish it (KTX writer role).
 *   write_view_feats <name> <slot> <req_seq> <f0>..<f5> <valid>
 *       publish given f32 features directly (isolates the shm layout from math).
 *   read_move <name> <slot>
 *       read the MOVE record (KTX reader role); print
 *       "<fresh> <ans_seq> <fwd> <side> <jump> <mx> <my> <mz>" (floats hex).
 *
 * Handoff-gate commands (bot-program T3.1 #422; drive tests/test_move_highway.py):
 *   radii
 *       print "<R_ON> <R_OFF> <R_ARRIVE> <R_GOAL>" (the move_highway.h gate radii, qu).
 *   nearest <x> <y>
 *       print "<dist> <which>": Euclidean (x,y) distance to the nearest base highway
 *       polyline and that highway's index (-1 if none).
 *   engaged <slot> <bx> <by> <have_goal> <gx> <gy>
 *       print the latched gate result (0/1) for one call from a fresh process.
 *   engaged_seq
 *       read "<slot> <bx> <by> <have_goal> <gx> <gy>" lines from stdin until EOF; print one
 *       0/1 per line in ONE process so the per-slot latch/hysteresis persists across the steps.
 */
#include "move_shm.h"
#include "move_highway.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static unsigned f32bits(float f)
{
    uint32_t u;
    memcpy(&u, &f, 4);
    return (unsigned) u;
}

static int cmd_sizes(void)
{
    printf("VIEW_BODY=%d MOVE_BODY=%d VIEW_SLOT=%d MOVE_SLOT=%d "
           "VIEW_BLOCK=%d MOVE_BLOCK=%d REGION=%d FEATURE_DIM=%d MAX_SLOTS=%d\n",
           MSHM_VIEW_BODY_SIZE, MSHM_MOVE_BODY_SIZE,
           MSHM_VIEW_SLOT_SIZE, MSHM_MOVE_SLOT_SIZE,
           MSHM_VIEW_BLOCK_SIZE, MSHM_MOVE_BLOCK_SIZE,
           MSHM_REGION_SIZE, MWV_FEATURE_DIM, MSHM_MAX_SLOTS);
    return 0;
}

static int cmd_features(char **a)
{
    float out[MWV_FEATURE_DIM];
    int i;
    mwv_state_features(atof(a[0]), atof(a[1]), atof(a[2]), atof(a[3]), atof(a[4]), out);
    for (i = 0; i < MWV_FEATURE_DIM; i++)
    {
        printf("%08x%s", f32bits(out[i]), i + 1 < MWV_FEATURE_DIM ? " " : "\n");
    }
    return 0;
}

static int cmd_features_batch(void)
{
    char line[256];
    while (fgets(line, sizeof(line), stdin))
    {
        double vx, vy, vz, yaw, pitch;
        float out[MWV_FEATURE_DIM];
        int i;
        if (sscanf(line, "%lf %lf %lf %lf %lf", &vx, &vy, &vz, &yaw, &pitch) != 5)
        {
            continue;  /* skip blank/short lines */
        }
        mwv_state_features(vx, vy, vz, yaw, pitch, out);
        for (i = 0; i < MWV_FEATURE_DIM; i++)
        {
            printf("%08x%s", f32bits(out[i]), i + 1 < MWV_FEATURE_DIM ? " " : "\n");
        }
    }
    return 0;
}

static int cmd_create(const char *name)
{
    void *r = mshm_create(name);
    if (!r)
    {
        fprintf(stderr, "create failed\n");
        return 2;
    }
    mshm_close(r);
    printf("ok %d\n", MSHM_REGION_SIZE);
    return 0;
}

static int cmd_write_view(const char *name, char **a)
{
    void *r;
    float feats[MWV_FEATURE_DIM];
    int slot = atoi(a[0]);
    uint32_t req = (uint32_t) strtoul(a[1], NULL, 10);
    int valid = atoi(a[7]);
    r = mshm_open(name);
    if (!r) { fprintf(stderr, "open failed\n"); return 2; }
    mwv_state_features(atof(a[2]), atof(a[3]), atof(a[4]), atof(a[5]), atof(a[6]), feats);
    mshm_write_view(r, slot, req, feats, valid);
    mshm_close(r);
    printf("ok\n");
    return 0;
}

static int cmd_write_view_feats(const char *name, char **a)
{
    void *r;
    float feats[MWV_FEATURE_DIM];
    int i;
    int slot = atoi(a[0]);
    uint32_t req = (uint32_t) strtoul(a[1], NULL, 10);
    int valid = atoi(a[2 + MWV_FEATURE_DIM]);
    for (i = 0; i < MWV_FEATURE_DIM; i++)
    {
        feats[i] = (float) atof(a[2 + i]);
    }
    r = mshm_open(name);
    if (!r) { fprintf(stderr, "open failed\n"); return 2; }
    mshm_write_view(r, slot, req, feats, valid);
    mshm_close(r);
    printf("ok\n");
    return 0;
}

static int cmd_read_move(const char *name, char **a)
{
    void *r;
    mshm_move_t mv;
    int fresh;
    int slot = atoi(a[0]);
    r = mshm_open(name);
    if (!r) { fprintf(stderr, "open failed\n"); return 2; }
    fresh = mshm_read_move(r, slot, &mv);
    mshm_close(r);
    printf("%d %u %d %d %d %08x %08x %08x\n",
           fresh, mv.ans_seq, mv.fwd, mv.side, mv.jump,
           f32bits(mv.move[0]), f32bits(mv.move[1]), f32bits(mv.move[2]));
    return 0;
}

static int cmd_radii(void)
{
    printf("%g %g %g %g\n", MHW_R_ON, MHW_R_OFF, MHW_R_ARRIVE, MHW_R_GOAL);
    return 0;
}

static int cmd_nearest(char **a)
{
    int which = -1;
    double d2 = mhw_nearest_base_highway(atof(a[0]), atof(a[1]), &which);
    printf("%.6f %d\n", sqrt(d2), which);
    return 0;
}

static int cmd_engaged(char **a)
{
    int r = mhw_handoff_engaged(atoi(a[0]), atof(a[1]), atof(a[2]),
                                atoi(a[3]), atof(a[4]), atof(a[5]));
    printf("%d\n", r);
    return 0;
}

static int cmd_engaged_seq(void)
{
    char line[256];
    while (fgets(line, sizeof(line), stdin))
    {
        int slot, hg;
        double bx, by, gx, gy;
        if (sscanf(line, "%d %lf %lf %d %lf %lf", &slot, &bx, &by, &hg, &gx, &gy) != 6)
        {
            continue;  /* skip blank/short lines */
        }
        printf("%d\n", mhw_handoff_engaged(slot, bx, by, hg, gx, gy));
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2)
    {
        fprintf(stderr, "usage: %s <command> [args...]\n", argv[0]);
        return 1;
    }
    const char *cmd = argv[1];
    char **a = argv + 2;
    int n = argc - 2;

    if (strcmp(cmd, "sizes") == 0 && n == 0) return cmd_sizes();
    if (strcmp(cmd, "features") == 0 && n == 5) return cmd_features(a);
    if (strcmp(cmd, "features_batch") == 0 && n == 0) return cmd_features_batch();
    if (strcmp(cmd, "create") == 0 && n == 1) return cmd_create(a[0]);
    if (strcmp(cmd, "write_view") == 0 && n == 9) return cmd_write_view(a[0], a + 1);
    if (strcmp(cmd, "write_view_feats") == 0 && n == 10)
        return cmd_write_view_feats(a[0], a + 1);
    if (strcmp(cmd, "read_move") == 0 && n == 2) return cmd_read_move(a[0], a + 1);
    if (strcmp(cmd, "radii") == 0 && n == 0) return cmd_radii();
    if (strcmp(cmd, "nearest") == 0 && n == 2) return cmd_nearest(a);
    if (strcmp(cmd, "engaged") == 0 && n == 6) return cmd_engaged(a);
    if (strcmp(cmd, "engaged_seq") == 0 && n == 0) return cmd_engaged_seq();

    fprintf(stderr, "bad command '%s' (n=%d)\n", cmd, n);
    return 1;
}
