import rasterio

with rasterio.open("../data/sentinel2_l2a.tif") as src:
    print("sentinel2_l2a.tif")
    print(src.crs)          # Coordinate reference system
    print(src.bounds)       # Map extent
    print(src.res)           # Pixel size in map units (metres here)
    print(src.count)         # Number of bands
    blue = src.read(1)       # 2D NumPy array: B02
    scl = src.read(7)        # 2D array: scene classification
    valid = src.read(8) == 1 # Boolean mask
    print(blue, scl, valid)

with rasterio.open("../data/copernicus_dem_glo30.tif") as src2:
    print("copernicus_dem_glo30.tif")
    print(src2.crs)
    print(src2.bounds)
    print(src2.res)
    print(src2.count)
    print(src2.read(1),src2.read(2))