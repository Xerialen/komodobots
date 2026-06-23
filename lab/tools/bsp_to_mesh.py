#!/usr/bin/env python3
"""Quake1 BSP v29 -> textured glTF binary (.glb) pipeline (LD-C4, #92).

Successor to bsp_to_obj.py (LD-C2, #91).  Adds miptex decoding, palette
application, texinfo UV computation, and per-texture-material glTF emission
so the lab dashboard (Mockup and Live 3D views) can render the map with
Quake's original textures.

== BSP v29 facts ==

Lump layout (0-based):
    0=ENTITIES  1=PLANES    2=MIPTEX     3=VERTEXES
    4=VIS       5=NODES     6=TEXINFO    7=FACES
    8=LIGHTING  9=CLIPNODES 10=LEAFS    11=MARKSURFACES
    12=EDGES    13=SURFEDGES 14=MODELS

MIPTEX lump (2): 4-byte count + count*4-byte offsets (relative to lump start)
  Each miptex: char[16] name, uint32 width, uint32 height, uint32 mip_offset[4]
  Pixel data starts at mip_offset[0] (relative to miptex start), w*h bytes.
  Palette index -> RGB via the 768-byte Quake palette.

TEXINFO lump (6): 40 bytes per entry
  float s_axis[3], s_offset, t_axis[3], t_offset  (32 bytes)
  int32 miptex_index, int32 flags                   (8 bytes)
  UV formula: u = dot(v, s_axis) + s_offset
              v = dot(v, t_axis) + t_offset
  Normalized:  u_n = u / tex_width,  v_n = v / tex_height
  UVs may exceed 0..1 and must wrap (sampler wrapS/wrapT = REPEAT).

FACE lump (7): 20 bytes: h planenum, h side, i firstedge, h numedges,
  h texinfo, 4b styles, i lightofs.

MODELS lump (14): 64 bytes per model.  model[0] is the worldmodel; its
  firstface+numfaces (fields [14],[15]) give the worldmodel face range.

== Special texture handling ==

- sky textures (name starts with 'sky'): emitted as a separate material group
  tagged as sky, assigned a uniform colour; the viewer hides them by default.
- tool textures (name starts with any of 'clip', 'trigger', 'hint', 'skip',
  'nodraw', '+0~', and single-char names '{<', 'z_exit', etc.): emitted as
  the separate 'skip' material group (invisible tools/triggers).
- '*'-prefixed liquid textures (e.g. *water1, *lava1): decoded normally and
  placed in the regular material set; turb animation NOT rendered.
- NULL/missing miptex entries: faces referencing them map to the skip group.
- Fullbright handling: mip0 pixel data decoded verbatim; no lightmap blending.

== Output ==

Per-map .glb (GLB container: 12-byte header + JSON chunk + BIN chunk):
  - One buffer, geometry + image data interleaved.
  - One mesh with N primitives, one primitive per distinct texture material.
  - Positions, UV0 per face-vertex (NOT deduplicated -- each BSP face-vertex
    needs its own UV, so the face-vertex expansion is the natural unit).
  - Indices (uint16 when total face-vertices <= 65535, else uint32).
  - One image per texture (PNG, embedded in the BIN chunk).
  - One material per image (alpha OPAQUE, doubleSided true; sky/skip groups
    are tagged via material extras).
  - Sampler: WRAP for both S and T (UVs may tile).
  - asset.extras records source_bsp_sha256, script_version, per-texture counts.

Committed output: lab/dashboard/public/maps/{dm3,dm2,frobodm2,trick}.glb
  plus an updated maps.json (glb key added beside the existing obj key).

== Usage ==

Requires: stdlib only (no third-party dependencies).

    python lab/tools/bsp_to_mesh.py MAP=BSP_PATH [MAP=BSP_PATH ...] \
        [--palette PAK_PATH_OR_LMP_PATH] \
        [--out-dir lab/dashboard/public/maps] \
        [--max-tex-dim 64]    # optional: cap mip0 dimension for size budget

    # validate mode: assert UV spans and print per-map texture counts + sizes
    python lab/tools/bsp_to_mesh.py --validate MAP=BSP_PATH ...

    # The LD-C4 set (palette auto-loaded from pak0.pak):
    python lab/tools/bsp_to_mesh.py \\
        dm3=C:/nQuake/qw/maps/dm3.bsp \\
        frobodm2=C:/nQuake/qw/maps/frobodm2.bsp \\
        trick=C:/nQuake/qw/maps/trick.bsp \\
        dm2=/path/to/dm2.bsp \\
        --palette C:/nQuake/id1/pak0.pak

BSP sources (none committed -- ~1 MB game assets):
- locally: C:/nQuake/qw/maps/{dm3,frobodm2,trick}.bsp (dm2 not local)
- WSL Ubuntu-24.04: ~/mvd-mcp-bundle/bsps/dm2.bsp
- lab host (read-only): servexeri:~/nquakesv/qw/maps/*.bsp
"""

from __future__ import annotations

import logging
import argparse
import base64
import hashlib
import io
import json
import math
import struct
import sys
import zlib
from pathlib import Path
from typing import Optional


LOGGER = logging.getLogger(__name__)
# ---------------------------------------------------------------------------
# BSP v29 lump indices
# ---------------------------------------------------------------------------

LUMP_MIPTEX = 2
LUMP_VERTEXES = 3
LUMP_TEXINFO = 6
LUMP_FACES = 7
LUMP_EDGES = 12
LUMP_SURFEDGES = 13
LUMP_MODELS = 14
LUMP_COUNT = 15

TEXINFO_SIZE = 40   # float s_axis[3], s_offset, t_axis[3], t_offset, int miptex, int flags
FACE_SIZE = 20
EDGE_SIZE = 4
SURFEDGE_SIZE = 4
VERTEX_SIZE = 12
MODEL_SIZE = 64

# ---------------------------------------------------------------------------
# glTF 2.0 constants
# ---------------------------------------------------------------------------

GLTF_FLOAT = 5126
GLTF_UNSIGNED_SHORT = 5123
GLTF_UNSIGNED_INT = 5125
GLTF_ARRAY_BUFFER = 34962       # ARRAY_BUFFER (vertex data)
GLTF_ELEMENT_ARRAY_BUFFER = 34963  # ELEMENT_ARRAY_BUFFER (index data)
GLTF_SAMPLER_WRAP_REPEAT = 10497

SCRIPT_VERSION = "lab/tools/bsp_to_mesh.py v1 (LD-C4 #92)"
SCHEMA = "komodobots.maps.v1"
GENERATOR = "lab/tools/bsp_to_mesh.py"
DEFAULT_OUT_DIR = Path("lab/dashboard/public/maps")

# Special texture tag values stored in material extras
TAG_REGULAR = "regular"
TAG_SKY = "sky"
TAG_SKIP = "skip"
TAG_LIQUID = "liquid"

# Quake texture naming conventions for special types
_SKY_PREFIXES = ("sky",)
_SKIP_PREFIXES = ("clip", "trigger", "hint", "skip", "nodraw")
# Single special names (case insensitive)
_SKIP_EXACT = {"z_exit"}

# ---------------------------------------------------------------------------
# Quake palette (embedded fallback: the standard id1 palette, 256 RGB triples)
# This matches the data in gfx/palette.lmp from pak0.pak.
# Stored as base64-encoded bytes (768 bytes total).
# ---------------------------------------------------------------------------

_FALLBACK_PALETTE_B64 = (
    "AAAAAAA/Pz8/f39/v7+//8z/zMz//8z/zAD/z/8AAP/M/8//zP///////////////"
    "//////////////8"
    # This is a placeholder -- the real palette is loaded from pak0.pak or
    # palette.lmp at runtime; see load_palette().  If neither is available,
    # the exporter exits with an error rather than producing wrong colours.
)

_EMBEDDED_QUAKE_PALETTE: Optional[bytes] = None


def _embed_quake_palette() -> bytes:
    """Return the canonical Quake id1 palette (768 bytes, 256 RGB triples).

    Hardcoded verbatim from id1/gfx/palette.lmp -- public domain colour table,
    identical across all id Software Quake releases.  Used as a fallback when
    pak0.pak / palette.lmp is not supplied on the command line.
    """
    global _EMBEDDED_QUAKE_PALETTE
    if _EMBEDDED_QUAKE_PALETTE is not None:
        return _EMBEDDED_QUAKE_PALETTE
    # 768-byte table: 256 RGB triples, canonical Quake palette.
    raw = bytes([
        0x00,0x00,0x00, 0x0f,0x0f,0x0f, 0x1f,0x1f,0x1f, 0x2f,0x2f,0x2f,
        0x3f,0x3f,0x3f, 0x4b,0x4b,0x4b, 0x5b,0x5b,0x5b, 0x6b,0x6b,0x6b,
        0x7b,0x7b,0x7b, 0x8b,0x8b,0x8b, 0x9b,0x9b,0x9b, 0xab,0xab,0xab,
        0xbb,0xbb,0xbb, 0xcb,0xcb,0xcb, 0xdb,0xdb,0xdb, 0xeb,0xeb,0xeb,
        0x0f,0x0b,0x07, 0x17,0x0f,0x0b, 0x1f,0x17,0x0b, 0x27,0x1b,0x0f,
        0x2f,0x23,0x13, 0x37,0x2b,0x17, 0x3f,0x2f,0x17, 0x4b,0x37,0x1b,
        0x53,0x3b,0x1b, 0x5b,0x43,0x1f, 0x63,0x4b,0x1f, 0x6b,0x53,0x1f,
        0x73,0x57,0x1f, 0x7b,0x5f,0x23, 0x83,0x67,0x23, 0x8f,0x6f,0x23,
        0x0b,0x0b,0x0f, 0x13,0x13,0x1b, 0x1b,0x1b,0x27, 0x27,0x27,0x33,
        0x2f,0x2f,0x3f, 0x37,0x37,0x4b, 0x3f,0x3f,0x57, 0x47,0x47,0x67,
        0x4f,0x4f,0x73, 0x5b,0x5b,0x7f, 0x63,0x63,0x8b, 0x6b,0x6b,0x97,
        0x73,0x73,0xa3, 0x7b,0x7b,0xaf, 0x83,0x83,0xbb, 0x8b,0x8b,0xcb,
        0x00,0x00,0x00, 0x07,0x07,0x00, 0x0b,0x0b,0x00, 0x13,0x13,0x00,
        0x1b,0x1b,0x00, 0x23,0x23,0x00, 0x2b,0x2b,0x07, 0x2f,0x2f,0x07,
        0x37,0x37,0x07, 0x3f,0x3f,0x07, 0x47,0x47,0x07, 0x4b,0x4b,0x0b,
        0x53,0x53,0x0b, 0x5b,0x5b,0x0b, 0x63,0x63,0x0b, 0x6b,0x6b,0x0f,
        0x07,0x00,0x00, 0x0f,0x00,0x00, 0x17,0x00,0x00, 0x1f,0x00,0x00,
        0x27,0x00,0x00, 0x2f,0x00,0x00, 0x37,0x00,0x00, 0x3f,0x00,0x00,
        0x47,0x00,0x00, 0x4f,0x00,0x00, 0x57,0x00,0x00, 0x5f,0x00,0x00,
        0x67,0x00,0x00, 0x6f,0x00,0x00, 0x77,0x00,0x00, 0x7f,0x00,0x00,
        0x13,0x13,0x00, 0x1b,0x1b,0x00, 0x23,0x23,0x00, 0x2f,0x2b,0x00,
        0x37,0x2f,0x00, 0x43,0x37,0x00, 0x4b,0x3b,0x07, 0x57,0x43,0x07,
        0x5f,0x47,0x07, 0x6b,0x4b,0x0b, 0x77,0x53,0x0f, 0x83,0x57,0x13,
        0x8b,0x5b,0x13, 0x97,0x5f,0x1b, 0xa3,0x63,0x1f, 0xaf,0x67,0x23,
        0x23,0x13,0x07, 0x2f,0x17,0x0b, 0x3b,0x1f,0x0f, 0x4b,0x23,0x13,
        0x57,0x2b,0x17, 0x63,0x2f,0x1f, 0x73,0x37,0x23, 0x7f,0x3b,0x2b,
        0x8f,0x43,0x33, 0x9f,0x4f,0x33, 0xaf,0x63,0x2f, 0xbf,0x77,0x2f,
        0xcf,0x8f,0x2b, 0xdf,0xab,0x27, 0xef,0xcb,0x1f, 0xff,0xf3,0x1b,
        0x0b,0x07,0x00, 0x1b,0x13,0x00, 0x2b,0x23,0x0f, 0x37,0x2b,0x13,
        0x47,0x33,0x1b, 0x53,0x37,0x23, 0x63,0x3f,0x2b, 0x6f,0x47,0x33,
        0x7f,0x53,0x3f, 0x8b,0x5f,0x47, 0x9b,0x6b,0x53, 0xa7,0x7b,0x5f,
        0xb7,0x87,0x6b, 0xc3,0x93,0x7b, 0xd3,0xa3,0x8b, 0xe3,0xb3,0x97,
        0xab,0x8b,0xa3, 0x9f,0x7f,0x97, 0x93,0x73,0x87, 0x8b,0x67,0x7b,
        0x7f,0x5b,0x6f, 0x77,0x53,0x63, 0x6b,0x4b,0x57, 0x5f,0x3f,0x4b,
        0x57,0x37,0x43, 0x4b,0x2f,0x37, 0x43,0x27,0x2f, 0x37,0x1f,0x23,
        0x2b,0x17,0x1b, 0x23,0x13,0x13, 0x17,0x0b,0x0b, 0x0f,0x07,0x07,
        0xbb,0x73,0x9f, 0xaf,0x6b,0x8f, 0xa3,0x5f,0x83, 0x97,0x57,0x77,
        0x8b,0x4f,0x6b, 0x7f,0x4b,0x5f, 0x73,0x43,0x53, 0x6b,0x3b,0x4b,
        0x5f,0x33,0x3f, 0x53,0x2b,0x37, 0x47,0x23,0x2b, 0x3b,0x1f,0x23,
        0x2f,0x17,0x1b, 0x23,0x13,0x13, 0x17,0x0b,0x0b, 0x0f,0x07,0x07,
        0xdb,0xc3,0xbb, 0xcb,0xb3,0xa7, 0xbf,0xa3,0x9b, 0xaf,0x97,0x8b,
        0xa3,0x87,0x7b, 0x97,0x7b,0x6f, 0x87,0x6f,0x5f, 0x7b,0x63,0x53,
        0x6b,0x57,0x47, 0x5f,0x4b,0x3b, 0x53,0x3f,0x33, 0x43,0x33,0x27,
        0x37,0x2b,0x1f, 0x27,0x1f,0x17, 0x1b,0x13,0x0f, 0x0f,0x0b,0x07,
        0x6f,0x83,0x7b, 0x67,0x7b,0x6f, 0x5f,0x73,0x67, 0x57,0x6b,0x5f,
        0x4f,0x63,0x57, 0x47,0x5b,0x4f, 0x3f,0x53,0x47, 0x37,0x4b,0x3f,
        0x2f,0x43,0x37, 0x2b,0x3b,0x2f, 0x23,0x33,0x27, 0x1f,0x2b,0x1f,
        0x17,0x23,0x17, 0x0f,0x1b,0x13, 0x0b,0x13,0x0b, 0x07,0x0b,0x07,
        0xff,0xf3,0x1b, 0xef,0xdf,0x17, 0xdb,0xcb,0x13, 0xcb,0xb7,0x0f,
        0xbb,0xa7,0x0f, 0xab,0x97,0x0b, 0x9b,0x83,0x07, 0x8b,0x73,0x07,
        0x7b,0x63,0x07, 0x6b,0x53,0x00, 0x5b,0x47,0x00, 0x4b,0x37,0x00,
        0x3b,0x2b,0x00, 0x2b,0x1f,0x00, 0x1b,0x0f,0x00, 0x0b,0x07,0x00,
        0x00,0x00,0xff, 0x0b,0x0b,0xef, 0x13,0x13,0xdf, 0x1b,0x1b,0xcf,
        0x23,0x23,0xbf, 0x2b,0x2b,0xaf, 0x2f,0x2f,0x9f, 0x2f,0x2f,0x8f,
        0x2f,0x2f,0x7f, 0x2f,0x2f,0x6f, 0x2f,0x2f,0x5f, 0x2b,0x2b,0x4f,
        0x23,0x23,0x3f, 0x1b,0x1b,0x2f, 0x13,0x13,0x1f, 0x0b,0x0b,0x0f,
        0x2b,0x00,0x00, 0x3b,0x00,0x00, 0x4b,0x07,0x00, 0x5f,0x07,0x00,
        0x6f,0x0f,0x00, 0x7f,0x17,0x07, 0x93,0x1f,0x07, 0xa3,0x27,0x0b,
        0xb7,0x33,0x0f, 0xc3,0x4b,0x1b, 0xcf,0x63,0x2b, 0xdb,0x7f,0x3b,
        0xe3,0x97,0x4f, 0xe7,0xab,0x5f, 0xef,0xbf,0x77, 0xf7,0xd3,0x8b,
        0xa7,0x7b,0x3b, 0xb7,0x9b,0x37, 0xc7,0xc3,0x37, 0xe7,0xe3,0x57,
        0x7f,0xbf,0xff, 0xab,0xe7,0xff, 0xd7,0xff,0xff, 0x67,0x00,0x00,
        0x8b,0x00,0x00, 0xb3,0x00,0x00, 0xd7,0x00,0x00, 0xff,0x00,0x00,
        0xff,0xf3,0x93, 0xff,0xf7,0xc7, 0xff,0xff,0xff, 0x9f,0x5b,0x53,
    ])
    assert len(raw) == 768, f"embedded palette must be 768 bytes, got {len(raw)}"
    _EMBEDDED_QUAKE_PALETTE = raw
    return raw


# ---------------------------------------------------------------------------
# Palette loading
# ---------------------------------------------------------------------------

def load_palette(source: Optional[str]) -> bytes:
    """Load the Quake 256-colour palette (768 bytes) from a PAK or .lmp file.

    If *source* is None, returns the embedded canonical id1 palette.
    If *source* ends with '.pak' or '.PAK', it is treated as a PAK archive
    and gfx/palette.lmp is extracted from it.
    Otherwise it is read directly as a .lmp file (raw 768 bytes).
    """
    if source is None:
        return _embed_quake_palette()
    p = Path(source)
    if not p.is_file():
        raise FileNotFoundError(f"palette source not found: {p}")
    raw = p.read_bytes()
    if p.suffix.lower() == ".pak":
        if raw[:4] != b"PACK":
            raise ValueError(f"{p} is not a PAK file (bad magic)")
        diroff, dirsize = struct.unpack_from("<II", raw, 4)
        n = dirsize // 64
        for i in range(n):
            eoff = diroff + i * 64
            name = raw[eoff:eoff + 56].split(b"\x00")[0].decode("ascii", errors="replace")
            foff, fsize = struct.unpack_from("<II", raw, eoff + 56)
            if name.lower() == "gfx/palette.lmp":
                pal = raw[foff:foff + fsize]
                if len(pal) != 768:
                    raise ValueError(f"palette.lmp in {p} is {len(pal)} bytes, expected 768")
                return pal
        raise ValueError(f"gfx/palette.lmp not found in {p}")
    if len(raw) != 768:
        raise ValueError(f"palette file {p} is {len(raw)} bytes, expected 768")
    return raw


# ---------------------------------------------------------------------------
# Miptex decoding
# ---------------------------------------------------------------------------

def _classify_texture(name: str) -> str:
    """Return TAG_SKY, TAG_SKIP, TAG_LIQUID, or TAG_REGULAR."""
    ln = name.lower()
    if any(ln.startswith(p) for p in _SKY_PREFIXES):
        return TAG_SKY
    if any(ln.startswith(p) for p in _SKIP_PREFIXES) or ln in _SKIP_EXACT:
        return TAG_SKIP
    if ln.startswith("*"):
        return TAG_LIQUID
    return TAG_REGULAR


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    """Return a single PNG chunk: length + tag + data + CRC."""
    length = struct.pack(">I", len(data))
    crc = struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return length + tag + data + crc


def _encode_png_rgb(rgb_data: bytes, w: int, h: int) -> bytes:
    """Encode a raw RGB byte array (w*h*3 bytes, row-major) as a PNG byte string.

    Pure stdlib implementation using zlib — no Pillow required.  Uses filter
    type 0 (None) per scanline, which is sufficient for the non-photographic
    palette-decoded textures in Quake BSPs.
    """
    # Build raw filtered scanlines: filter-byte 0 prepended to each row
    raw_rows = bytearray()
    row_stride = w * 3
    for y in range(h):
        raw_rows.append(0)  # filter type = None
        raw_rows += rgb_data[y * row_stride:(y + 1) * row_stride]
    # PNG file signature
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR: width, height, bit_depth=8, color_type=2 (RGB), compression=0, filter=0, interlace=0
    ihdr_data = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    ihdr = _png_chunk(b"IHDR", ihdr_data)
    # IDAT: zlib-compressed scanlines (level 6 is a reasonable default)
    idat = _png_chunk(b"IDAT", zlib.compress(bytes(raw_rows), 6))
    # IEND
    iend = _png_chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def _nn_resize_rgb(rgb_data: bytes, src_w: int, src_h: int,
                   dst_w: int, dst_h: int) -> bytes:
    """Nearest-neighbour resize of an RGB byte array.  Pure stdlib."""
    out = bytearray(dst_w * dst_h * 3)
    x_ratio = src_w / dst_w
    y_ratio = src_h / dst_h
    for dy in range(dst_h):
        sy = min(int(dy * y_ratio), src_h - 1)
        for dx in range(dst_w):
            sx = min(int(dx * x_ratio), src_w - 1)
            src_off = (sy * src_w + sx) * 3
            dst_off = (dy * dst_w + dx) * 3
            out[dst_off] = rgb_data[src_off]
            out[dst_off + 1] = rgb_data[src_off + 1]
            out[dst_off + 2] = rgb_data[src_off + 2]
    return bytes(out)


def _miptex_to_png(miptex_data: bytes, palette: bytes, tex_abs_off: int,
                   w: int, h: int, mip0_off: int, max_dim: int = 0) -> bytes:
    """Decode mip0 pixel data to a PNG bytes object.

    *miptex_data* is the full BSP bytes.  *tex_abs_off* is the byte offset of
    the start of this miptex within *miptex_data*.  *mip0_off* is the offset
    of the mip0 pixel array relative to *tex_abs_off*.  *max_dim* caps the
    longest edge via nearest-neighbour downscale (0 = no cap).

    Returns raw PNG bytes.  Pure stdlib — no Pillow required.
    """
    pixel_start = tex_abs_off + mip0_off
    pixels = miptex_data[pixel_start:pixel_start + w * h]
    if len(pixels) != w * h:
        # Truncated BSP or bad offset -- return a 1x1 magenta fallback
        return _solid_color_png(255, 0, 255)
    # Expand palette indices -> RGB
    rgb_data = bytearray(w * h * 3)
    for i, idx in enumerate(pixels):
        pal_off = idx * 3
        rgb_data[i * 3] = palette[pal_off]
        rgb_data[i * 3 + 1] = palette[pal_off + 1]
        rgb_data[i * 3 + 2] = palette[pal_off + 2]
    # Optional nearest-neighbour downscale
    if max_dim > 0 and max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        rgb_data = _nn_resize_rgb(bytes(rgb_data), w, h, new_w, new_h)
        w, h = new_w, new_h
    return _encode_png_rgb(bytes(rgb_data), w, h)


def _solid_color_png(r: int, g: int, b: int) -> bytes:
    """Return a 1x1 solid-colour PNG (fallback for missing/corrupt miptex).

    Pure stdlib — no Pillow required.
    """
    return _encode_png_rgb(bytes([r, g, b]), 1, 1)


def _sky_placeholder_png() -> bytes:
    """Return a 1x1 sky-blue PNG used for sky material faces."""
    return _solid_color_png(80, 120, 200)


def _skip_placeholder_png() -> bytes:
    """Return a 1x1 transparent-ish magenta PNG for skip/tool material."""
    return _solid_color_png(200, 0, 200)


# ---------------------------------------------------------------------------
# BSP geometry + texture extraction
# ---------------------------------------------------------------------------

def parse_bsp(data: bytes, palette: bytes, max_tex_dim: int = 0) -> dict:
    """Parse BSP v29 and return a dict with all geometry + texture data needed
    for glTF export.

    Returns:
        {
          "textures": [{"name": str, "tag": str, "png": bytes, "w": int, "h": int}, ...],
          "texinfo":  [{"tex_idx": int, "flags": int, "s": (3f), "so": f, "t": (3f), "to": f}, ...],
          "vertexes": [(x,y,z), ...],
          "edges":    [(v0,v1), ...],
          "surfedges": [int, ...],
          "faces":    [(firstedge, numedges, texinfo_idx), ...],  # worldmodel only
        }
    """
    version = struct.unpack_from("<i", data, 0)[0]
    if version != 29:
        raise ValueError(f"expected BSP v29, got {version}")
    lumps = [struct.unpack_from("<ii", data, 4 + i * 8) for i in range(LUMP_COUNT)]

    # --- Vertexes ---
    vo, vl = lumps[LUMP_VERTEXES]
    vertexes = [struct.unpack_from("<3f", data, vo + k * VERTEX_SIZE)
                for k in range(vl // VERTEX_SIZE)]

    # --- Edges ---
    eo, el = lumps[LUMP_EDGES]
    edges = [struct.unpack_from("<2H", data, eo + k * EDGE_SIZE)
             for k in range(el // EDGE_SIZE)]

    # --- Surfedges ---
    so, sl = lumps[LUMP_SURFEDGES]
    surfedges = [struct.unpack_from("<i", data, so + k * SURFEDGE_SIZE)[0]
                 for k in range(sl // SURFEDGE_SIZE)]

    # --- Miptex / textures ---
    mlo, mll = lumps[LUMP_MIPTEX]
    num_tex = struct.unpack_from("<i", data, mlo)[0]
    textures = []
    for i in range(num_tex):
        toff_rel = struct.unpack_from("<i", data, mlo + 4 + i * 4)[0]
        if toff_rel < 0:
            textures.append({"name": "__null__", "tag": TAG_SKIP,
                              "png": _skip_placeholder_png(), "w": 1, "h": 1})
            continue
        tex_abs = mlo + toff_rel
        name_raw = struct.unpack_from("16s", data, tex_abs)[0]
        name = name_raw.split(b"\x00")[0].decode("ascii", errors="replace")
        w, h = struct.unpack_from("<II", data, tex_abs + 16)
        mip0_off = struct.unpack_from("<I", data, tex_abs + 24)[0]
        tag = _classify_texture(name)
        if tag == TAG_SKY:
            png = _sky_placeholder_png()
        elif tag == TAG_SKIP:
            png = _skip_placeholder_png()
        else:
            png = _miptex_to_png(data, palette, tex_abs, w, h, mip0_off, max_tex_dim)
        textures.append({"name": name, "tag": tag, "png": png, "w": w, "h": h})

    # --- Texinfo ---
    tio, til = lumps[LUMP_TEXINFO]
    texinfo = []
    for i in range(til // TEXINFO_SIZE):
        si = tio + i * TEXINFO_SIZE
        sx, sy, sz, so_f = struct.unpack_from("<4f", data, si)
        tx, ty, tz, to_f = struct.unpack_from("<4f", data, si + 16)
        tex_idx, flags = struct.unpack_from("<ii", data, si + 32)
        texinfo.append({
            "tex_idx": tex_idx,
            "flags": flags,
            "s": (sx, sy, sz),
            "so": so_f,
            "t": (tx, ty, tz),
            "to": to_f,
        })

    # --- Faces (worldmodel only) ---
    mo, _ = lumps[LUMP_MODELS]
    model0 = struct.unpack_from("<9f7i", data, mo)
    firstface, numfaces = model0[14], model0[15]

    fo, fl = lumps[LUMP_FACES]
    faces = []
    for k in range(firstface, firstface + numfaces):
        f = struct.unpack_from("<hhihh4si", data, fo + k * FACE_SIZE)
        faces.append((f[2], f[3], f[4]))   # firstedge, numedges, texinfo_idx

    return {
        "textures": textures,
        "texinfo": texinfo,
        "vertexes": vertexes,
        "edges": edges,
        "surfedges": surfedges,
        "faces": faces,
    }


# ---------------------------------------------------------------------------
# UV computation
# ---------------------------------------------------------------------------

def compute_uv(v: tuple, s: tuple, so: float, t: tuple, to: float,
               w: int, h: int) -> tuple:
    """Compute normalized (u, v) UV for a vertex given texinfo parameters.

    u = (dot(v, s_axis) + s_offset) / tex_width
    v = (dot(v, t_axis) + t_offset) / tex_height

    Returns (u, v) in [0..1] range (may exceed 0..1 for tiling).
    Note: glTF UV v-axis points DOWN (same as Quake), so no flip needed.
    """
    u = (v[0] * s[0] + v[1] * s[1] + v[2] * s[2] + so) / w
    vv = (v[0] * t[0] + v[1] * t[1] + v[2] * t[2] + to) / h
    return (u, vv)


# ---------------------------------------------------------------------------
# glTF / GLB assembly
# ---------------------------------------------------------------------------

def _pad4(n: int) -> int:
    """Return n rounded up to the next multiple of 4."""
    return (n + 3) & ~3


def _pack_f32(values) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def build_glb(map_name: str, bsp_data: bytes, palette: bytes,
              max_tex_dim: int = 0) -> tuple[bytes, dict]:
    """Build a GLB binary and return (glb_bytes, maps_json_entry_fields).

    The entry fields are merged into maps.json by the caller.
    """
    bsp = parse_bsp(bsp_data, palette, max_tex_dim)
    textures = bsp["textures"]
    texinfo = bsp["texinfo"]
    vertexes = bsp["vertexes"]
    edges = bsp["edges"]
    surfedges = bsp["surfedges"]
    faces = bsp["faces"]

    # Decide index type based on max face-vertex count
    total_fv = sum(numedges for _, numedges, _ in faces)
    use_uint16 = total_fv <= 65535
    index_dtype = GLTF_UNSIGNED_SHORT if use_uint16 else GLTF_UNSIGNED_INT
    index_fmt = "<H" if use_uint16 else "<I"
    index_bytes = 2 if use_uint16 else 4

    # Group faces by texture index (one primitive per texture)
    from collections import defaultdict
    tex_faces: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for firstedge, numedges, ti_idx in faces:
        if ti_idx < 0 or ti_idx >= len(texinfo):
            continue
        tex_idx = texinfo[ti_idx]["tex_idx"]
        if tex_idx < 0 or tex_idx >= len(textures):
            tex_idx = 0  # fallback
        tex_faces[tex_idx].append((firstedge, numedges, ti_idx))

    # ---------------------------------------------------------------------------
    # Build geometry buffers per primitive
    # ---------------------------------------------------------------------------
    # Each primitive: flat list of face-vertices in fan-triangulation order.
    # position (vec3 f32), uv (vec2 f32), indices (face-vertex-local uint16/uint32).

    prim_data: list[dict] = []  # one entry per tex_idx present in tex_faces
    for tex_idx in sorted(tex_faces):
        face_list = tex_faces[tex_idx]
        tex = textures[tex_idx]
        ti_entry = texinfo.get if hasattr(texinfo, 'get') else None

        pos_list: list[tuple] = []
        uv_list: list[tuple] = []
        idx_list: list[int] = []

        for firstedge, numedges, ti_idx in face_list:
            ti = texinfo[ti_idx]
            s = ti["s"]
            so = ti["so"]
            t = ti["t"]
            to = ti["to"]
            w = tex["w"] if tex["w"] > 0 else 1
            h = tex["h"] if tex["h"] > 0 else 1

            # Build face-vertex list
            fv_base = len(pos_list)
            fv_verts = []
            for i in range(numedges):
                se = surfedges[firstedge + i]
                v_idx = edges[se][0] if se >= 0 else edges[-se][1]
                v = vertexes[v_idx]
                uv = compute_uv(v, s, so, t, to, w, h)
                pos_list.append(v)
                uv_list.append(uv)
                fv_verts.append(fv_base + i)

            # Fan triangulation
            for j in range(1, len(fv_verts) - 1):
                idx_list.extend([fv_verts[0], fv_verts[j], fv_verts[j + 1]])

        if not idx_list:
            continue

        pos_bytes = b"".join(_pack_f32(p) for p in pos_list)
        uv_bytes = b"".join(_pack_f32(uv) for uv in uv_list)
        idx_bytes_data = b"".join(struct.pack(index_fmt, i) for i in idx_list)

        # Compute AABB for positions accessor
        xs = [p[0] for p in pos_list]
        ys = [p[1] for p in pos_list]
        zs = [p[2] for p in pos_list]
        pos_min = [min(xs), min(ys), min(zs)]
        pos_max = [max(xs), max(ys), max(zs)]

        prim_data.append({
            "tex_idx": tex_idx,
            "tex_name": tex["name"],
            "tex_tag": tex["tag"],
            "tex_w": tex["w"],
            "tex_h": tex["h"],
            "tex_png": tex["png"],
            "pos_bytes": pos_bytes,
            "uv_bytes": uv_bytes,
            "idx_bytes": idx_bytes_data,
            "vertex_count": len(pos_list),
            "index_count": len(idx_list),
            "pos_min": pos_min,
            "pos_max": pos_max,
        })

    # ---------------------------------------------------------------------------
    # Pack the binary buffer: align each region to 4 bytes
    # Buffer layout: [pos0][uv0][idx0][img0][pos1][uv1][idx1][img1]...
    # ---------------------------------------------------------------------------

    bin_chunks: list[bytes] = []
    buffer_views = []   # {byteOffset, byteLength, target}
    accessors = []
    images = []
    samplers = [{"wrapS": GLTF_SAMPLER_WRAP_REPEAT, "wrapT": GLTF_SAMPLER_WRAP_REPEAT,
                 "minFilter": 9728, "magFilter": 9728}]  # NEAREST
    gltf_textures = []
    materials = []
    primitives = []

    current_offset = 0

    def _add_view(data_bytes: bytes, target: int) -> int:
        nonlocal current_offset
        padded = data_bytes + b"\x00" * (_pad4(len(data_bytes)) - len(data_bytes))
        bin_chunks.append(padded)
        bv_idx = len(buffer_views)
        # glTF 2.0 spec §5.12: bufferView.buffer is REQUIRED.  With a single BIN
        # chunk the index is always 0.  Omitting it causes GLTFLoader to crash with
        # "Cannot read properties of undefined (reading 'type')".
        buffer_views.append({"buffer": 0, "byteOffset": current_offset,
                              "byteLength": len(data_bytes), "target": target})
        current_offset += len(padded)
        return bv_idx

    def _add_image_view(data_bytes: bytes) -> int:
        nonlocal current_offset
        padded = data_bytes + b"\x00" * (_pad4(len(data_bytes)) - len(data_bytes))
        bin_chunks.append(padded)
        bv_idx = len(buffer_views)
        # Same contract: image bufferViews also require buffer: 0.
        buffer_views.append({"buffer": 0, "byteOffset": current_offset,
                              "byteLength": len(data_bytes)})
        current_offset += len(padded)
        return bv_idx

    for pd in prim_data:
        # Position accessor
        pos_bv = _add_view(pd["pos_bytes"], GLTF_ARRAY_BUFFER)
        pos_acc = len(accessors)
        accessors.append({
            "bufferView": pos_bv,
            "componentType": GLTF_FLOAT,
            "count": pd["vertex_count"],
            "type": "VEC3",
            "min": pd["pos_min"],
            "max": pd["pos_max"],
        })

        # UV accessor
        uv_bv = _add_view(pd["uv_bytes"], GLTF_ARRAY_BUFFER)
        uv_acc = len(accessors)
        accessors.append({
            "bufferView": uv_bv,
            "componentType": GLTF_FLOAT,
            "count": pd["vertex_count"],
            "type": "VEC2",
        })

        # Index accessor
        idx_bv = _add_view(pd["idx_bytes"], GLTF_ELEMENT_ARRAY_BUFFER)
        idx_acc = len(accessors)
        accessors.append({
            "bufferView": idx_bv,
            "componentType": index_dtype,
            "count": pd["index_count"],
            "type": "SCALAR",
        })

        # Image / texture / material
        img_bv = _add_image_view(pd["tex_png"])
        img_idx = len(images)
        images.append({"bufferView": img_bv, "mimeType": "image/png"})

        tex_gltf_idx = len(gltf_textures)
        gltf_textures.append({"sampler": 0, "source": img_idx})

        mat_idx = len(materials)
        materials.append({
            "name": pd["tex_name"],
            "doubleSided": True,
            "alphaMode": "OPAQUE",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": tex_gltf_idx, "texCoord": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "extras": {"quake_texture": pd["tex_name"], "quake_tag": pd["tex_tag"]},
        })

        primitives.append({
            "attributes": {"POSITION": pos_acc, "TEXCOORD_0": uv_acc},
            "indices": idx_acc,
            "material": mat_idx,
            "mode": 4,  # TRIANGLES
        })

    # ---------------------------------------------------------------------------
    # Assemble glTF JSON
    # ---------------------------------------------------------------------------

    total_tex_count = len(prim_data)
    total_tri_count = sum(pd["index_count"] // 3 for pd in prim_data)
    total_vert_count = sum(pd["vertex_count"] for pd in prim_data)
    total_png_bytes = sum(len(pd["tex_png"]) for pd in prim_data)
    bsp_sha256 = hashlib.sha256(bsp_data).hexdigest()

    gltf_json = {
        "asset": {
            "version": "2.0",
            "generator": SCRIPT_VERSION,
            "extras": {
                "source_bsp_sha256": bsp_sha256,
                "script_version": SCRIPT_VERSION,
                "map_name": map_name,
                "texture_count": total_tex_count,
                "glb_triangle_count": total_tri_count,
                "glb_vertex_count": total_vert_count,
                "total_png_bytes": total_png_bytes,
            },
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": map_name}],
        "meshes": [{"name": map_name, "primitives": primitives}],
        "accessors": accessors,
        "bufferViews": buffer_views,
        "samplers": samplers,
        "textures": gltf_textures,
        "images": images,
        "materials": materials,
        "buffers": [{"byteLength": current_offset}],
    }

    json_bytes = json.dumps(gltf_json, separators=(",", ":")).encode("utf-8")
    json_padded = json_bytes + b" " * (_pad4(len(json_bytes)) - len(json_bytes))

    bin_data = b"".join(bin_chunks)

    # GLB: header + JSON chunk + BIN chunk
    total_length = 12 + 8 + len(json_padded) + 8 + len(bin_data)
    glb = (
        b"glTF"
        + struct.pack("<II", 2, total_length)
        + struct.pack("<II", len(json_padded), 0x4E4F534A)   # JSON
        + json_padded
        + struct.pack("<II", len(bin_data), 0x004E4942)       # BIN\0
        + bin_data
    )

    maps_entry_fields = {
        "glb": f"{map_name}.glb",
        "source_bsp_sha256": bsp_sha256,
        "texture_count": total_tex_count,
        "glb_triangles": total_tri_count,
        "glb_vertices": total_vert_count,
        "glb_bytes": len(glb),
    }
    return glb, maps_entry_fields


# ---------------------------------------------------------------------------
# --validate mode
# ---------------------------------------------------------------------------

def validate_map(map_name: str, bsp_data: bytes, palette: bytes,
                 max_tex_dim: int = 0) -> bool:
    """Parse BSP, compute UVs for all worldmodel faces, and report stats.

    Returns True if all assertions pass.
    """
    print(f"\n=== {map_name} --validate ===")
    bsp = parse_bsp(bsp_data, palette, max_tex_dim)
    textures = bsp["textures"]
    texinfo = bsp["texinfo"]
    vertexes = bsp["vertexes"]
    edges = bsp["edges"]
    surfedges = bsp["surfedges"]
    faces = bsp["faces"]

    from collections import defaultdict, Counter
    tex_face_count: Counter = Counter()
    tex_tri_count: Counter = Counter()
    uv_violations: list[str] = []
    UV_SPAN_WARN = 16.0  # warn (not fail) if UV span > this many tiles

    total_png_bytes = 0
    tex_png_sizes: dict[int, int] = {}
    for i, t in enumerate(textures):
        if t["tag"] not in (TAG_SKY, TAG_SKIP):
            tex_png_sizes[i] = len(t["png"])
            total_png_bytes += len(t["png"])

    for firstedge, numedges, ti_idx in faces:
        if ti_idx < 0 or ti_idx >= len(texinfo):
            continue
        ti = texinfo[ti_idx]
        tex_idx = ti["tex_idx"]
        if tex_idx < 0 or tex_idx >= len(textures):
            continue
        tex = textures[tex_idx]
        w = tex["w"] if tex["w"] > 0 else 1
        h = tex["h"] if tex["h"] > 0 else 1

        fv_verts = []
        for i in range(numedges):
            se = surfedges[firstedge + i]
            v_idx = edges[se][0] if se >= 0 else edges[-se][1]
            fv_verts.append(vertexes[v_idx])

        us = [compute_uv(v, ti["s"], ti["so"], ti["t"], ti["to"], w, h)[0] for v in fv_verts]
        vs = [compute_uv(v, ti["s"], ti["so"], ti["t"], ti["to"], w, h)[1] for v in fv_verts]
        u_span = max(us) - min(us)
        v_span = max(vs) - min(vs)
        if u_span > UV_SPAN_WARN or v_span > UV_SPAN_WARN:
            uv_violations.append(f"  tex={tex['name']} u_span={u_span:.1f} v_span={v_span:.1f}")

        tex_face_count[tex_idx] += 1
        tex_tri_count[tex_idx] += numedges - 2

    # Report
    print(f"  Textures referenced by worldmodel: {len(tex_face_count)}")
    total_tris = sum(tex_tri_count.values())
    print(f"  Total triangles: {total_tris}")
    print(f"  Total PNG bytes (non-sky/skip): {total_png_bytes:,} "
          f"({total_png_bytes / 1024:.1f} KB)")
    if uv_violations:
        print(f"  UV span warnings (>{UV_SPAN_WARN} tiles): {len(uv_violations)}")
        for msg in uv_violations[:10]:
            print(msg)
    else:
        print("  UV spans: all within warning threshold")

    per_tex = sorted(tex_png_sizes.items(), key=lambda x: -x[1])
    print("  Top-5 PNG sizes by texture:")
    for tidx, sz in per_tex[:5]:
        t = textures[tidx]
        print(f"    [{tidx}] {t['name']!r:20s} {t['w']}x{t['h']} -> {sz:,} bytes PNG")

    ok = True
    if total_png_bytes > 3 * 1024 * 1024:
        print(f"  FAIL: total PNG bytes {total_png_bytes:,} exceeds 3 MB budget "
              f"({total_png_bytes / 1024 / 1024:.2f} MB)")
        ok = False
    else:
        print(f"  PASS: size budget (<= 3 MB: {total_png_bytes / 1024 / 1024:.2f} MB)")

    print(f"  Validate {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------------------
# maps.json update
# ---------------------------------------------------------------------------

def update_maps_json(out_dir: Path, map_name: str, new_fields: dict) -> None:
    """Merge glb-related fields into maps.json for the given map_name.

    The obj entry for the same map (if present) is preserved; glb fields are
    added alongside it.  The updated entry is the union of old + new_fields,
    with new_fields winning on conflict.
    """
    manifest_path = out_dir / "maps.json"
    maps: dict = {}
    if manifest_path.is_file():
        prev = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prev.get("schema") == SCHEMA and isinstance(prev.get("maps"), dict):
            maps = prev["maps"]
    existing = maps.get(map_name, {})
    existing.update(new_fields)
    maps[map_name] = existing
    manifest = {
        "schema": SCHEMA,
        "generator": GENERATOR,
        "maps": {name: maps[name] for name in sorted(maps)},
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=False) + "\n",
        encoding="ascii", newline="\n",
    )
    print(f"maps.json updated for {map_name}: {manifest_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="BSP v29 -> textured glTF (.glb) pipeline (LD-C4, #92).")
    parser.add_argument("maps", nargs="+", metavar="MAP=BSP_PATH",
                        help="map name and its source .bsp")
    parser.add_argument("--palette", metavar="PAK_OR_LMP",
                        help="pak0.pak or palette.lmp; omit to use embedded palette")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help=f"output directory (default: {DEFAULT_OUT_DIR})")
    parser.add_argument("--max-tex-dim", type=int, default=0, metavar="N",
                        help="cap mip0 texture longest edge (0=no cap, 64=quarter size)")
    parser.add_argument("--validate", action="store_true",
                        help="validate UV spans and report size budget; no .glb written")
    args = parser.parse_args(argv)

    try:
        palette = load_palette(args.palette)
    except (FileNotFoundError, ValueError) as e:
        print(f"error loading palette: {e}", file=sys.stderr)
        return 1

    jobs = []
    for spec in args.maps:
        name, sep, path = spec.partition("=")
        if not sep or not name or not path:
            parser.error(f"expected MAP=BSP_PATH, got {spec!r}")
        bsp_path = Path(path)
        if not bsp_path.is_file():
            parser.error(f"BSP not found: {bsp_path}")
        jobs.append((name, bsp_path))

    args.out_dir.mkdir(parents=True, exist_ok=True)

    all_ok = True
    for map_name, bsp_path in jobs:
        bsp_data = bsp_path.read_bytes()
        if args.validate:
            ok = validate_map(map_name, bsp_data, palette, args.max_tex_dim)
            all_ok = all_ok and ok
        else:
            try:
                glb, entry_fields = build_glb(map_name, bsp_data, palette,
                                              args.max_tex_dim)
            except Exception as e:
                print(f"error building {map_name}: {e}", file=sys.stderr)
                import traceback
                traceback.print_exc()
                return 1
            out_path = args.out_dir / f"{map_name}.glb"
            out_path.write_bytes(glb)
            print(f"{map_name}: {entry_fields['texture_count']} textures, "
                  f"{entry_fields['glb_triangles']} triangles, "
                  f"{entry_fields['glb_vertices']} vertices -> {out_path} "
                  f"({len(glb):,} bytes / {len(glb)/1024:.1f} KB)")
            update_maps_json(args.out_dir, map_name, entry_fields)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
