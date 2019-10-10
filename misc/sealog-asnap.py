#!/usr/bin/env python3
#
# Purpose: This service submits ASNAP events to Sealog at the 
#          specified interval so long as Sealog says ASNAPs should
#          be created.
#
#   Usage: Type python3 sealog-asnap.py to start the service.
#
#          This serivce runs in the forground. Type ^d to kill the
#          service.
#
#  Author: Webb Pinner webbpinner@gmail.com
# Created: 2018-09-26
# Updated: 2019-10-07

import json
import requests
import time
import sys
import os
import logging
import python_sealog
from python_sealog.settings import apiServerURL, cruisesAPIPath, eventsAPIPath, customVarAPIPath, headers

# Default logging level
LOG_LEVEL = logging.INFO

# create logger
logger = logging.getLogger(__file__)
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

asnapStatusVarName = 'asnapStatus'

interval = 10 #seconds

clientWSID = "asnap"

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
  'id': clientWSID
}

eventTemplate = {
  "event_value": "ASNAP",
  "event_options": [],
  "event_free_text": ""
}

def asnapService(interval):
  """
  This is the main function for this script.  It creates a new event request at the specified interval
  """

  runFlag = True
  while True:
    try:
      r = requests.get(apiServerURL + customVarAPIPath + '?name=' + asnapStatusVarName, headers=headers )
      response = json.loads(r.text)

      if type(response) != type([]):
        print("response:", response)
      else:

        if response[0]['custom_var_value'] == 'On':
          runFlag = True
        elif response[0]['custom_var_value'] == 'Off':
          runFlag = False
    except Exception as error:
      print(error)

    if runFlag:
      try:
        logger.debug("Submitting ASNAP Event")
        r = requests.post(apiServerURL + eventsAPIPath, headers=headers, data = json.dumps(eventTemplate))

      except Exception as error:
        print(error)

    time.sleep(interval)

if __name__ == '__main__':
  """
  This script submit a new ASNAP event at the specified interval
  """

  import argparse

  parser = argparse.ArgumentParser(description='ASNAP event submission service')
  parser.add_argument('-d', '--debug', action='store_true', help=' display debug messages')
  parser.add_argument('-i', '--interval', help='ASNAP interval in seconds.')

  args = parser.parse_args()

  # Turn on debug mode
  if args.debug:
    logger.info("Setting log level to DEBUG")
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
      handler.setLevel(logging.DEBUG)
    logger.debug("Log level now set to DEBUG")

  if args.interval:
    interval = args.interval
    logger.info("Interval set to " + args.interval + " seconds.")

  try:
    asnapService(interval)
  except KeyboardInterrupt:
    print('Interrupted')
    try:
      sys.exit(0)
    except SystemExit:
      os._exit(0)


