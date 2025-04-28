# TODO: open bugs
# 1. River connections don't look good
# 2. Roads could fail to be drawn
# 3. Roads and rivers can cross each other
# 4. River could snap to edges of the map and it currently doesn't look good if both endpoints are on the edge
# 5. seed randomness yields very different results
# 6. Sometimes we get segfaults

"""
mapbuild.py – v3
================
* loads atlas.png + atlas.tsj (Tiled JSON tileset)
* renders seasonal trees from per-tile properties
* keeps rivers / roads path engine and biome generator
"""

import heapq, json, random, re
from pathlib import Path
import numpy as np
from PIL import Image
from noise import pnoise2

# ───────────────────────────────────────────────
# 0. GLOBALS
# ───────────────────────────────────────────────
TILE, GRID, SEED = 32, 128, 28
ASSETS           = Path("assets")
RNG              = random.Random(SEED)

# ── forest tuning knobs ───────────────────────
MIN_DIST    = 4      # Poisson disk radius in cells (>= 3)
NOISE_TH    = 0.25   # raise → fewer trees  (0.10 ~ sparse woods)
DENSITY_FREQ= 4.0    # lower → bigger clumps; doesn’t change total #

def perlin(nx,ny,f,b): return pnoise2(nx*f, ny*f, octaves=4, base=SEED+b)

# ───────────────────────────────────────────────
# 1.  LOAD atlas.tsj  +  atlas.png
# ───────────────────────────────────────────────
tsj = json.loads((ASSETS / "atlas.tsj").read_text())
ATLAS = Image.open(ASSETS / tsj["image"]).convert("RGBA")
COLS  = tsj["columns"]

# helper: crop any gid
def atlas_tile(gid):
    row, col = divmod(gid, COLS)
    x0, y0   = col*TILE, row*TILE
    return ATLAS.crop((x0, y0, x0+TILE, y0+TILE))

# map gid → flat property dict
META = {}
for t in tsj.get("tiles", []):
    props = {p["name"]: p["value"] for p in t.get("properties", [])}
    META[t["id"]] = props

# build TREES[variant][part] = PIL tile
TREES = {}
for gid, p in META.items():
    if p.get("category") != "tree": continue
    TREES.setdefault(p["variant"], {})[p["part"]] = atlas_tile(gid)
TREE_VARIANTS = list(TREES)  # whatever variants are present

# ───────────────────────────────────────────────
# 2.  GROUND BIOMES  (unchanged)
# ───────────────────────────────────────────────
BIOMES = {
    "water":  dict(rule=lambda nx,ny: perlin(nx,ny,1.2,101)<-0.10,
                   priority=0, patch_f=9, density=0.10, fallback="grass"),
    "desert": dict(rule=lambda nx,ny: perlin(nx,ny,1.0,202)>0.20,
                   priority=2, patch_f=7, density=0.15, fallback="darkgrass"),
    "darkgrass":dict(rule=lambda nx,ny: perlin(nx,ny,1.1,303)<-0.05,
                   priority=1, patch_f=7, density=0.18, fallback="grass"),
    "grass":  dict(rule=lambda nx,ny: True,
                   priority=3, patch_f=8, density=0.25, fallback="grass"),
}
PRIORITY={b:d["priority"] for b,d in BIOMES.items()}
PATCH_F ={b:d["patch_f"]  for b,d in BIOMES.items()}
DENSITY ={b:d["density"]  for b,d in BIOMES.items()}
FALLBACK={b:d["fallback"] for b,d in BIOMES.items()}

# ───────────────────────────────────────────────
# 2.b. Object rules
# ───────────────────────────────────────────────
# ── helper: weighted choice without external deps

# per-biome variant mix
TREE_VARIANT_WEIGHTS = {
    "grass":     {"light_green": 0.20, "green": 0.05, "yellow": 0.01},
    "darkgrass": {"green":  0.20, "light_green": 0.05, "yellow": 0.01},
    # water / desert won’t get trunks anyway
}

# helps with picking objects to place from a weighted list
def weighted_pick(weight_dict):
    total = sum(weight_dict.values())
    r = RNG.uniform(0, total)
    upto = 0
    for k, w in weight_dict.items():
        upto += w
        if r <= upto:
            return k
    return k  # fallback last key


def slice_sheet(p):
    img=Image.open(p).convert("RGBA")
    return [img.crop(((i%4)*TILE,(i//4)*TILE,
                      (i%4+1)*TILE,(i//4+1)*TILE)) for i in range(16)]
SHEETS,HI_LO={},{}
for png in ASSETS.glob("transition_*_*.png"):
    hi,lo=re.match(r"transition_(\w+)_(\w+)\.png", png.name).groups()
    SHEETS[(hi,lo)]=slice_sheet(png); HI_LO[(hi,lo)]=(hi,lo)

PURE,EXTRA={},{}
for (hi,lo),sheet in SHEETS.items():
    PURE.setdefault(hi,sheet[15]); PURE.setdefault(lo,sheet[0])
for b in PURE:
    strip=ASSETS/f"solid_{b}.png"
    if strip.is_file():
        img=Image.open(strip).convert("RGBA")
        EXTRA[b]=[img.crop((c*TILE,0,(c+1)*TILE,TILE))
                  for c in range(img.width//TILE)]
    else: EXTRA[b]=[]

# assign biome per corner
corners=np.empty((GRID+1,GRID+1),object)
for y in range(GRID+1):
    ny=y/GRID
    for x in range(GRID+1):
        nx=x/GRID
        for b in BIOMES:
            if BIOMES[b]["rule"](nx,ny): corners[y,x]=b; break

# repair illegal pairs
valid=set(SHEETS)|{tuple(reversed(p)) for p in SHEETS}
def repair():
    changed=0
    for y in range(GRID):
        for x in range(GRID):
            for dx,dy in ((1,0),(0,1)):
                a,b=corners[y,x],corners[y+dy,x+dx]
                if a!=b and (a,b) not in valid:
                    loser=a if PRIORITY[a]>PRIORITY[b] else b
                    corners[y+dy if loser==b else y,
                            x+dx if loser==b else x]=FALLBACK[loser]; changed+=1
    return changed
for _ in range(4):
    if repair()==0: break

# ───────────────────────────────────────────────
# 3.  FOREST placement (unchanged but uses META collision)
# ───────────────────────────────────────────────
tree_mask=np.zeros((GRID,GRID),bool)
def place_trees():
    """
    Blue-noise style placement:
      • eval every 2×2 candidate but random phase-shift per row pair
      • density driven by Perlin so clumps & clearings
      • Poisson disk: minDist = 3 cells
    """
    freq = 2.5
    for cyBlock in range(0, GRID, 4):          # process 4-row blocks
        phaseX = RNG.randint(0, 1)
        phaseY = RNG.randint(0, 1)
        for cy in range(cyBlock + phaseY, min(cyBlock+4, GRID-1), 2):
            for cx in range(phaseX, GRID-1, 2):
                # biome gate
                if any(corners[cy+dy, cx+dx] in ("water","desert")
                       for dy in (0,1) for dx in (0,1)):
                    continue

                # Poisson radius
                if tree_mask[max(0,cy-MIN_DIST):cy+MIN_DIST+1,
                             max(0,cx-MIN_DIST):cx+MIN_DIST+1].any():
                    continue

                # density mask
                if perlin(cx/GRID, cy/GRID, DENSITY_FREQ, 909) < NOISE_TH:
                    continue
                tree_mask[cy, cx] = True

place_trees()

# collision bitmap from per-tile property
collision=np.zeros((GRID,GRID),bool)

# ───────────────────────────────────────────────
# 4. PATH ENGINE (same as the "fixed" version)
#     -- omitted for brevity, keep your latest working block here --
# ───────────────────────────────────────────────
# ...  (keep carve()/a_star()/overlay code)

# ───────────────────────────────────────────────
# 5.  RENDER
# ───────────────────────────────────────────────
img=Image.new("RGBA",(GRID*TILE,GRID*TILE))

def decor(b,x,y):
    ex=EXTRA[b]
    if not ex: return PURE[b]
    if perlin(x/GRID,y/GRID,PATCH_F[b],hash(b)&0xFFFF)<0 or RNG.random()>DENSITY[b]:
        return PURE[b]
    h=(x*0x45d9f3b+y*0x2c1b3c6+hash(b))&0xFFFFFFFF
    return ex[h%len(ex)]
def sheet_for(a,b): return SHEETS.get((a,b)) or SHEETS.get((b,a))

# ground first
for y in range(GRID):
    for x in range(GRID):
        nw,ne,sw,se = corners[y,x],corners[y,x+1],corners[y+1,x],corners[y+1,x+1]
        kinds={nw,ne,sw,se}
        if len(kinds)==1:
            img.paste(decor(nw,x,y),(x*TILE,y*TILE)); continue
        if len(kinds)==2:
            a,b=kinds; s=sheet_for(a,b)
            if s:
                hi,_=HI_LO.get((a,b)) or HI_LO.get((b,a))
                bit=lambda c:1 if c==hi else 0
                idx=(bit(ne)<<0)|(bit(se)<<1)|(bit(sw)<<2)|(bit(nw)<<3)
                img.paste(s[idx],(x*TILE,y*TILE)); continue
        maj=max(kinds,key=[nw,ne,sw,se].count)
        img.paste(PURE[maj],(x*TILE,y*TILE))

# paste forests
for cy,cx in zip(*np.where(tree_mask)):
    major = max({corners[cy,cx], corners[cy,cx+1],
                corners[cy+1,cx], corners[cy+1,cx+1]},
                key=[corners[cy,cx], corners[cy,cx+1],
                    corners[cy+1,cx], corners[cy+1,cx+1]].count)
    weights = TREE_VARIANT_WEIGHTS.get(major, {"light_green":1})
    variant = weighted_pick(weights)
    parts   = TREES[variant]
    mapping=[("tl",cx,cy),("tr",cx+1,cy),("bl",cx,cy+1),("br",cx+1,cy+1)]
    for part,tx,ty in mapping:
        tile=parts[part]
        img.paste(tile,(tx*TILE,ty*TILE),mask=tile)
        # collision flag if that gid has collision=true
        gid = next( g for g,p in META.items()
                    if p.get("variant")==variant and p.get("part")==part )
        if META[gid].get("collision"):
            collision[ty,tx]=True

# ---- overlay pass  (insert your latest river/road render loop here) ----
# img becomes final composite

out=ASSETS/"wang_world_phase1.png"
img.save(out); img.show()
print("map saved →", out)

