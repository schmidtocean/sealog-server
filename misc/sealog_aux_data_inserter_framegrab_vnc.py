#!/usr/bin/env python3
'''
FILE:           sealog_aux_data_inserter_framegrab.py

DESCRIPTION:    This service listens for new events submitted to Sealog, captures
                a screenshot from a VNC server, renames/copies the file to the
                sealog-files/images directory and creates an aux_data record
                containing the image path
                Works reliably with vncdotool 0.12 - later versions may produce blank image

                The VNC sources are configured via the DEFAULT_SOURCES_CONFIG inline
                YAML block below. Pass --sources_file/-f to load the sources
                configuration from an external YAML file instead.

BUGS:
NOTES:
AUTHOR:     Webb Pinner / Kaarel-SOI
COMPANY:    OceanDataTools.org
VERSION:    1.3
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
from os import environ
from os.path import dirname, realpath

import yaml
import websockets
from vncdotool import api

sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.settings import WS_SERVER_URL, HEADERS
from misc.python_sealog.event_aux_data import create_event_aux_data

# VNC server details
VNC_PORT = 5900
VNC_PASSWORD = environ.get('VNC_VIEWONLY')
# The data_source to use for the auxData records
AUX_DATA_DATASOURCE = 'vesselRealtimeFramegrabberData'

# Set of events to ignore
EXCLUDE_SET = ('ASNAP',)

CLIENT_WSID = f'aux_data_inserter_{AUX_DATA_DATASOURCE}'

THRESHOLD = 20  # seconds
DEST_DIR = '/data/sealog-FKt-files/images/'

# Allowed image formats for screenshot captures.
DEFAULT_FILENAME_SUFFIX = '.png'
ALLOWED_FILENAME_SUFFIXES = ('.png', '.jpg', '.bmp')

# Default sources configuration, used unless an external sources file is
# specified via the --sources_file/-f command-line option.
# event_list is an optional list of event_values that trigger a screengrab
# in addition to any event_value containing source_name; it defaults to []
# and can be omitted entirely when not needed.
# filename_prefix is optional and defaults to source_name when omitted.
# filename_suffix is optional and defaults to .png when omitted; when set
# it must end with one of ALLOWED_FILENAME_SUFFIXES.
# sonar_quality: true marks a source as eligible for the SONAR QUALITY event.
DEFAULT_SOURCES_CONFIG = '''
sources:
  - source_name: POSMV
    source_address: 10.23.10.52

  - source_name: EM124
    source_address: 10.23.10.60
    event_list:
      - SONAR QUALITY
    sonar_quality: true

  - source_name: EM712
    source_address: 10.23.10.62
    event_list:
      - SONAR QUALITY
    sonar_quality: true

  - source_name: EM2040
    source_address: 10.23.10.64
    event_list:
      - SONAR QUALITY
    sonar_quality: true

  - source_name: EK80
    source_address: 10.23.10.66

  - source_name: SBP29
    source_address: 10.23.10.69

  - source_name: KSYNC
    source_address: 10.23.10.72

  - source_name: UHDAS
    source_address: 10.23.10.73
    filename_prefix: UHDAS-1

  - source_name: CTD
    source_address: 10.23.10.75
    event_list:
      - CTD
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


def capture_screenshot(vnc_server, vnc_password, filename):
    '''Capture a screenshot from a VNC server and save to filename.'''
    try:
        with api.connect(vnc_server, password=vnc_password, timeout=20.0) as client:
            client.refreshScreen()
            client.captureScreen(filename)
    except Exception as error:  # pylint: disable=broad-except
        logging.error("Error capturing screenshot: %s", str(error))


async def aux_data_inserter(sources):  # pylint:disable=redefined-outer-name
    '''
    Connect to the websocket feed for new events. When new events arrive,
    capture a screenshot, build aux_data records, and submit them to the sealog-server.
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

                    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                    if datetime.strptime(
                            event_obj['message']['ts'],
                            '%Y-%m-%dT%H:%M:%S.%fZ') < now_utc - timedelta(
                            seconds=THRESHOLD):
                        logging.debug("Skipping because event ts is older than threshold")
                        continue

                    aux_data_record = {
                        'event_id': event_obj['message']['id'],
                        'data_source': AUX_DATA_DATASOURCE,
                        'data_array': []
                    }

                    for source in sources:
                        event_val = event_obj['message']['event_value']
                        if (source['source_name'] not in event_val and
                                event_val not in source.get('event_list', [])):
                            logging.debug("Skipping because event value not VNC source")
                            continue
                        if event_val == 'SONAR QUALITY' and not source.get('sonar_quality', False):
                            logging.debug("Sonar quality but not multibeam, skipping")
                            continue

                        filename_date = datetime.date(datetime.strptime(
                            event_obj['message']['ts'],
                            '%Y-%m-%dT%H:%M:%S.%fZ')
                        )
                        filename_time = datetime.time(
                            datetime.strptime(
                                event_obj['message']['ts'],
                                '%Y-%m-%dT%H:%M:%S.%fZ'
                            )
                        )
                        filename_middle = datetime.combine(
                            filename_date, filename_time
                        ).strftime("%Y%m%d_%H%M%S%f")[:-3]

                        event_slug = event_obj['message']['event_value'].upper().replace(' ', '_')
                        screenshot_file = (
                            f"{source.get('filename_prefix', source['source_name'])}"
                            f"_{filename_middle}_{event_slug}"
                            f"{source.get('filename_suffix', DEFAULT_FILENAME_SUFFIX)}"
                        )
                        dst = os.path.join(DEST_DIR, screenshot_file)

                        logging.debug("dst: %s", dst)

                        try:
                            await asyncio.to_thread(
                                capture_screenshot,
                                f"{source['source_address']}::{VNC_PORT}",
                                VNC_PASSWORD, screenshot_file
                            )

                            if os.path.exists(screenshot_file):
                                shutil.move(screenshot_file, dst)
                                aux_data_record['data_array'].append(
                                    {'data_name': "camera_name",
                                     'data_value': source['source_name']}
                                )
                                aux_data_record['data_array'].append(
                                    {'data_name': "filename", 'data_value': dst}
                                )

                        except Exception as error:  # pylint: disable=broad-except
                            logging.error("Unable to save screenshot")
                            logging.error(error)

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
    # event_list is the list of event_values that trigger a screengrab.
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
