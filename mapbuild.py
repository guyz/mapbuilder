"""
mapbuild.py – tri-biome Wang generator *with sparse décor patches*
------------------------------------------------------------------
If assets/solid_<biome>.png exists, the strip is sliced into
one ‘pure’ tile (always index 0) plus N decorative frames.
These extra frames are sprinkled on the interior according to
two biome-specific knobs:

    PATCH_FREQ[biome]   • spatial frequency of Perlin noise
    DENSITY[biome]      • probability (0-1) that a tile inside a
                          high-noise patch uses a decorative frame

Defaults give ~8 % flowers on grass, ~4 % shells on sand, etc.
"""

import math, random
from pathlib import Path
import numpy as np
from PIL import Image
from noise import pnoise2                           # Perlin noise

# ────────────────────────────────────────────────────────────
# global knobs you might tweak
# ────────────────────────────────────────────────────────────
TILE        = 32
GRID        = 128           # world size in tiles
SEED        = 42
WATER_FREQ  = 1.2
DESERT_FREQ = 1.0
WATER_TH    = -0.10
DESERT_TH   =  0.20
BUFFER_DIST = 2

ASSETS_DIR  = Path("assets")
PAIR_IMG = {("water",  "grass"):  "transition_grass_water.png",
            ("grass",  "desert"): "transition_grass_desert.png",
            ("water",  "desert"): "transition_desert_water.png"}   # hi_low order

# Décor parameters by biome (add more if you add biomes)
PATCH_FREQ = dict(grass=8.0, desert=7.0, water=9.0)   # lower→larger blobs
DENSITY    = dict(grass=0.25, desert=0.15, water=0.10) # fraction inside blob

# ────────────────────────────────────────────────────────────
# helper – slice a 4×4 Wang sheet
# ────────────────────────────────────────────────────────────
def slice_sheet(path: Path):
    img = Image.open(path).convert("RGBA")
    return [img.crop(((i % 4)*TILE,
                      (i // 4)*TILE,
                      (i % 4 + 1)*TILE,
                      (i // 4 + 1)*TILE))
            for i in range(16)]

SHEETS, HI_LO = {}, {}
for pair, fname in PAIR_IMG.items():
    sheet = slice_sheet(ASSETS_DIR / fname)
    hi, lo = Path(fname).stem.split("_")[-2:]
    SHEETS[pair] = sheet
    HI_LO[pair]  = (hi, lo)

# ── build PURE + optional DECORATIVE tiles ─────────────────
PURE = {}        # biome → PIL (canonical)
EXTRA = {}       # biome → list[PIL] of decorative frames

for pair, sheet in SHEETS.items():
    hi, lo = HI_LO[pair]
    PURE.setdefault(hi, sheet[15])
    PURE.setdefault(lo, sheet[0])

for biome in PURE:
    strip_path = ASSETS_DIR / f"solid_{biome}.png"
    frames = []
    if strip_path.is_file():
        strip = Image.open(strip_path).convert("RGBA")
        cols = strip.width // TILE
        for c in range(cols):
            tile = strip.crop((c*TILE, 0, (c+1)*TILE, TILE))
            frames.append(tile)
    EXTRA[biome] = frames               # may be empty list

# ────────────────────────────────────────────────────────────
# deterministic Perlin wrappers
# ────────────────────────────────────────────────────────────
def perlin(nx, ny, freq, base):
    """Perlin in range [-1,1]"""
    return pnoise2(nx*freq, ny*freq, octaves=4, base=base)

def decor_noise(biome, x, y):
    freq = PATCH_FREQ.get(biome, 8.0)
    base = hash(biome) & 0xFFFF
    return perlin(x/GRID, y/GRID, freq, base)  # [-1,1]

rng = random.Random(SEED)

# ────────────────────────────────────────────────────────────
# 1.  assign a biome to every *corner*
# ────────────────────────────────────────────────────────────
corners = np.full((GRID+1, GRID+1), "grass", dtype=object)
for y in range(GRID+1):
    for x in range(GRID+1):
        nx, ny = x/GRID, y/GRID
        if perlin(nx, ny, WATER_FREQ, 101) < WATER_TH:
            corners[y,x] = "water"
        elif perlin(nx, ny, DESERT_FREQ, 202) > DESERT_TH:
            corners[y,x] = "desert"

# enforce water-desert gap
water = (corners == "water").astype(np.uint8)
buf   = np.zeros_like(water)
for k in range(1, BUFFER_DIST+1):
    buf |= np.pad(water[k:,   :], ((0,k),(0,0))) \
        |  np.pad(water[:-k,  :], ((k,0),(0,0))) \
        |  np.pad(water[:, k:], ((0,0),(0,k))) \
        |  np.pad(water[:, :-k],((0,0),(k,0)))
corners[(buf==1) & (corners=="desert")] = "grass"

# ────────────────────────────────────────────────────────────
# 2.  tile output image
# ────────────────────────────────────────────────────────────
out = Image.new("RGBA", (GRID*TILE, GRID*TILE))

def sheet_for_pair(a,b):
    if (a,b) in SHEETS:   key=(a,b)
    else:                 key=(b,a)
    return SHEETS[key], *HI_LO[key]

def pick_interior_tile(biome, x, y):
    """
    Return a deterministic, varied tile for a mono-biome cell.
    • Outside a high-noise patch   → canonical PURE tile.
    • Inside a patch               → one of the EXTRA frames,
      chosen by a coordinate hash so neighbouring cells can differ.
    """
    extras = EXTRA[biome]
    if not extras:                     # no decorative frames
        return PURE[biome]

    n = decor_noise(biome, x, y)       # [-1,1]
    if n < 0.0 or rng.random() > DENSITY.get(biome, 0.2):
        return PURE[biome]             # keep plain tile

    # --- inside a patch ------------------------------------------------
    # Produce a stable pseudorandom index: mix grid coords with biome hash
    h = (x * 0x45d9f3b + y * 0x2c1b3c6 + (hash(biome) & 0xFFFF)) & 0xFFFFFFFF
    idx = h % len(extras)
    return extras[idx]


for y in range(GRID):
    for x in range(GRID):
        nw, ne = corners[y,x],   corners[y,x+1]
        sw, se = corners[y+1,x], corners[y+1,x+1]
        palette = {nw,ne,sw,se}

        # single-biome cell
        if len(palette)==1:
            tile = pick_interior_tile(nw, x, y)
            out.paste(tile, (x*TILE, y*TILE))
            continue

        # exactly two biomes → Wang transition
        if len(palette)==2:
            a,b = palette
            sheet, hi, lo = sheet_for_pair(a,b)
            def bit(bm): return 1 if bm==hi else 0
            code = (bit(ne)<<0)|(bit(se)<<1)|(bit(sw)<<2)|(bit(nw)<<3)
            out.paste(sheet[code], (x*TILE, y*TILE))
            continue

        # rare fallback (shouldn’t happen)
        maj = max(palette, key=[nw,ne,sw,se].count)
        out.paste(PURE[maj], (x*TILE, y*TILE))

# ────────────────────────────────────────────────────────────
# 3.  save & preview
# ────────────────────────────────────────────────────────────
out_path = ASSETS_DIR / "wang_multi_biome.png"
out.save(out_path)
out.show()

vals,cnts = np.unique(corners, return_counts=True)
print("corner biome counts:", dict(zip(vals,map(int,cnts))), "→", out_path)
