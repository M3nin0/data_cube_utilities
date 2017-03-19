# Copyright 2016 United States Government as represented by the Administrator
# of the National Aeronautics and Space Administration. All Rights Reserved.
#
# Portion of this code is Copyright Geoscience Australia, Licensed under the
# Apache License, Version 2.0 (the "License"); you may not use this file
# except in compliance with the License. You may obtain a copy of the License
# at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# The CEOS 2 platform is licensed under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
# http://www.apache.org/licenses/LICENSE-2.0.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

# datacube imports.
import datacube
from datacube.api import GridWorkflow
import xarray as xr
import numpy as np

# Author: AHDS
# Creation date: 2016-06-23
# Modified by:
# Last modified date: 2016-08-05


class DataAccessApi:
    """
    Class that provides wrapper functionality for the DataCube.
    """

    # defaults for all the required fields.
    product_default = 'ls7_ledaps'
    platform_default = 'LANDSAT_7'

    def __init__(self, config='/home/localuser/Datacube/data_cube_ui/config/.datacube.conf'):
        self.dc = datacube.Datacube(config=config)

    """
    query params are defined in datacube.api.query
    """

    def get_dataset_by_extent(self,
                              product,
                              product_type=None,
                              platform=None,
                              time=None,
                              longitude=None,
                              latitude=None,
                              measurements=None,
                              output_crs=None,
                              resolution=None,
                              crs=None,
                              dask_chunks=None):
        """
        Gets and returns data based on lat/long bounding box inputs.
        All params are optional. Leaving one out will just query the dc without it, (eg leaving out
        lat/lng but giving product returns dataset containing entire product.)

        Args:
            product (string): The name of the product associated with the desired dataset.
            product_type (string): The type of product associated with the desired dataset.
            platform (string): The platform associated with the desired dataset.
            time (tuple): A tuple consisting of the start time and end time for the dataset.
            longitude (tuple): A tuple of floats specifying the min,max longitude bounds.
            latitude (tuple): A tuple of floats specifying the min,max latitutde bounds.
            crs (string): CRS lat/lon bounds are specified in, defaults to WGS84.
            measurements (list): A list of strings that represents all measurements.
            output_crs (string): Determines reprojection of the data before its returned
            resolution (tuple): A tuple of min,max ints to determine the resolution of the data.
            dask_chunks (dict): Lazy loaded array block sizes, not lazy loaded by default.

        Returns:
            data (xarray): dataset with the desired data.
        """

        # there is probably a better way to do this but I'm not aware of it.
        query = {}
        if product_type is not None:
            query['product_type'] = product_type
        if platform is not None:
            query['platform'] = platform
        if time is not None:
            query['time'] = time
        if longitude is not None and latitude is not None:
            query['longitude'] = longitude
            query['latitude'] = latitude
        if crs is not None:
            query['crs'] = crs

        data = self.dc.load(
            product=product,
            measurements=measurements,
            output_crs=output_crs,
            resolution=resolution,
            dask_chunks=dask_chunks,
            **query)
        return data

    def get_stacked_datasets_by_extent(self,
                                       products,
                                       product_type=None,
                                       platforms=None,
                                       time=None,
                                       longitude=None,
                                       latitude=None,
                                       measurements=None,
                                       output_crs=None,
                                       resolution=None,
                                       dask_chunks=None):
        """
          Gets and returns data based on lat/long bounding box inputs.
          All params are optional. Leaving one out will just query the dc without it, (eg leaving out
          lat/lng but giving product returns dataset containing entire product.)

          Args:
              products (array of strings): The names of the product associated with the desired dataset.
              product_type (string): The type of product associated with the desired dataset.
              platforms (array of strings): The platforms associated with the desired dataset.
              time (tuple): A tuple consisting of the start time and end time for the dataset.
              longitude (tuple): A tuple of floats specifying the min,max longitude bounds.
              latitude (tuple): A tuple of floats specifying the min,max latitutde bounds.
              measurements (list): A list of strings that represents all measurements.
              output_crs (string): Determines reprojection of the data before its returned
              resolution (tuple): A tuple of min,max ints to determine the resolution of the data.

          Returns:
              data (xarray): dataset with the desired data.
          """

        data_array = []

        for index, product in enumerate(products):
            product_data = self.get_dataset_by_extent(
                product,
                product_type=product_type,
                platform=platforms[index],
                time=time,
                longitude=longitude,
                latitude=latitude,
                measurements=measurements,
                output_crs=output_crs,
                resolution=resolution,
                dask_chunks=dask_chunks)
            if 'time' in product_data:
                product_data['satellite'] = xr.DataArray(
                    np.full(product_data[list(product_data.data_vars)[0]].values.shape, index, dtype="int16"),
                    dims=('time', 'latitude', 'longitude'))
                data_array.append(product_data.copy(deep=True))

        data = None
        if len(data_array) > 0:
            combined_data = xr.concat(data_array, 'time')
            data = combined_data.reindex({'time': sorted(combined_data.time.values)})

        return data

    def get_dataset_tiles(self,
                          product,
                          product_type=None,
                          platform=None,
                          time=None,
                          longitude=None,
                          latitude=None,
                          measurements=None,
                          output_crs=None,
                          resolution=None):
        """
        Gets and returns data based on lat/long bounding box inputs.
        All params are optional. Leaving one out will just query the dc without it, (eg leaving out
        lat/lng but giving product returns dataset containing entire product.)

        Args:
            product (string): The name of the product associated with the desired dataset.
            product_type (string): The type of product associated with the desired dataset.
            platform (string): The platform associated with the desired dataset.
            time (tuple): A tuple consisting of the start time and end time for the dataset.
            longitude (tuple): A tuple of floats specifying the min,max longitude bounds.
            latitude (tuple): A tuple of floats specifying the min,max latitutde bounds.
            measurements (list): A list of strings that represents all measurements.
            output_crs (string): Determines reprojection of the data before its returned
            resolution (tuple): A tuple of min,max ints to determine the resolution of the data.

        Returns:
            data (xarray): dataset with the desired data in tiled sections.
        """

        # there is probably a better way to do this but I'm not aware of it.
        query = {}
        if product_type is not None:
            query['product_type'] = product_type
        if platform is not None:
            query['platform'] = platform
        if time is not None:
            query['time'] = time
        if longitude is not None and latitude is not None:
            query['longitude'] = longitude
            query['latitude'] = latitude

        # set up the grid workflow
        gw = GridWorkflow(self.dc.index, product=product)

        # dict of tiles.
        request_tiles = gw.list_cells(
            product=product, measurements=measurements, output_crs=output_crs, resolution=resolution, **query)
        """
        tile_def = defaultdict(dict)
        for cell, tiles in request_tiles.items():
            for time, tile in tiles.items():
                tile_def[cell, time]['request'] = tile

        keys = list(tile_def)

        data_tiles = {}
        for key in keys:
            tile = tile_def[key]['request']
            data_tiles[key[0]] = gw.load(key[0], tile)
        """
        # cells now return stacked xarrays of data.
        data_tiles = {}
        for tile_key in request_tiles:
            tile = request_tiles[tile_key]
            data_tiles[tile_key] = gw.load(tile, measurements=measurements)

        return data_tiles

    def get_scene_metadata(self, platform, product, longitude=None, latitude=None, crs=None, time=None):
        """
        Gets a descriptor based on a request.

        Args:
            platform (string): Platform for which data is requested
            product (string): The name of the product associated with the desired dataset.
            longitude (tuple): Tuple of min,max floats for longitude
            latitude (tuple): Tuple of min,max floats for latitutde
            crs (string): Describes the coordinate system of params lat and long
            time (tuple): Tuple of start and end datetimes for requested data

        Returns:
            scene_metadata (dict): Dictionary containing a variety of data that can later be
                                   accessed.
        """

        dataset = self.get_dataset_by_extent(
            platform=platform,
            product=product,
            longitude=longitude,
            latitude=latitude,
            crs=crs,
            time=time,
            dask_chunks={})

        if not dataset:
            return {
                'lat_extents': (0, 0),
                'lon_extents': (0, 0),
                'time_extents': (0, 0),
                'scene_count': 0,
                'pixel_count': 0,
                'tile_count': 0,
                'storage_units': {}
            }

        lon_min, lat_min, lon_max, lat_max = dataset.geobox.extent.envelope
        return {
            'lat_extents': (lat_min, lat_max),
            'lon_extents': (lon_min, lon_max),
            'time_extents': (dataset.time[0].values.astype('M8[ms]').tolist(),
                             dataset.time[-1].values.astype('M8[ms]').tolist()),
            'scene_count':
            dataset.time.size,
            'pixel_count':
            dataset.geobox.shape[0] * dataset.geobox.shape[1],
        }

    def list_acquisition_dates(self, platform, product, longitude=None, latitude=None, crs=None, time=None):
        """
        Get a list of all acquisition dates for a query.

        Args:
            platform (string): Platform for which data is requested
            product (string): The name of the product associated with the desired dataset.
            longitude (tuple): Tuple of min,max floats for longitude
            latitude (tuple): Tuple of min,max floats for latitutde
            crs (string): Describes the coordinate system of params lat and long
            time (tuple): Tuple of start and end datetimes for requested data

        Returns:
            times (list): Python list of dates that can be used to query the dc for single time
                          sliced data.
        """
        dataset = self.get_dataset_by_extent(
            platform=platform,
            product=product,
            longitude=longitude,
            latitude=latitude,
            crs=crs,
            time=time,
            dask_chunks={})

        if not dataset:
            return []

        return dataset.time.values.astype('M8[ms]').tolist()

    def get_datacube_metadata(self, platform, product):
        """
        Gets some details on the cube and its contents.

        Args:
            platform (string): Desired platform for requested data.
            product (string): Desired product for requested data.

        Returns:
            datacube_metadata (dict): a dict with multiple keys containing relevant metadata.
        """

        return self.get_scene_metadata(platform, product)
