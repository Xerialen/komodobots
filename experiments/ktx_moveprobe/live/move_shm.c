/* See move_shm.h. Mirrors scripts/move_policy_sidecar.py byte-for-byte. */
/* Expose POSIX ftruncate/mmap/munmap under strict -std=c11 (glibc hides them
 * without a feature-test macro -> implicit declaration + a miscompiled 64-bit
 * off_t arg). Must precede every include. */
#define _POSIX_C_SOURCE 200809L
#include "move_shm.h"

#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

/* ------------------------------------------------------------------ *
 *  Little-endian field access (x86_64 is LE; KTX's box is x86_64).
 *  memcpy avoids alignment / strict-aliasing pitfalls.
 * ------------------------------------------------------------------ */
static void put_u32(uint8_t *p, uint32_t v) { memcpy(p, &v, 4); }
static uint32_t get_u32(const uint8_t *p) { uint32_t v; memcpy(&v, p, 4); return v; }
static void put_f32(uint8_t *p, float v) { memcpy(p, &v, 4); }
static float get_f32(const uint8_t *p) { float v; memcpy(&v, p, 4); return v; }

/* ------------------------------------------------------------------ *
 *  Guard load/store. SEQ_CST atomics double as full compiler+CPU
 *  barriers, so the body writes between an odd publish and an even
 *  publish cannot be reordered across the guards.
 * ------------------------------------------------------------------ */
static uint32_t guard_load(const uint8_t *g)
{
    uint32_t v;
    __atomic_load((const uint32_t *) g, &v, __ATOMIC_SEQ_CST);
    return v;
}
static void guard_store(uint8_t *g, uint32_t v)
{
    __atomic_store((uint32_t *) g, &v, __ATOMIC_SEQ_CST);
}

/* ------------------------------------------------------------------ *
 *  seqlock write/read on a record at `slot_ptr` with the given body
 *  size. Identical protocol to move_policy_sidecar._seqlock_write /
 *  _seqlock_read. The body mutation is performed by `fill` (writer) or
 *  `take` (reader) operating on the body pointer (slot_ptr + 4).
 * ------------------------------------------------------------------ */
typedef void (*body_fill_fn)(uint8_t *body, void *ctx);
typedef void (*body_take_fn)(const uint8_t *body, void *ctx);

static void seqlock_write(uint8_t *slot_ptr, size_t body_size,
                          body_fill_fn fill, void *ctx)
{
    uint8_t *tail = slot_ptr + 4 + body_size;
    uint32_t g = guard_load(slot_ptr);
    uint32_t g_odd = (g + 1u) | 1u;       /* next odd value */
    /* Mark BOTH guards in-progress before the body so head==tail can never be a
     * stale matching even pair while the body is mutating. */
    guard_store(slot_ptr, g_odd);
    guard_store(tail, g_odd);
    fill(slot_ptr + 4, ctx);
    uint32_t g_even = g_odd + 1u;          /* next even value */
    /* Publish to the trailing guard first, the leading guard last. */
    guard_store(tail, g_even);
    guard_store(slot_ptr, g_even);
}

static int seqlock_read(const uint8_t *slot_ptr, size_t body_size,
                        body_take_fn take, void *ctx, int retries)
{
    const uint8_t *tail = slot_ptr + 4 + body_size;
    int n = retries < 1 ? 1 : retries;
    int i;
    for (i = 0; i < n; i++)
    {
        uint32_t ga = guard_load(slot_ptr);
        if (ga & 1u)            /* odd -> writer mid-write, retry */
        {
            continue;
        }
        take(slot_ptr + 4, ctx);
        uint32_t gb = guard_load(tail);
        if (ga == gb)           /* matching even pair -> untorn write */
        {
            return 1;
        }
    }
    return 0;
}

#define SEQLOCK_RETRIES 16

/* ------------------------------------------------------------------ *
 *  Offsets
 * ------------------------------------------------------------------ */
size_t mshm_view_base(int slot) { return (size_t) slot * MSHM_VIEW_SLOT_SIZE; }
size_t mshm_move_base(int slot)
{
    return (size_t) MSHM_VIEW_BLOCK_SIZE + (size_t) slot * MSHM_MOVE_SLOT_SIZE;
}

/* ------------------------------------------------------------------ *
 *  VIEW writer (KTX role)
 * ------------------------------------------------------------------ */
struct view_ctx {
    uint32_t req_seq;
    const float *feats;
    int valid;
};

static void view_fill(uint8_t *body, void *vctx)
{
    struct view_ctx *c = (struct view_ctx *) vctx;
    int i;
    put_u32(body + 0, c->req_seq);
    for (i = 0; i < MWV_FEATURE_DIM; i++)
    {
        put_f32(body + 4 + 4 * i, c->feats[i]);
    }
    body[4 + 4 * MWV_FEATURE_DIM] = (uint8_t) (c->valid ? 1 : 0);  /* offset 28 */
    /* pad bytes 29..31 left as-is (zeroed at create). */
}

void mshm_write_view(void *region, int slot, uint32_t req_seq,
                     const float feats[MWV_FEATURE_DIM], int valid)
{
    uint8_t *base = (uint8_t *) region + mshm_view_base(slot);
    struct view_ctx ctx;
    ctx.req_seq = req_seq;
    ctx.feats = feats;
    ctx.valid = valid;
    seqlock_write(base, MSHM_VIEW_BODY_SIZE, view_fill, &ctx);
}

/* ------------------------------------------------------------------ *
 *  MOVE reader (KTX role)
 * ------------------------------------------------------------------ */
static void move_take(const uint8_t *body, void *vout)
{
    mshm_move_t *out = (mshm_move_t *) vout;
    out->ans_seq = get_u32(body + 0);
    out->fwd = (int) (int8_t) body[4];
    out->side = (int) (int8_t) body[5];
    out->jump = (int) (uint8_t) body[6];
    /* body[7] is pad */
    out->move[0] = get_f32(body + 8);
    out->move[1] = get_f32(body + 12);
    out->move[2] = get_f32(body + 16);
}

int mshm_read_move(void *region, int slot, mshm_move_t *out)
{
    const uint8_t *base = (const uint8_t *) region + mshm_move_base(slot);
    memset(out, 0, sizeof(*out));
    return seqlock_read(base, MSHM_MOVE_BODY_SIZE, move_take, out, SEQLOCK_RETRIES);
}

/* ------------------------------------------------------------------ *
 *  Region lifecycle
 * ------------------------------------------------------------------ */
static int shm_path(char *buf, size_t n, const char *name)
{
    int w = snprintf(buf, n, "/dev/shm/%s", name);
    return (w > 0 && (size_t) w < n) ? 0 : -1;
}

void *mshm_create(const char *name)
{
    char path[256];
    int fd;
    void *map;
    int slot;
    static const float zeros[MWV_FEATURE_DIM] = {0, 0, 0, 0, 0, 0};

    if (shm_path(path, sizeof(path), name) != 0)
    {
        return NULL;
    }
    fd = open(path, O_CREAT | O_RDWR, 0600);
    if (fd < 0)
    {
        return NULL;
    }
    if (ftruncate(fd, MSHM_REGION_SIZE) != 0)
    {
        close(fd);
        return NULL;
    }
    map = mmap(NULL, MSHM_REGION_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    if (map == MAP_FAILED)
    {
        return NULL;
    }
    /* Zero, then seed each VIEW invalid (MOVE records stay all-zero, which reads
     * back as a clean even-guard ans_seq=0 -> "no answer yet"). Mirrors the
     * sidecar's create_region clean-start contract. */
    memset(map, 0, MSHM_REGION_SIZE);
    for (slot = 0; slot < MSHM_MAX_SLOTS; slot++)
    {
        mshm_write_view(map, slot, 0, zeros, 0);
    }
    return map;
}

void *mshm_open(const char *name)
{
    char path[256];
    int fd;
    void *map;

    if (shm_path(path, sizeof(path), name) != 0)
    {
        return NULL;
    }
    fd = open(path, O_RDWR);
    if (fd < 0)
    {
        return NULL;
    }
    map = mmap(NULL, MSHM_REGION_SIZE, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    close(fd);
    return (map == MAP_FAILED) ? NULL : map;
}

void mshm_close(void *region)
{
    if (region)
    {
        munmap(region, MSHM_REGION_SIZE);
    }
}

void mshm_unlink(const char *name)
{
    char path[256];
    if (shm_path(path, sizeof(path), name) == 0)
    {
        unlink(path);
    }
}
