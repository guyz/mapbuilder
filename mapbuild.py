"""
mapbuild.py  –  multi-biome Wang-corner terrain generator
---------------------------------------------------------
requirements:
    pip install pillow noise
directory layout expected:
    assets/
        transition_grass_water.png
        transition_grass_desert.png
        transition_desert_water.png
            (each is a 4×4 = 128×128 PNG, indices 0-15 row-major)

The first biome name in the PNG filename is the HIGH layer,
the second is the LOW layer, e.g.  transition_grass_water → high=grass, low=water
"""

import os, math, random
from pathlib import Path
import numpy as np
from PIL import Image
from noise import pnoise2             # Perlin

# ────────────────────────────────────────────────────────────
# global knobs
# ────────────────────────────────────────────────────────────
TILE        = 32          # pixel edge of one tile
GRID        = 128         # number of tiles along one axis
SEED        = 42
WATER_FREQ  = 1.2         # ↓ lower ⇒ bigger blobs
DESERT_FREQ = 1.0
WATER_TH    = -0.10       # Perlin value < WATER_TH  → water
DESERT_TH   =  0.20       # Perlin value > DESERT_TH → desert
BUFFER_DIST = 2           # Manhattan distance separating water & desert
ASSETS_DIR  = Path("assets")

# ────────────────────────────────────────────────────────────
# tileset helpers
# ────────────────────────────────────────────────────────────
PAIR_IMG = {("water",  "grass"):  "transition_grass_water.png",
            ("grass",  "desert"): "transition_grass_desert.png",
            ("water",  "desert"): "transition_desert_water.png"}   # high_low in PNG

def split_tileset(img_path: Path):
    """return list[16] of 32×32 PIL tiles cropped from 4×4 sheet"""
    img = Image.open(img_path).convert("RGBA")
    return [img.crop(((idx % 4)*TILE,
                      (idx // 4)*TILE,
                      (idx % 4 + 1)*TILE,
                      (idx // 4 + 1)*TILE))
            for idx in range(16)]

SHEETS  = {}   # (water,grass) → [16 PILs]
HI_LO   = {}   # (water,grass) → ("grass","water")

for pair, fname in PAIR_IMG.items():
    sheet_path = ASSETS_DIR / fname
    SHEETS[pair] = split_tileset(sheet_path)

    # parse "transition_<high>_<low>.png"
    stem_parts = sheet_path.stem.split("_")   # ['transition', 'grass', 'water']
    hi, lo = stem_parts[-2], stem_parts[-1]
    HI_LO[pair] = (hi, lo)

# build a “pure” tile cache so areas of one biome use a single image
PURE_TILE = {}   # biome → PIL.Image
for pair, sheet in SHEETS.items():
    hi, lo = HI_LO[pair]
    PURE_TILE.setdefault(hi, sheet[15])   # all-high tile
    PURE_TILE.setdefault(lo, sheet[0])    # all-low  tile

# ────────────────────────────────────────────────────────────
# noise helpers
# ────────────────────────────────────────────────────────────
rng = random.Random(SEED)

def perlin(nx: float, ny: float, freq: float, seed_shift: int):
    """Perlin in range -1 … +1"""
    return pnoise2(nx*freq, ny*freq, octaves=4, base=SEED+seed_shift)

# ────────────────────────────────────────────────────────────
# 1. generate corner biome grid
# ────────────────────────────────────────────────────────────
corners = np.full((GRID+1, GRID+1), "grass", dtype=object)

for y in range(GRID+1):
    for x in range(GRID+1):
        nx, ny = x / GRID, y / GRID
        w_val  = perlin(nx, ny, WATER_FREQ, 101)
        d_val  = perlin(nx, ny, DESERT_FREQ, 202)

        if w_val < WATER_TH:
            corners[y, x] = "water"
        elif d_val > DESERT_TH:
            corners[y, x] = "desert"

# ── enforce WATER-to-DESERT buffer (convert desert tiles inside buffer → grass)
water_mask = (corners == "water").astype(np.uint8)
buffer     = np.zeros_like(water_mask)
for k in range(1, BUFFER_DIST+1):
    buffer |= np.pad(water_mask[k:,   :], ((0,k),(0,0))) \
           |  np.pad(water_mask[:-k,  :], ((k,0),(0,0))) \
           |  np.pad(water_mask[:, k:], ((0,0),(0,k))) \
           |  np.pad(water_mask[:, :-k],((0,0),(k,0)))
corners[(buffer == 1) & (corners == "desert")] = "grass"

# ────────────────────────────────────────────────────────────
# 2. stitch output image tile-by-tile
# ────────────────────────────────────────────────────────────
out_img = Image.new("RGBA", (GRID*TILE, GRID*TILE))

def find_sheet_and_orientation(biome_a: str, biome_b: str):
    """Return (sheet[16], hiBiome, loBiome) for this unordered pair"""
    if (biome_a, biome_b) in SHEETS:
        key = (biome_a, biome_b)
    elif (biome_b, biome_a) in SHEETS:
        key = (biome_b, biome_a)
    else:
        raise KeyError(f"No tileset for pair ({biome_a}, {biome_b})")
    sheet = SHEETS[key]
    hi, lo = HI_LO[key]
    return sheet, hi, lo

for y in range(GRID):
    for x in range(GRID):
        nw, ne = corners[y,   x], corners[y,   x+1]
        sw, se = corners[y+1, x], corners[y+1, x+1]
        palette = {nw, ne, sw, se}

        if len(palette) == 1:
            # interior of a single biome
            biome = palette.pop()
            tile  = PURE_TILE[biome]
            out_img.paste(tile, (x*TILE, y*TILE))
            continue

        if len(palette) != 2:
            # rare safety fallback: collapse to majority biome
            majority = max(palette, key=[nw, ne, sw, se].count)
            out_img.paste(PURE_TILE[majority], (x*TILE, y*TILE))
            continue

        a, b = palette
        sheet, hi, lo = find_sheet_and_orientation(a, b)

        def bit(corner_biome):
            return 1 if corner_biome == hi else 0

        code = (bit(ne) << 0) | (bit(se) << 1) | (bit(sw) << 2) | (bit(nw) << 3)
        out_img.paste(sheet[code], (x*TILE, y*TILE))

# ────────────────────────────────────────────────────────────
# 3. export & report
# ────────────────────────────────────────────────────────────
out_path = ASSETS_DIR / "wang_multi_biome.png"
out_img.save(out_path)
out_img.show()

vals, counts = np.unique(corners, return_counts=True)
print("corner biome counts:", dict(zip(vals, map(int, counts))), "→", out_path)
