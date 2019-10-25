#!/usr/bin/env python3
#
#  Purpose: This service listens for new events submitted to Sealog, creates
#           an aux_data record containing current vehicle position and attitude
#           data and associates the aux data record with the newly created
#           event.
#
#           However this will only happen if the timestamp of the event
#           is within 120 seconds from the current server time.
#
#    Usage: Type python3 sealog-auxDataInserter-nav.py to start the service.
#
#           This serivce runs in the forground. Type ^d to kill the
#           service.
#
#   Author: Webb Pinner webbpinner@gmail.com
#  Created: 2018-12-05
# Modified: 2019-10-07

import asyncio
import websockets
import json
import requests
import logging
import os
import sys
from datetime import datetime
from pymongo import MongoClient

import python_sealog
from python_sealog.settings import apiServerURL, wsServerURL, cruisesAPIPath, eventsAPIPath, auxDataAPIPath, headers

# set of events to ignore
excludeSet = ()

clientWSID = 'auxData-navInserter'

hello = {
  'type': 'hello',
  'id': clientWSID,
  'auth': {
    'headers': headers
  },
  'version': '2',
  'subs': ['/ws/status/newEvents']
}

ping = {
  'type':'ping',
  'id':clientWSID
}

auxDataTemplate = {
  'event_id': None,
  'data_source': None,
  'data_array': []
}

client = MongoClient()
db = client.udpDataCache
collection = db.udpData

LOG_LEVEL = logging.INFO

# create logger
logger = logging.getLogger(__file__ )
logger.setLevel(LOG_LEVEL)

# create console handler and set level to debug
ch = logging.StreamHandler()
ch.setLevel(LOG_LEVEL)

# create formatter
formatter = logging.Formatter('%(asctime)s - %(name)s:%(lineno)s - %(levelname)s - %(message)s')

# add formatter to ch
ch.setFormatter(formatter)

# add ch to logger
logger.addHandler(ch)

async def auxDataInserter():
  try:
    async with websockets.connect(wsServerURL) as websocket:

      await websocket.send(json.dumps(hello))

      while(True):

        event = await websocket.recv()
        eventObj = json.loads(event)

        if eventObj['type'] and eventObj['type'] == 'ping':
          await websocket.send(json.dumps(ping))
        elif eventObj['type'] and eventObj['type'] == 'pub' and eventObj['message']['event_value'] not in excludeSet:

          try:
            record = collection.find_one()

            logger.debug("Record from database:\n" + json.dumps(record.data, indent=2))

            auxNavData = auxDataTemplate

            auxNavData['event_id'] = eventObj['message']['id']
            auxNavData['data_source'] = "vehicleRealtimeNavData"
            auxNavData['data_array'] = []

            auxNavData['data_array'].append({ 'data_name': "latitude",'data_value': float(record['data']['latitude']).round(6), 'data_uom': 'ddeg' })
            auxNavData['data_array'].append({ 'data_name': "longitude",'data_value': float(record['data']['longitude']).round(6), 'data_uom': 'ddeg' })
            auxNavData['data_array'].append({ 'data_name': "depth",'data_value': record['data']['depth'], 'data_uom': 'meters' })
            auxNavData['data_array'].append({ 'data_name': "heading",'data_value': record['data']['heading'], 'data_uom': 'deg' })
            auxNavData['data_array'].append({ 'data_name': "pitch",'data_value': record['data']['pitch'], 'data_uom': 'deg' })
            auxNavData['data_array'].append({ 'data_name': "roll",'data_value': record['data']['roll'], 'data_uom': 'deg' })
            auxNavData['data_array'].append({ 'data_name': "altitude",'data_value': record['data']['altitude'], 'data_uom': 'meters' })

            logger.debug("Aux Data Record:\n" + json.dumps(auxNavData, indent=2))

          except Exception as error:
            logger.error("Error submitting auxData record: " + str(error))
          
          try:
            logger.debug("Submitting AuxData record to Sealog Server")
            r = requests.post(apiServerURL + auxDataAPIPath, headers=headers, data = json.dumps(auxNavData))
            logger.debug("Response: " + r.text)

          except Exception as error:
            logger.error("Error submitting auxData record: " + str(error))

        else:
          logger.debug("Skipping because event value is in the exclude set")

  except Exception as error:
    logger.error(str(error))

if __name__ == '__main__':

  import argparse
  import os
  import sys

  parser = argparse.ArgumentParser(description='Aux Data Inserter Service - Nav Data')
  parser.add_argument('-d', '--debug', action='store_true', help=' display debug messages')

  args = parser.parse_args()

  # Turn on debug mode
  if args.debug:
    logger.info("Setting log level to DEBUG")
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
      handler.setLevel(logging.DEBUG)
    logger.debug("Log level now set to DEBUG")
  
  # Run the main loop
  try:
    asyncio.get_event_loop().run_until_complete(auxDataInserter())
  except KeyboardInterrupt:
    print('Interrupted')
    try:
      sys.exit(0)
    except SystemExit:
      os._exit(0)