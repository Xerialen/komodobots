/* POSIX-shm live-brain transport -- C side (bot-program T0.3).
 *
 * BYTE-FOR-BYTE parity target: scripts/move_policy_sidecar.py (T0.6), which owns
 * the canonical layout + the odd/even two-guard seqlock. KTX is the WRITER of the
 * VIEW record (world-view, KTX -> sidecar) and the READER of the MOVE record
 * (decision, sidecar -> KTX); the sidecar is the mirror. This unit implements
 * exactly those two production roles plus region lifecycle. The CI byte-match
 * gate (tests/test_live_c_parity.py) drives this C side against the Python module
 * over a shared /dev/shm region in both directions.
 *
 * Region (one /dev/shm file, same as the sidecar's open_region): a regular file
 * under /dev/shm, mmapped -- NOT shm_open, matching the Python which uses
 * os.open("/dev/shm/<name>"). So no -lrt is needed.
 *
 *   layout: [ VIEW[0..MAX-1] ][ MOVE[0..MAX-1] ]
 *   each record: guard_a(u32) | body | guard_b(u32)   (little-endian)
 *     VIEW body "<I6fB3x" : req_seq(u32) 6*f32 valid(u8) pad(3)  = 32 bytes
 *     MOVE body "<IbbBx3f" : ans_seq(u32) fwd(i8) side(i8) jump(u8) pad(1)
 *                            3*f32                                = 20 bytes
 *
 * seqlock: the writer marks BOTH guards odd before mutating the body, then
 * publishes the next even value to the TRAILING guard first and the LEADING
 * guard last; the reader retries until guard_a == guard_b AND even. This is the
 * Codex-reviewed T0.6 fix (sidecar commit 953ad70) -- a single odd-leading-guard
 * scheme lets a reader accept a torn body, so do not "simplify" it.
 */
#ifndef KOMODO_MOVE_SHM_H
#define KOMODO_MOVE_SHM_H

#include <stdint.h>
#include <stddef.h>

#include "move_world_view.h"

#define MSHM_MAX_SLOTS 4

/* Body sizes (struct.calcsize of the sidecar formats). */
#define MSHM_VIEW_BODY_SIZE 32  /* "<I6fB3x"  : 4 + 24 + 1 + 3 */
#define MSHM_MOVE_BODY_SIZE 20  /* "<IbbBx3f" : 4 + 1 + 1 + 1 + 1 + 12 */

/* seqlock framing adds a leading + trailing u32 guard. */
#define MSHM_VIEW_SLOT_SIZE (4 + MSHM_VIEW_BODY_SIZE + 4)  /* 40 */
#define MSHM_MOVE_SLOT_SIZE (4 + MSHM_MOVE_BODY_SIZE + 4)  /* 28 */

#define MSHM_VIEW_BLOCK_SIZE (MSHM_MAX_SLOTS * MSHM_VIEW_SLOT_SIZE)  /* 160 */
#define MSHM_MOVE_BLOCK_SIZE (MSHM_MAX_SLOTS * MSHM_MOVE_SLOT_SIZE)  /* 112 */
#define MSHM_REGION_SIZE     (MSHM_VIEW_BLOCK_SIZE + MSHM_MOVE_BLOCK_SIZE)  /* 272 */

/* Decoded MOVE record (the sidecar's answer KTX applies). */
typedef struct {
    uint32_t ans_seq;   /* the req_seq the sidecar answered (freshness key) */
    int      fwd;        /* {-1,0,1} forwardmove sign */
    int      side;       /* {-1,0,1} sidemove sign */
    int      jump;       /* {0,1} */
    float    move[3];    /* fwd*320, side*320, 0 (the sidecar's precomputed scale) */
} mshm_move_t;

/* Region lifecycle. Return NULL on failure (errno set). KTX owns create+zero;
 * the sidecar attaches via mshm_open. */
void *mshm_create(const char *name);  /* O_CREAT, ftruncate, zero + seed slots */
void *mshm_open(const char *name);    /* attach to an existing region */
void  mshm_close(void *region);
void  mshm_unlink(const char *name);

/* Byte offset of a slot's record within the region. */
size_t mshm_view_base(int slot);
size_t mshm_move_base(int slot);

/* VIEW writer (KTX role): publish a world-view for `slot` under the seqlock.
 * `feats` is the MWV_FEATURE_DIM f32 vector from mwv_state_features. */
void mshm_write_view(void *region, int slot, uint32_t req_seq,
                     const float feats[MWV_FEATURE_DIM], int valid);

/* MOVE reader (KTX role): read the decision for `slot` under the seqlock.
 * Returns 1 if a consistent (untorn) record was read into *out, 0 if every
 * retry caught a write in flight (KTX then treats the slot as stale ->
 * fallback). The application freshness check keys on out->ans_seq. */
int mshm_read_move(void *region, int slot, mshm_move_t *out);

#endif /* KOMODO_MOVE_SHM_H */
