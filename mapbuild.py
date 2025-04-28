# TODO: open bugs
# 1. River connections don't look good
# 2. Roads could fail to be drawn
# 3. Roads and rivers can cross each other
# 4. River could snap to edges of the map and it currently doesn't look good if both endpoints are on the edge

"""
mapbuild.py – ground + overlay paths (river/road)  v2
=============================================================
Only the PATH ENGINE block changed:
  * rivers snap their endpoints to water/edge
  * idempotent carving (no double-draw)
"""

import heapq, random, re
from pathlib import Path
import numpy as np
from PIL import Image
from noise import pnoise2
# ───────────────────────────────────────────────
# 0. Global knobs
# ───────────────────────────────────────────────
# SEED = 24 is good.
TILE, GRID, SEED = 32, 128, 28
ASSETS           = Path("assets")
RNG              = random.Random(SEED)
def perlin(nx, ny, f, b): return pnoise2(nx*f, ny*f, octaves=4, base=SEED+b)

# ───────────────────────────────────────────────
# 1.  BIOME catalogue (unchanged)
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
# 2.  PATHS
# ───────────────────────────────────────────────
PATHS=[
    dict(kind="river", start=(20,10), end=(110,100), wiggle=0.35),
    dict(kind="road",  start=(5,120), end=(120,60), wiggle=0.15),
]

OVERLAY={
    "road": dict(sheet="overlay_road.png",
                 move_cost=dict(grass=1, desert=2, darkgrass=1, water=99)),
    "river":dict(sheet="overlay_river.png",
                 move_cost=dict(grass=3, desert=4, darkgrass=2, water=1)),
}

# ───────────────────────────────────────────────
# helper – slice a 4×4 sheet
# ───────────────────────────────────────────────
def slice_sheet(path):
    img=Image.open(path).convert("RGBA")
    return [img.crop(((i%4)*TILE,(i//4)*TILE,
                      (i%4+1)*TILE,(i//4+1)*TILE)) for i in range(16)]

# ───────────────────────────────────────────────
# 3. Load ground transition sheets (unchanged)
# ───────────────────────────────────────────────
trans_pat=re.compile(r"transition_(\w+)_(\w+)\.png")
SHEETS,HI_LO={},{}
for png in ASSETS.glob("transition_*_*.png"):
    hi,lo=trans_pat.match(png.name).groups()
    SHEETS[(hi,lo)]=slice_sheet(png); HI_LO[(hi,lo)]=(hi,lo)

PURE,EXTRA={},{}
for (hi,lo),sheet in SHEETS.items():
    PURE.setdefault(hi,sheet[15]); PURE.setdefault(lo,sheet[0])
for b in PURE:
    strip=ASSETS/f"solid_{b}.png"; frames=[]
    if strip.is_file():
        img=Image.open(strip).convert("RGBA")
        frames=[img.crop((c*TILE,0,(c+1)*TILE,TILE))
                for c in range(img.width//TILE)]
    EXTRA[b]=frames

# ───────────────────────────────────────────────
# 4. Assign ground biomes  (unchanged)
# ───────────────────────────────────────────────
corners=np.empty((GRID+1,GRID+1),object)
for y in range(GRID+1):
    ny=y/GRID
    for x in range(GRID+1):
        nx=x/GRID
        for b in BIOMES:
            if BIOMES[b]["rule"](nx,ny): corners[y,x]=b; break

valid_pairs=set(SHEETS)|{tuple(reversed(p)) for p in SHEETS}
def repair():
    ch=0
    for y in range(GRID):
        for x in range(GRID):
            for dx,dy in ((1,0),(0,1)):
                a,b=corners[y,x],corners[y+dy,x+dx]
                if a!=b and (a,b)not in valid_pairs:
                    loser=a if PRIORITY[a]>PRIORITY[b] else b
                    corners[y+dy if loser==b else y,
                            x+dx if loser==b else x]=FALLBACK[loser]; ch+=1
    return ch
for _ in range(4):
    if repair()==0: break

# ───────────────────────────────────────────────
# ###  PATH ENGINE  (replace previous block)
# ───────────────────────────────────────────────
# helper placed near the render loop
def water_count(x, y):
    """number of water ground corners in this 2×2 cell"""
    return sum(corners[y + dy, x + dx] == "water"
               for dy in (0, 1) for dx in (0, 1))


overlay_mask={k:np.zeros_like(corners,dtype=np.uint8) for k in OVERLAY}

def on_edge(c): x,y=c; return x in (0,GRID-1) or y in (0,GRID-1)
def nearest_anchor(cell):
    """closest cell that is water OR on map edge"""
    q=[cell]; seen={cell}
    while q:
        x,y=q.pop(0)
        if corners[y,x]=="water" or on_edge((x,y)): return (x,y)
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny=x+dx,y+dy
            if 0<=nx<GRID and 0<=ny<GRID and (nx,ny) not in seen:
                seen.add((nx,ny)); q.append((nx,ny))
    return cell

def a_star(start,end,cost,wiggle):
    sx,sy=start; ex,ey=end
    h=lambda X,Y: abs(X-ex)+abs(Y-ey)
    openq=[(0,sx,sy)]; g={(sx,sy):0}; parent={}
    while openq:
        f,x,y=heapq.heappop(openq)
        if (x,y)==(ex,ey):
            path=[(x,y)]
            while (x,y)!=(sx,sy):
                x,y=parent[(x,y)]; path.append((x,y))
            return path[::-1]
        for dx,dy in ((1,0),(-1,0),(0,1),(0,-1)):
            nx,ny=x+dx,y+dy
            if not(0<=nx<GRID and 0<=ny<GRID): continue
            w=cost[corners[ny,nx]]
            if w>=99: continue
            ng=g[(x,y)]+w+wiggle*RNG.uniform(-0.3,0.3)
            if (nx,ny) not in g or ng<g[(nx,ny)]:
                g[(nx,ny)]=ng; parent[(nx,ny)]=(x,y)
                heapq.heappush(openq,(ng+h(nx,ny),nx,ny))
    return []

def carve(kind,start,end,wiggle):
    if kind=="river":
        start,end=nearest_anchor(start),nearest_anchor(end)
    cost=OVERLAY[kind]["move_cost"]
    for cx,cy in a_star(start,end,cost,wiggle):
        # mark corners; |= keeps previous river bits intact
        overlay_mask[kind][cy,  cx  ]|=1
        overlay_mask[kind][cy,  cx+1]|=1
        overlay_mask[kind][cy+1,cx  ]|=1
        overlay_mask[kind][cy+1,cx+1]|=1

for p in PATHS:
    carve(p["kind"], p["start"], p["end"], p.get("wiggle",0.2))

OVERLAY_SHEETS={k:slice_sheet(ASSETS/v["sheet"]) for k,v in OVERLAY.items()}

# priority: river first, road second, others later
OVERLAY_DRAW_ORDER=["river","road"]+[
    k for k in OVERLAY if k not in ("river","road")
]

# ───────────────────────────────────────────────
# 5. RENDER   (replace previous render block)
# ───────────────────────────────────────────────
base=Image.new("RGBA",(GRID*TILE,GRID*TILE))

def decor(b,x,y):
    ex=EXTRA[b]
    if not ex: return PURE[b]
    n=perlin(x/GRID,y/GRID,PATCH_F[b],hash(b)&0xFFFF)
    if n<0 or RNG.random()>DENSITY[b]: return PURE[b]
    h=(x*0x45d9f3b+y*0x2c1b3c6+hash(b))&0xFFFFFFFF
    return ex[h%len(ex)]

def sheet_for(a,b): return SHEETS.get((a,b)) or SHEETS.get((b,a))

# ---- ground
for y in range(GRID):
    for x in range(GRID):
        nw,ne,sw,se = corners[y,x],corners[y,x+1],corners[y+1,x],corners[y+1,x+1]
        kinds={nw,ne,sw,se}
        if len(kinds)==1:
            base.paste(decor(nw,x,y),(x*TILE,y*TILE))
            continue
        if len(kinds)==2:
            a,b=kinds; s=sheet_for(a,b)
            if s:
                hi,_=HI_LO.get((a,b)) or HI_LO.get((b,a))
                bit=lambda c:1 if c==hi else 0
                code=(bit(ne)<<0)|(bit(se)<<1)|(bit(sw)<<2)|(bit(nw)<<3)
                base.paste(s[code],(x*TILE,y*TILE))
                continue
        maj=max(kinds,key=[nw,ne,sw,se].count)
        base.paste(PURE[maj],(x*TILE,y*TILE))

# ---- overlays with precedence & water-skip for river
final=base.copy()
written=np.zeros((GRID,GRID),dtype=bool)  # cell mask

for kind in OVERLAY_DRAW_ORDER:
    sheet=OVERLAY_SHEETS[kind]
    mask =overlay_mask[kind]
    for y in range(GRID):
        for x in range(GRID):
            if written[y,x]: continue                 # already covered by higher layer
            code=(mask[y,x+1]<<0)|(mask[y+1,x+1]<<1)|(mask[y+1,x]<<2)|(mask[y,x]<<3)
            if code==0: continue
            if kind == "river":
                # don't draw if the river tile would jut out onto open water
                if water_count(x, y) >= 2:        # ≥ half corners already water
                    continue
            final.paste(sheet[code],(x*TILE,y*TILE),sheet[code])
            written[y,x]=True

# 6. save/show as before
out=ASSETS/"wang_world_paths.png"
final.save(out); final.show()
print("saved →",out)
