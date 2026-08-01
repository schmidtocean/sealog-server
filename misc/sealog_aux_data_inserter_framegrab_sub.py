#!/usr/bin/env python3
'''
FILE:           sealog_aux_data_inserter_framegrab.py

DESCRIPTION:    This service listens for new events submitted to Sealog, copies
                frame grab file(s) from a source dir, renames/copies the file
                to the sealog-files/images directory and creates an aux_data
                record containing the specified real-time data and associates
                the aux data record with the newly created event.  However if
                the realtime data is older than 20 seconds this service will
                consider the data stale and will not associate it with the
                newly created event.

                The sources are configured via the DEFAULT_SOURCES_CONFIG inline
                YAML block below. Pass --sources_file/-f to load the sources
                configuration from an external YAML file instead.

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    1.1
CREATED:    2020-01-27
REVISION:   2026-08-01

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
'''

import os
import sys
import asyncio
import json
import time
import shutil
import logging
from datetime import datetime, timedelta, timezone
from os.path import dirname, realpath

import yaml
import requests
import websockets

sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.settings import WS_SERVER_URL, HEADERS
from misc.python_sealog.event_aux_data import create_event_aux_data


# The data_source to use for the auxData records
AUX_DATA_DATASOURCE = 'vehicleRealtimeFramegrabberData'

# set of events to ignore
EXCLUDE_SET = ()

# needs to be unique for all currently active dataInserter scripts.
CLIENT_WSID = f'aux_data_inserter_{AUX_DATA_DATASOURCE}'

THRESHOLD = 20  # seconds

# ------------ only needed for scp transfers -------------
# user = 'survey'
# host = '192.168.1.42'
# port = 22
# key_file = '/home/sealog/.ssh/id_rsa'
# my_key = RSAKey.from_private_key_file(key_file)
# t = Transport(host, port)

SOURCE_DIR = '/mnt/ramdisk'
DEST_DIR = '/data/sealog-Sub-files/images'

# Allowed image formats for frame grab captures.
DEFAULT_FILENAME_SUFFIX = '.jpg'
ALLOWED_FILENAME_SUFFIXES = ('.png', '.jpg', '.bmp')

# Default sources configuration, used unless an external sources file is
# specified via the --sources_file/-f command-line option.
# filename_prefix is optional and defaults to source_name when omitted.
# filename_suffix is optional and defaults to .jpg when omitted; when set
# it must end with one of ALLOWED_FILENAME_SUFFIXES.
DEFAULT_SOURCES_CONFIG = '''
sources:
  - source_name: SCICAM
    source_url: http://10.23.46.60/images/
    source_filename: scicam.jpg

  - source_name: SITCAM
    source_url: http://10.23.46.61/images/
    source_filename: sitcam.jpg

  # Additional cameras, uncomment and adjust as needed:
  # - source_name: HDQUAD
  #   source_url: http://10.23.46.62/images/
  #   source_filename: hdquad.jpg
  #
  # - source_name: SDQUAD
  #   source_url: http://10.23.46.63/images/
  #   source_filename: sdquad.jpg
  #
  # - source_name: SCITOO
  #   source_url: http://10.23.46.64/images/
  #   source_filename: scitoo.jpg
  #
  # - source_name: SITTOO
  #   source_url: http://10.23.46.65/images/
  #   source_filename: sittoo.jpg
'''

HELLO = {
    'type': 'hello',
    'id': CLIENT_WSID,
    'auth': {
        'headers': HEADERS
    },
    'version': '2',
    'subs': ['/ws/status/newEvents']
}

PING = {
    'type': 'ping',
    'id': CLIENT_WSID
}


async def aux_data_inserter(sources):  # pylint:disable=redefined-outer-name
    '''
    Connect to the websocket feed for new events.  When new events arrive,
    build aux_data records and submit them to the sealog-server.
    '''

    logging.debug("Connecting to event websocket feed...")
    try:
        async with websockets.connect(WS_SERVER_URL) as websocket:

            await websocket.send(json.dumps(HELLO))

            while True:

                event = await websocket.recv()
                event_obj = json.loads(event)

                if event_obj['type'] and event_obj['type'] == 'ping':
                    await websocket.send(json.dumps(PING))

                elif event_obj['type'] and event_obj['type'] == 'pub':

                    if event_obj['message']['event_value'] in EXCLUDE_SET:
                        logging.debug("Skipping because event value is in the exclude set")
                        continue

                    if datetime.strptime(
                            event_obj['message']['ts'],
                            '%Y-%m-%dT%H:%M:%S.%fZ') < datetime.now(timezone.utc).replace(
                            tzinfo=None) - timedelta(seconds=THRESHOLD):
                        logging.debug("Skipping because event ts is older than thresold")
                        continue

                    aux_data_record = {
                        'event_id': event_obj['message']['id'],
                        'data_source': AUX_DATA_DATASOURCE,
                        'data_array': []
                    }

                    for source in sources:

                        event_ts = datetime.strptime(
                            event_obj['message']['ts'], '%Y-%m-%dT%H:%M:%S.%fZ'
                        )
                        filename_middle = event_ts.strftime("%Y%m%d_%H%M%S%f")[:-3]

                        event_slug = event_obj['message']['event_value'].upper().replace(' ', '_')
                        filename = (
                            f"{source.get('filename_prefix', source['source_name'])}"
                            f"_{filename_middle}_{event_slug}"
                            f"{source.get('filename_suffix', DEFAULT_FILENAME_SUFFIX)}"
                        )
                        dst = os.path.join(DEST_DIR, filename)

                        logging.debug("dst: %s", dst)

                        try:
                            res = requests.get(
                                source['source_url'] + source['source_filename'],
                                stream=True,
                                timeout=(2, None)
                            )

                            if res.status_code != 200:
                                logging.error(
                                    "Unable to retrieve image from: %s",
                                    source['source_url'] + source['source_filename']
                                )
                                continue

                        except requests.exceptions.RequestException as exc:
                            logging.error("Unable to retrieve image from remote server")
                            logging.error(exc)
                            continue

                        try:
                            with open(dst, 'wb') as f:
                                shutil.copyfileobj(res.raw, f)

                            aux_data_record['data_array'].append(
                                {'data_name': "camera_name", 'data_value': source['source_name']}
                            )
                            aux_data_record['data_array'].append(
                                {'data_name': "filename", 'data_value': dst}
                            )

                        except shutil.Error as exc:
                            logging.error("Unable to save image to server")
                            logging.error(exc)

                    if len(aux_data_record['data_array']) > 0:
                        create_event_aux_data(aux_data_record)

    except Exception as error:  # pylint: disable=broad-except
        logging.error(str(error))
        raise error

# -------------------------------------------------------------------------------------
# Required python code for running the script as a stand-alone utility
# -------------------------------------------------------------------------------------
if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser(
        description='Aux Data Inserter Service - ' +
        AUX_DATA_DATASOURCE)
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')
    parser.add_argument('-f', '--sources_file',
                        help='use the specified sources file instead of the built-in inline config')

    parsed_args = parser.parse_args()

    ############################
    # Set up logging before we do any other argument parsing (so that we
    # can log problems with argument parsing).

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    # Load the sources config, either from an external file or the
    # built-in inline default.
    if parsed_args.sources_file:
        try:
            with open(parsed_args.sources_file, 'r', encoding='utf-8') as file:
                sources_config = yaml.safe_load(file)
            sources = sources_config['sources']
        except (OSError, yaml.YAMLError, TypeError, KeyError) as error:
            logging.error("Could not load sources configuration from file")
            logging.debug(str(error))
            sys.exit(1)
    else:
        sources_config = yaml.safe_load(DEFAULT_SOURCES_CONFIG)
        sources = sources_config['sources']

    for src in sources:
        suffix = src.get('filename_suffix', DEFAULT_FILENAME_SUFFIX)
        if not suffix.endswith(ALLOWED_FILENAME_SUFFIXES):
            logging.error(
                "Invalid filename_suffix '%s' for source '%s': must end with one of %s",
                suffix, src.get('source_name', '<unknown>'), ALLOWED_FILENAME_SUFFIXES
            )
            sys.exit(1)

    # Run the main loop
    while True:

        # Wait 5 seconds for the server to complete startup
        time.sleep(5)

        try:
            # t.connect(username=user, pkey=my_key) # only needed for scp transfers
            asyncio.get_event_loop().run_until_complete(aux_data_inserter(sources))
        except KeyboardInterrupt:
            logging.error('Keyboard Interrupted')
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0)  # pylint: disable=protected-access
        except Exception as error:  # pylint: disable=broad-except
            logging.error("Lost connection to server, trying again in 5 seconds")
            logging.debug(str(error))
