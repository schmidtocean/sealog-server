#!/usr/bin/env python3
'''
FILE:           filecrop_utility.py

DESCRIPTION:    This class handles culling subsets of data from files based on
                start/stop times.

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    1.0
CREATED:    2021-04-21
REVISION:   2023-07-21

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2023
'''

import os
import logging
from datetime import datetime

class FileCropUtility():
    '''
    This class handles culling subsets of data from files based on start/stop
    times.
    '''

    def __init__(self, start_dt=datetime(1970, 1, 1, 0, 0, 0, tzinfo=None), stop_dt=datetime.utcnow(), delimiter=',', dt_format='%Y-%m-%dT%H:%M:%S.%fZ', header=False):
        self.start_dt = start_dt
        self.stop_dt = stop_dt
        self.delimiter = delimiter
        self.dt_format = dt_format
        self.header = header
        self._header_str = None


    @property
    def header_str(self):
        return self._header_str
    

    def cull_files(self, data_files):
        '''
        Peek at the first/last entries in the file(s) and return only the files
        that contain data between the start/stop timestamps.
        '''

        if not isinstance(data_files, list):
            data_files = [data_files]

        logging.info("Culling file list")
        culled_files = []

        for data_file in data_files:
            logging.debug("File: %s", data_file)
            with open( data_file, 'rb' ) as file :

                if self.header:
                    self._header_str = file.readline().decode()
                    self._header_str = self._header_str or header_str

                first_line = file.readline().decode().rstrip('\n')
                try:
                    first_ts = datetime.strptime(first_line.split(self.delimiter)[0],self.dt_format)

                except Exception as err:
                    logging.warning("Could not process first line in %s: %s", data_file, first_line)
                    logging.debug(str(err))
                    continue

                logging.debug("    First line: %s", first_line)
                logging.debug("    First timestamp: %s", first_ts)

                file.seek(-2, os.SEEK_END)
                while file.read(1) != b'\n':
                    file.seek(-2, os.SEEK_CUR)

                last_line = file.readline().decode().rstrip('\n')
                logging.warn(f'lastline: {last_line}')
                # Hack to deal with extra newline characters in data files.
                if last_line == '':
                    file.seek(-4, os.SEEK_CUR)
                    while file.read(1) != b'\n':
                        file.seek(-2, os.SEEK_CUR)

                    last_line = file.readline().decode().rstrip('\n')
                
                    logging.warn(f'lastline hack: {last_line}')
                # End of hack

                try:
                    last_ts = datetime.strptime(last_line.split(self.delimiter)[0],self.dt_format)
                except Exception as err:
                    logging.warning("Could not process last line in %s: %s", data_file, last_line)
                    logging.debug(str(err))
                    continue

                logging.debug("    Last line: %s", last_line)
                logging.debug("    Last timestamp: %s", last_ts)

            if not ((self.start_dt - last_ts).total_seconds() > 0 or (first_ts - self.stop_dt).total_seconds() > 0):
                logging.debug("    ** Include this file **")
                culled_files.append(data_file)

        logging.debug("Culled file list: \n\t%s", '\n\t'.join(culled_files))
        return culled_files

    def crop_file_data(self, data_files):
        '''
        Read the file(s) and return on the data from between the start/stop
        timestamps.
        '''

        header_sent = not self.header

        logging.info("Cropping file data")

        if not isinstance(data_files, list):
            data_files = [data_files]

        while True:

            # send header
            if not header_sent:
                header_sent = True
                yield self._header_str

            for idx, data_file in enumerate(data_files):
                logging.debug("File: %s", data_file)

                with open( data_file, 'r' ) as file:

                    if self.header:
                        _ = file.readline()

                    while True:
                        line_str = file.readline()

                        if not line_str:
                            break

                        if line_str.rstrip('\n').rstrip('\r') == '':
                            continue

                        try:
                            line_ts = datetime.strptime(line_str.split(self.delimiter)[0],self.dt_format)

                        except Exception as err:
                            logging.warning("Could not process line: %s", line_str)
                            logging.debug(str(err))

                        else:

                            if (line_ts - self.start_dt).total_seconds() >= 0 and (self.stop_dt - line_ts).total_seconds() >= 0:
                                yield line_str

            break
