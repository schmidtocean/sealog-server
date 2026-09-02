#!/usr/bin/env python3
'''
FILE:           sealog_vessel_data_export_FKt.py

DESCRIPTION:    This script exports all the data for a given cruise.
                example usage:
                python ./misc/sealog_vessel_data_export_FKt.py -v -C FKt291212

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    2.0
CREATED:    2018-11-07
REVISION:   2026-05-25

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
'''
# pylint: disable=invalid-name

import sys
import os
import json
import logging
import subprocess

from os.path import dirname, realpath
sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.cruises import get_cruises, get_cruise_by_id
from misc.python_sealog.misc import get_framegrab_list_by_cruise
from misc.python_sealog.events import get_events_by_cruise
from misc.python_sealog.event_aux_data import get_event_aux_data_by_cruise
from misc.python_sealog.event_exports import get_event_exports_by_cruise
from misc.python_sealog.event_templates import get_event_templates
from misc.base_data_exporter import SealogDataExporter

EXPORT_ROOT_DIR = '/data/sealog-FKt-export'
VESSEL_NAME = 'R/V Falkor (too)'
EXPORT_IMAGES = True
IMAGE_DATASOURCES = ['vesselRealtimeFramegrabberData']

OPENVDM_IP = '10.23.9.20'
OPENVDM_USER = 'mt'
OPENVDM_SSH_KEY = '/home/mt/.ssh/id_rsa_openvdm'
CRUISEDATA_DIR_ON_DATA_WAREHOUSE = '/mnt/CruiseData'
SEALOG_DIR = 'Falkor_too/Raw/Sealog'
CREATE_DEST_DIR = False


class FKtVesselDataExporter(SealogDataExporter):  # pylint: disable=too-few-public-methods
    """Exports cruise-level event data for the R/V Falkor (too)."""

    def _cruise_file_prefix(self, cruise):
        return cruise['cruise_id']

    def _get_cruise_export_tasks(self):
        return [
            {
                'description': 'Cruise Record',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_cruiseRecord.json'
                ),
                'data_fn': json.dumps,
            },
            {
                'description': 'Events (json)',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_eventOnlyExport.json'
                ),
                'data_fn': lambda c: json.dumps(get_events_by_cruise(c['id'])),
            },
            {
                'description': 'Events (csv)',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_eventOnlyExport.csv'
                ),
                'data_fn': lambda c: get_events_by_cruise(c['id'], 'csv'),
            },
            {
                'description': 'Aux Data',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_auxDataExport.json'
                ),
                'data_fn': lambda c: json.dumps(get_event_aux_data_by_cruise(c['id'])),
            },
            {
                'description': 'Events with Aux Data (json)',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_sealogExport.json'
                ),
                'data_fn': lambda c: json.dumps(get_event_exports_by_cruise(c['id'])),
            },
            {
                'description': 'Events with Aux Data (csv)',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_sealogExport.csv'
                ),
                'data_fn': lambda c: get_event_exports_by_cruise(c['id'], 'csv'),
            },
            {
                'description': 'Event Templates',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_eventTemplates.json'
                ),
                'data_fn': lambda c: json.dumps(get_event_templates()),
            },
        ]

    def _export_images(self, cruise, cruise_dir):
        logging.info("Exporting Images")
        framegrab_list = get_framegrab_list_by_cruise(cruise['id'], self.image_datasources)
        images_dir = os.path.join(cruise_dir, self.IMAGES_DIRNAME)
        self._rsync_images(framegrab_list, images_dir)

    def push_to_data_warehouse(self, cruise):
        """Push exported data to the OpenVDM data warehouse."""
        if CREATE_DEST_DIR:
            dest = os.path.join(CRUISEDATA_DIR_ON_DATA_WAREHOUSE, cruise['cruise_id'])
            command = [
                'ssh', '-i', OPENVDM_SSH_KEY,
                f"{OPENVDM_USER}@{OPENVDM_IP}",
                f"cd {dest}; test -d {SEALOG_DIR} || mkdir -p {SEALOG_DIR}"
            ]
            logging.debug(' '.join(command))
            subprocess.call(command)

        dest = os.path.join(
            CRUISEDATA_DIR_ON_DATA_WAREHOUSE, cruise['cruise_id'], SEALOG_DIR, '')
        command = [
            'rsync', '-trimv', '--progress', '--delete',
            '-e', f'ssh -i {OPENVDM_SSH_KEY}',
            os.path.join(EXPORT_ROOT_DIR, cruise['cruise_id'], ''),
            f"{OPENVDM_USER}@{OPENVDM_IP}:{dest}"
        ]
        logging.debug(' '.join(command))
        subprocess.call(command)

    def export_cruise(self, cruise):
        """Export all data for the given cruise."""
        logging.info("Exporting data for cruise %s", cruise['cruise_id'])

        cruise_dir = os.path.join(self.export_root_dir, cruise['cruise_id'])
        dirs = {
            'cruise': cruise_dir,
            'files': os.path.join(cruise_dir, self.FILES_DIRNAME),
        }
        if self.export_images:
            dirs['images'] = os.path.join(cruise_dir, self.IMAGES_DIRNAME)

        self._build_export_directories(dirs)

        for task in self._get_cruise_export_tasks():
            filepath = task['path'](cruise, dirs)
            if filepath is not None:
                try:
                    content = task['data_fn'](cruise)
                except Exception as err:  # pylint: disable=broad-except
                    logging.error("Failed to export %s: %s", task['description'], err)
                    continue
                self._write_file(filepath, content, task['description'])

        if self.export_images:
            self._export_images(cruise, cruise_dir)
        self._export_cruise_files(cruise, cruise_dir)


if __name__ == '__main__':

    import argparse

    exporter = FKtVesselDataExporter(
        name=VESSEL_NAME,
        export_root_dir=EXPORT_ROOT_DIR,
        export_images=EXPORT_IMAGES,
        image_datasources=IMAGE_DATASOURCES,
    )

    parser = argparse.ArgumentParser(description='Sealog ' + VESSEL_NAME + ' Data export')
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')
    parser.add_argument('-n', '--no_transfer', action='store_true', default=False,
                        help='build reports and export data but do not push to data warehouse')
    parser.add_argument('-t', '--transfer_only', action='store_true', default=False,
                        help='only push the exported data to data warehouse')
    parser.add_argument('-C', '--cruise_id',
                        help='export data for the specified cruise (i.e. FKt230301)')

    parsed_args = parser.parse_args()

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    if parsed_args.cruise_id:
        selected_cruise = get_cruise_by_id(parsed_args.cruise_id)
        if selected_cruise is None:
            logging.error("Cruise %s not found", parsed_args.cruise_id)
            sys.exit(0)
    else:
        selected_cruise = next(iter(get_cruises()), None)
        if selected_cruise is None:
            logging.error("There are no cruises available for export")
            sys.exit(0)

    if parsed_args.transfer_only:
        exporter.push_to_data_warehouse(selected_cruise)
        logging.debug("Done")
        sys.exit(0)

    success, msg = exporter.verify_source_directories(selected_cruise)
    if not success:
        logging.error(msg)
        sys.exit(0)

    if not os.path.isdir(EXPORT_ROOT_DIR):
        logging.error("Cannot find export directory: %s", EXPORT_ROOT_DIR)
        sys.exit(1)

    logging.info("Cruise ID: %s", selected_cruise['cruise_id'])
    if 'cruise_name' in selected_cruise['cruise_additional_meta']:
        logging.info(
            "Cruise Name: %s", selected_cruise['cruise_additional_meta']['cruise_name'])

    exporter.export_cruise(selected_cruise)

    if not parsed_args.no_transfer:
        exporter.push_to_data_warehouse(selected_cruise)

    logging.debug("Done")
