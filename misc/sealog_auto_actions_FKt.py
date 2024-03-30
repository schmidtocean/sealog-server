#!/usr/bin/env python3
'''
FILE:           sealog_auto_actions.py

DESCRIPTION:    This service listens for new events submitted to Sealog and
                performs additional actions depending on the recieved event.

                This service listens for "Start of Cruise" and "Arrived at
                Dock/Port" status and enables/disables the ASNAP functionality
                and if a lowering is currently active it will set the start/
                stop time to the time of the event.

                This service listens for "On bottom" and "Off bottom" status
                and if a lowering is currently active it will set the
                lowering_on_bottom/lowering_off_bottom statu times to the time
                of the event.

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    1.0
CREATED:    2018-09-26
REVISION:   2024-03-30

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
'''

import sys
import asyncio
import json
import logging
import time
import requests
import websockets

from os.path import dirname, realpath
sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.custom_vars import get_custom_var_uid_by_name, set_custom_var
from misc.python_sealog.events import get_events_by_lowering
from misc.python_sealog.lowerings import get_lowering_by_event
from misc.python_sealog.settings import API_SERVER_URL, WS_SERVER_URL, HEADERS, EVENTS_API_PATH, LOWERINGS_API_PATH

ASNAP_STATUS_VAR_NAME = 'asnapStatus'

INCLUDE_SET = ('CRUISE')

CLIENT_WSID = 'autoActions'

HELLO = {
    'type': 'hello',
    'id': CLIENT_WSID,
    'auth': {
        'headers': HEADERS
    },
    'version': '2',
    'subs': ['/ws/status/newEvents', '/ws/status/updateEvents']
}

PING = {
    'type':'ping',
    'id':CLIENT_WSID
}

ASNAP_LOOKUP = {
    'Start of Cruise': 'On',
    'Arrived at Dock/Port': 'Off'
}

def _handle_vessel_event(event):
    '''
    The function handle auto actions for the VEHICLE event_value.  It uses the
    included event_options to set the lowering start/stop times, ASNAP status
    and dive milestones.
    '''

    status = None

    # if event has status event_option, pass status to _set_asnap and _set_statuss
    for option in event['event_options']:
        if option['event_option_name'] == "status":
            status = option['event_option_value']
            break

    if status is not None:
        _set_asnap(status)
        

def _set_asnap(evt_status):
    '''
    Sets the ASNAP status variable based on the evt_status
    '''

    # if evt_status not in ASNAP_LOOKUP, return
    if evt_status not in ASNAP_LOOKUP:
        return

    # Get the UID for the ASNAP custom_var
    asnap_status_var_uid = get_custom_var_uid_by_name(ASNAP_STATUS_VAR_NAME)

    logging.info("Setting ASNAP to %s", ASNAP_LOOKUP[evt_status])
    set_custom_var(asnap_status_var_uid, ASNAP_LOOKUP[evt_status])


async def auto_actions(): #pylint: disable=too-many-branches, too-many-statements
    '''
    Listen to the new and updated events and respond as instructed based on the
    event and it's options
    '''

    try:

        async with websockets.connect(WS_SERVER_URL) as websocket:

            await websocket.send(json.dumps(HELLO))

            while True:

                msg = await websocket.recv()
                msg_obj = json.loads(msg)

                if msg_obj['type'] and msg_obj['type'] == 'ping':
                    await websocket.send(json.dumps(PING))

                elif msg_obj['type'] and msg_obj['type'] == 'pub':

                    event = msg_obj['message']
                    logging.debug("Event: \n%s", json.dumps(event, indent=2))

                    if event['event_value'] not in INCLUDE_SET:
                        logging.debug("Skipping because event value is not in the include set")
                        continue

                    _handle_vessel_event(event)

    except Exception as error:
        logging.error(str(error))


# -------------------------------------------------------------------------------------
# Required python code for running the script as a stand-alone utility
# -------------------------------------------------------------------------------------
if __name__ == '__main__':

    import argparse
    import os

    parser = argparse.ArgumentParser(description='Auto-Actions Service')
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')

    parsed_args = parser.parse_args()

    ############################
    # Set up logging before we do any other argument parsing (so that we
    # can log problems with argument parsing).

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    # Run the main loop
    while True:

        # Wait 5 seconds for the server to complete startup
        time.sleep(5)

        try:
            logging.debug("Listening to event websocket feed...")
            asyncio.get_event_loop().run_until_complete(auto_actions())
        except KeyboardInterrupt:
            logging.error('Keyboard Interrupted')
            try:
                sys.exit(0)
            except SystemExit:
                os._exit(0) # pylint: disable=protected-access
        except Exception as error:
            logging.error("Lost connection to server, trying again in 5 seconds")
            logging.debug(str(error))
