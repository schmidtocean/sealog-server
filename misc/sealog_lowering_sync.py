#!/usr/bin/env python3
"""Forward Sub and EMP deployment and recovery events to FKt."""

import argparse
import asyncio
import json
import logging
import runpy

import requests
import websockets


EVENTS_API_PATH = '/api/v1/events'
LOWERING_BY_EVENT_PATH = '/api/v1/lowerings/byevent'
SUBSCRIPTION_PATH = '/ws/status/newEvents'

SETTINGS_FILES = {
    'fkt': '/opt/sealog-server-fkt/misc/python_sealog/settings.py',
    'sub': '/opt/sealog-server-sub/misc/python_sealog/settings.py',
    'emp': '/opt/sealog-server-emp/misc/python_sealog/settings.py',
}

MAPPINGS = {
    'sub': {
        'event_value': 'ROV',
        'event_options': [],
        'milestones': {
            'off deck': 'Deployed',
            'on deck': 'Recovered',
        },
    },
    'emp': {
        'event_value': 'EQUIPMENT',
        'event_options': [
            {'event_option_name': 'system', 'event_option_value': 'AUV'},
        ],
        'milestones': {
            'in water': 'Deployed',
            'out of water': 'Recovered',
        },
    },
}


def destination_status(instance, event):
    """Return the FKt status for a source milestone, or None if unrelated."""
    mapping = MAPPINGS[instance]
    if str(event.get('event_value', '')).upper() != 'VEHICLE':
        return None

    for option in event.get('event_options', []):
        if str(option.get('event_option_name', '')).lower() != 'milestone':
            continue
        value = option.get('event_option_value')
        if isinstance(value, str):
            status = mapping['milestones'].get(value.strip().lower())
        else:
            status = None
        if status:
            return status
    return None


def destination_event(instance, event, lowering):
    """Return the corresponding FKt event, or None for unrelated events."""
    mapping = MAPPINGS[instance]
    status = destination_status(instance, event)

    lowering_id = lowering.get('lowering_id')
    if not status or not lowering_id:
        return None

    event_options = [dict(option) for option in mapping['event_options']]
    event_options.extend([
        {'event_option_name': 'status', 'event_option_value': status},
        {'event_option_name': 'dive_number', 'event_option_value': lowering_id},
    ])
    return {
        'event_value': mapping['event_value'],
        'event_options': event_options,
        'ts': event['ts'],
        'event_author': event.get('event_author') or 'sync_script',
    }


def forward_event(instance, event, source, destination):
    """Resolve the source lowering and post one relevant event to FKt."""
    if destination_status(instance, event) is None:
        return False

    response = requests.get(
        source['apiServerURL'].rstrip('/') + LOWERING_BY_EVENT_PATH + '/' + event['id'],
        headers=source['headers'],
        timeout=10,
    )
    response.raise_for_status()
    lowering = response.json()
    if not isinstance(lowering, dict):
        logging.warning('No lowering found for source event %s', event['id'])
        return False
    payload = destination_event(instance, event, lowering)
    if payload is None:
        logging.warning('No lowering ID found for source event %s', event['id'])
        return False

    response = requests.post(
        destination['apiServerURL'].rstrip('/') + EVENTS_API_PATH,
        headers=destination['headers'],
        json=payload,
        timeout=10,
    )
    response.raise_for_status()
    logging.info(
        'Forwarded %s %s for %s',
        instance,
        payload['event_options'][-2]['event_option_value'],
        lowering['lowering_id'],
    )
    return True


async def listen(source, destination):
    """Listen to one source instance until its WebSocket disconnects."""
    instance = source['instance'].lower()
    client_id = 'sealogLoweringSync-' + instance
    hello = {
        'type': 'hello',
        'id': client_id,
        'auth': {'headers': source['headers']},
        'version': '2',
        'subs': [SUBSCRIPTION_PATH],
    }
    async with websockets.connect(source['websocketServerURL']) as websocket:
        logging.info('Connected to %s event feed', instance)
        await websocket.send(json.dumps(hello))
        async for message in websocket:
            message = json.loads(message)
            if message.get('type') == 'ping':
                await websocket.send(json.dumps({'type': 'ping', 'id': client_id}))
            elif message.get('type') == 'pub' and message.get('path') == SUBSCRIPTION_PATH:
                try:
                    await asyncio.to_thread(
                        forward_event, instance, message['message'], source, destination,
                    )
                except (KeyError, TypeError, ValueError, requests.RequestException):
                    logging.exception('Could not forward %s event', instance)


async def reconnecting_listener(source, destination):
    """Keep one source listener alive without interrupting other sources."""
    while True:
        try:
            await listen(source, destination)
        except (OSError, ValueError, websockets.exceptions.WebSocketException):
            logging.exception('%s source connection failed', source['instance'])
        await asyncio.sleep(5)


def load_server_settings(filename, websocket=False):
    """Load API connection values from an installed Sealog settings file."""
    settings = runpy.run_path(filename)
    connection = {
        'apiServerURL': settings['API_SERVER_URL'],
        'headers': settings['HEADERS'],
    }
    if websocket:
        connection['websocketServerURL'] = settings['WS_SERVER_URL']
    return connection


def load_connections():
    """Load FKt, Sub, and EMP connection values from installed settings."""
    destination = load_server_settings(SETTINGS_FILES['fkt'])
    sources = []
    for instance in MAPPINGS:
        connection = load_server_settings(SETTINGS_FILES[instance], websocket=True)
        connection['instance'] = instance
        sources.append(connection)
    return destination, sources


async def run(destination, sources):
    """Run all source listeners independently."""
    await asyncio.gather(*(
        reconnecting_listener(source, destination) for source in sources
    ))


def main():
    """Parse settings and run the forwarding service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbosity', action='count', default=0)
    args = parser.parse_args()
    logging.basicConfig(
        level=[logging.WARNING, logging.INFO, logging.DEBUG][min(args.verbosity, 2)],
        format='%(asctime)s %(levelname)s - %(message)s',
    )
    try:
        destination, sources = load_connections()
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.error(str(error))

    try:
        asyncio.run(run(destination, sources))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
