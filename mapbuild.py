"""
mapbuild.py – plug-and-play Wang terrain
================================================
• Edit the BIOMES dict to add / remove terrain types.
• Any transition sheet named  assets/transition_<high>_<low>.png
  is loaded automatically (order = high, low in filename).
• If two adjacent biomes have no sheet, the cell collapses to
  the one with higher priority (lower number).
"""

import random, re
from pathlib import Path
import numpy as np
from PIL import Image
from noise import pnoise2

# ───────────────────────────────────────────────
# 0. Map-level knobs
# ───────────────────────────────────────────────
TILE, GRID, SEED = 32, 128, 0
ASSETS           = Path("assets")
RNG              = random.Random(SEED)

def perlin(nx, ny, freq, base):
    return pnoise2(nx*freq, ny*freq, octaves=4, base=SEED+base)

# ───────────────────────────────────────────────
# 1.  BIOME catalogue  (add / remove here)
#     priority: lower  → more dominant when fixing adjacencies
#     fallback: biome to fall back to if this one disappears
# ───────────────────────────────────────────────
BIOMES = {
    "water": dict(
        rule      = lambda nx,ny: perlin(nx,ny,1.2,101) < -0.10,
        priority  = 0,
        patch_f   = 9,  density = 0.10,
        fallback  = "grass"
    ),
    "desert": dict(
        rule      = lambda nx,ny: perlin(nx,ny,1.0,202) > 0.20,
        priority  = 2,
        patch_f   = 7,  density = 0.15,
        fallback  = "darkgrass"
    ),
    "darkgrass": dict(
        rule      = lambda nx,ny: perlin(nx,ny,1.1,303) < -0.05,
        priority  = 1,
        patch_f   = 7,  density = 0.18,
        fallback  = "grass"
    ),
    "grass": dict(                              # default
        rule      = lambda nx,ny: True,
        priority  = 3,
        patch_f   = 8,  density = 0.25,
        fallback  = "grass"
    ),
    # Example: to add snow, uncomment below
    # "snow": dict(
    #     rule      = lambda nx,ny: perlin(nx,ny,0.9,404) > 0.25,
    #     priority  = 1,
    #     patch_f   = 8,  density = 0.14,
    #     fallback  = "grass"
    # ),
}

PRIORITY = {b: d["priority"] for b, d in BIOMES.items()}
FALLBACK = {b: d["fallback"] for b, d in BIOMES.items()}
PATCH_F  = {b: d["patch_f"]  for b, d in BIOMES.items()}
DENSITY  = {b: d["density"]  for b, d in BIOMES.items()}

# ───────────────────────────────────────────────
# 2.  Load every transition sheet present
# ───────────────────────────────────────────────
sheet_pat = re.compile(r"transition_(\w+)_(\w+)\.png")
SHEETS, HI_LO = {}, {}
for png in ASSETS.glob("transition_*_*.png"):
    if not (m := sheet_pat.match(png.name)): continue
    hi, lo = m.groups()
    img = Image.open(png).convert("RGBA")
    tiles = [img.crop(((i%4)*TILE, (i//4)*TILE,
                       (i%4+1)*TILE, (i//4+1)*TILE))
             for i in range(16)]
    SHEETS[(hi, lo)] = tiles
    HI_LO[(hi, lo)]  = (hi, lo)

# canonical interior + optional décor frames
PURE, EXTRA = {}, {}
for (hi, lo), sheet in SHEETS.items():
    PURE.setdefault(hi, sheet[15]); PURE.setdefault(lo, sheet[0])

for biome in PURE:
    strip = ASSETS / f"solid_{biome}.png"
    frames = []
    if strip.is_file():
        img = Image.open(strip).convert("RGBA")
        frames = [img.crop((c*TILE, 0, (c+1)*TILE, TILE))
                  for c in range(img.width // TILE)]
    EXTRA[biome] = frames

# ───────────────────────────────────────────────
# 3.  Assign biome to every map corner
# ───────────────────────────────────────────────
corners = np.empty((GRID+1, GRID+1), object)
ORDER = list(BIOMES.keys())          # evaluation order

for y in range(GRID+1):
    ny = y / GRID
    for x in range(GRID+1):
        nx = x / GRID
        for b in ORDER:
            if BIOMES[b]["rule"](nx, ny):
                corners[y, x] = b
                break

# ───────────────────────────────────────────────
# 4.  Generic adjacency repair
#     • Any neighbouring pair with no sheet collapses the
#       lower-priority corner to its fallback biome.
#     • Iterate until stable (rarely >2 passes).
# ───────────────────────────────────────────────
valid_pairs = set(SHEETS) | {tuple(reversed(p)) for p in SHEETS}

def fix_adjacent():
    changed = 0
    for y in range(GRID):
        for x in range(GRID):
            # horizontal edge
            a, b = corners[y, x], corners[y, x+1]
            if a != b and (a, b) not in valid_pairs:
                loser = a if PRIORITY[a] > PRIORITY[b] else b
                corners[y, x if loser == a else x+1] = FALLBACK.get(loser, "grass")
                changed += 1
            # vertical edge
            a, b = corners[y, x], corners[y+1, x]
            if a != b and (a, b) not in valid_pairs:
                loser = a if PRIORITY[a] > PRIORITY[b] else b
                corners[y if loser == a else y+1, x] = FALLBACK.get(loser, "grass")
                changed += 1
    return changed

for _ in range(4):
    if fix_adjacent() == 0:
        break

# ───────────────────────────────────────────────
# 5.  Render
# ───────────────────────────────────────────────
img = Image.new("RGBA", (GRID*TILE, GRID*TILE))

def interior(b, x, y):
    frames = EXTRA[b]
    if not frames:
        return PURE[b]
    n = perlin(x/GRID, y/GRID, PATCH_F[b], hash(b) & 0xFFFF)
    if n < 0 or RNG.random() > DENSITY[b]:
        return PURE[b]
    h = (x*0x45d9f3b + y*0x2c1b3c6 + hash(b)) & 0xFFFFFFFF
    return frames[h % len(frames)]

def sheet_for(a, b):
    return SHEETS.get((a, b)) or SHEETS.get((b, a))

for y in range(GRID):
    for x in range(GRID):
        nw, ne = corners[y,   x], corners[y,   x+1]
        sw, se = corners[y+1, x], corners[y+1, x+1]
        kinds  = {nw, ne, sw, se}

        if len(kinds) == 1:        # interior
            img.paste(interior(nw, x, y), (x*TILE, y*TILE))
            continue
        if len(kinds) == 2:        # legal transition?
            a, b = tuple(kinds)
            sheet = sheet_for(a, b)
            if sheet:
                hi, _ = HI_LO.get((a, b)) or HI_LO.get((b, a))
                bit   = lambda z: 1 if z == hi else 0
                code  = (bit(ne)<<0)|(bit(se)<<1)|(bit(sw)<<2)|(bit(nw)<<3)
                img.paste(sheet[code], (x*TILE, y*TILE))
                continue
        # fallback to majority biome
        maj = max(kinds, key=[nw, ne, sw, se].count)
        img.paste(PURE[maj], (x*TILE, y*TILE))

# ───────────────────────────────────────────────
# 6.  Save & report
# ───────────────────────────────────────────────
out = ASSETS / "wang_multi_biome.png"
img.save(out); img.show()
vals, cnts = np.unique(corners, return_counts=True)
print("Biome corner counts:", dict(zip(vals, map(int, cnts))), "→", out)
