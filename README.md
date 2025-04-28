# Map Builder

A procedural terrain generator using Wang tiles to create seamless terrain transitions between different biomes.

## Overview

`mapbuild.py` generates random terrain maps using the Wang tiles (corner matching) algorithm. It creates a consistent terrain with smooth transitions between biomes like desert, grass, and water.

The algorithm places tiles in a grid, ensuring that the corners of adjacent tiles always match, creating a continuous, natural-looking landscape.

## How It Works

### The Wang Tile Algorithm

This implementation uses 2-corner Wang tiles with a 4-bit encoding system:
- Each tile has 4 corners, with each corner representing either a higher terrain (1) or lower terrain (0)
- Corners are encoded using a binary system: NE=1, SE=2, SW=4, NW=8
- This creates 16 possible corner combinations (tiles), indexed from 0-15

For example:
- Tile 0: All corners are lower terrain (0000)
- Tile 15: All corners are higher terrain (1111)
- Tile 9: NW and NE corners are higher terrain (1001)

The algorithm:
1. Generates a grid of random corner values
2. For each cell in the output grid, calculates which tile to use based on its 4 corners
3. Places the appropriate tile from the tileset
4. Ensures adjacent tiles always share matching corner values

### Why It Works

The key insight is that we're not deciding which tile to use at each position; we're deciding what the value of each corner should be. This approach guarantees that transitions are smooth because:

1. Each corner value is shared by 4 adjacent tiles
2. The tile selection is deterministic based on corner values
3. Adjacent tiles must use tiles that match at their shared corners

This creates a mathematically guaranteed seamless terrain map without any inconsistencies.

## Creating a Tileset

Each transition tileset (like `transition_desert_water.png`) should be:
- A 4×4 grid of tiles (128×128 pixels total, with each tile being 32×32 pixels)
- Organized in row-major order with indices 0-15
- Include all 16 possible corner combinations

To create `transition_desert_water.png`:

1. Create a new 128×128 pixel image
2. Divide it into a 4×4 grid of 32×32 pixel tiles
3. Following the binary encoding pattern:
   - Tile 0 (position 0,0): Pure water (all corners = 0)
   - Tile 15 (position 3,3): Pure desert (all corners = 1)
   - Other tiles: Appropriate transitions between water and desert

Layout pattern (numbers = tile index):
```
 0  1  2  3
 4  5  6  7
 8  9 10 11
12 13 14 15
```

## Usage

```
python mapbuild.py
```

This will generate a random terrain map, display it on screen, and save it to `assets/wang_terrain_map.png`.

## Adding New Biomes

To add transitions between new biome types:
1. Create a new tileset image following the format above
2. Name it according to the convention: `transition_biome1_biome2.png`
3. Update the code to use the new tileset for the appropriate regions 

## Building Assets

### Building the Object Atlas

The object atlas is a single image containing all tiles for in-game objects (e.g., trees, rocks, chests, etc).
**TODO:** In the future, merge all other asset files into this single atlas for easier management.

#### How to Build/Extend the Atlas

1. **Draw all object art in a single 32x32 tilemap using Tiled map editor.**  
   - Place each object in its own 32x32 cell.
   - Save your map as `atlas.tmx` for future editing/reference.

2. **Export the result as `atlas.png` and put it in `assets/`.**  
   - This PNG is the pixel source file used by the game.

3. **In Tiled, create a new Tileset:**  
   - Go to `New -> New Tileset`.
   - Import `atlas.png` as the image source.

4. **Add any metadata logic you want to the different tiles and export as a `.tsj` file:**  
   - You can add custom properties, collision info, or tags to each tile.
   - Export the tileset as `atlas.tsj` (Tiled's JSON format).

5. **Map builder code then loads `atlas.png` and `atlas.tsj` and uses that.**  
   - The code can read the atlas image and metadata to place and interpret objects in the world.

This workflow makes it easy to add, update, or extend in-game objects and their properties in a single place. 