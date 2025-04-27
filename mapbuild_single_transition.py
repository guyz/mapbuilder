import numpy as np
from PIL import Image
import random
import os

# Set up constants
TILE_SIZE = 32
GRID_SIZE = 20
OUTPUT_SIZE = GRID_SIZE * TILE_SIZE
ASSETS_DIR = "assets"

# Load the tileset
tileset = Image.open(os.path.join(ASSETS_DIR, "transition_desert_water.png"))

# Generate a random grid of corner values (0 or 1)
# We need a grid of size (GRID_SIZE+1) x (GRID_SIZE+1) to represent corners
# add deterministic seed
np.random.seed(42)
corners = np.random.randint(0, 2, size=(GRID_SIZE+1, GRID_SIZE+1))

# Create the output image
output_image = Image.new("RGB", (OUTPUT_SIZE, OUTPUT_SIZE))

# For each position in the grid
for y in range(GRID_SIZE):
    for x in range(GRID_SIZE):
        # Calculate the tile index based on the 4 corners
        # NE=1, SE=2, SW=4, NW=8
        tile_index = 0
        if corners[y, x]:       # NW corner
            tile_index += 8
        if corners[y, x+1]:     # NE corner
            tile_index += 1
        if corners[y+1, x]:     # SW corner
            tile_index += 4
        if corners[y+1, x+1]:   # SE corner
            tile_index += 2
        
        # Calculate the position in the tileset
        # The tileset is a 4x4 grid of tiles
        tileset_x = (tile_index % 4) * TILE_SIZE
        tileset_y = (tile_index // 4) * TILE_SIZE
        
        # Extract the tile from the tileset
        tile = tileset.crop((tileset_x, tileset_y, 
                             tileset_x + TILE_SIZE, 
                             tileset_y + TILE_SIZE))
        
        # Place the tile in the output image
        output_image.paste(tile, (x * TILE_SIZE, y * TILE_SIZE))

# Display the result
output_image.show()

# Save the result
output_image.save(os.path.join(ASSETS_DIR, "wang_terrain_map.png"))
