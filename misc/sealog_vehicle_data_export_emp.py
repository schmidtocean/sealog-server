#!/usr/bin/env python3
'''
FILE:           sealog_vehicle_data_export_emp.py

DESCRIPTION:    Export Empress Sealog records, images, and user-uploaded files
                to the CruiseData vehicle directory.

BUGS:
NOTES:
AUTHOR:     Kaarel-SOI
COMPANY:    Schmidt Ocean Institute
VERSION:    1
CREATED:    2026-05-09
REVISION:   2026-05-09

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
'''

import json
import logging
import os
import subprocess
import sys
import tempfile
from typing import Any, cast

from os.path import dirname, realpath
sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.cruises import get_cruise_by_id, get_cruise_by_lowering, get_cruises
from misc.python_sealog.event_aux_data import get_event_aux_data_by_lowering
from misc.python_sealog.event_exports import get_event_exports_by_lowering
from misc.python_sealog.event_templates import get_event_templates
from misc.python_sealog.events import get_events_by_lowering
from misc.python_sealog.lowerings import get_lowering_by_id, get_lowerings, get_lowerings_by_cruise
from misc.python_sealog.misc import get_framegrab_list_by_lowering
from misc.python_sealog.settings import API_SERVER_FILE_PATH, SLACK_WEBHOOK_URL
from misc.python_sealog.slack import PooledSlackHandler

SLACK_LOG_LEVEL = 'INFO'

EXPORT_ROOT_DIR = '/data/sealog-emp-export'
VEHICLE_NAME = 'Empress'

CRUISEDATA_LOCAL_MOUNT = '/mnt/CruiseData'
OPENVDM_VEHICLE_DIR = 'Vehicles/' + VEHICLE_NAME
SEALOG_DIR = 'Sealog'

CREATE_DEST_DIR = True

CRUISES_FILE_PATH = os.path.join(API_SERVER_FILE_PATH, 'cruises')
IMAGES_FILE_PATH = os.path.join(API_SERVER_FILE_PATH, 'images')
LOWERINGS_FILE_PATH = os.path.join(API_SERVER_FILE_PATH, 'lowerings')

IMAGES_DIRNAME = 'Images'
FILES_DIRNAME = 'Files'

SealogRecord = dict[str, Any]
SealogRecords = list[SealogRecord]


def _export_dir_name(cruise_id, lowering_id):
    '''
    Build the SOI lowering directory name used in CruiseData.
    '''

    if lowering_id[1:].isnumeric():
        return cruise_id + '_' + lowering_id

    return lowering_id


def _verify_source_directories():
    '''
    Verify all required source directories exist.
    '''

    required_directories = {
        'cruises file path': CRUISES_FILE_PATH,
        'images file path': IMAGES_FILE_PATH,
        'lowerings file path': LOWERINGS_FILE_PATH,
        'local CruiseData mount': CRUISEDATA_LOCAL_MOUNT,
    }

    for label, path in required_directories.items():
        if not os.path.isdir(path):
            return False, 'Cannot find %s: %s' % (label, path)

    return True, ''


def _export_lowering_images(cruise, lowering): # pylint: disable=redefined-outer-name
    '''
    Sync framegrabs for the lowering into the export staging directory.
    '''

    logging.info("Export Images")

    lowering_export_dir = os.path.join(
        EXPORT_ROOT_DIR,
        cruise['cruise_id'],
        _export_dir_name(cruise['cruise_id'], lowering['lowering_id']),
    )
    images_export_dir = os.path.join(lowering_export_dir, IMAGES_DIRNAME)
    framegrab_list = get_framegrab_list_by_lowering(lowering['id'])

    existing_framegrab_list = os.listdir(images_export_dir)
    exported_framegrab_names = {os.path.basename(filepath) for filepath in framegrab_list}
    delete_framegrab_list = set(existing_framegrab_list) - exported_framegrab_names

    for filename in delete_framegrab_list:
        try:
            logging.info('Deleting: %s', filename)
            os.remove(os.path.join(images_export_dir, filename))
        except Exception as err:
            logging.warning('Could not delete stale image: %s', filename)
            logging.debug(str(err))

    temp_list_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as file:
            temp_list_path = file.name
            for framegrab in framegrab_list:
                file.write(os.path.basename(framegrab) + '\n')

        logging.info("Starting rclone transfer for images")
        subprocess.run([
            'rclone',
            'copy',
            '--transfers=16',
            '--checkers=16',
            '--size-only',
            '--progress',
            '--no-traverse',
            '--files-from', temp_list_path,
            IMAGES_FILE_PATH,
            images_export_dir,
        ], check=True)
    except subprocess.CalledProcessError as err:
        logging.error("Image transfer failed for lowering %s", lowering['lowering_id'])
        logging.debug(str(err))
    finally:
        if temp_list_path and os.path.exists(temp_list_path):
            os.remove(temp_list_path)


def _export_lowering_sealog_data_files(cruise, lowering): # pylint: disable=too-many-statements, redefined-outer-name
    '''
    Export lowering data from the database in CSV and JSON formats.
    '''

    logging.info("Exporting lowering-level data files")

    lowering_export_dir = os.path.join(
        EXPORT_ROOT_DIR,
        cruise['cruise_id'],
        _export_dir_name(cruise['cruise_id'], lowering['lowering_id']),
    )

    json_exports = [
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_loweringRecord.json',
            lowering,
            "Export Lowering Record",
        ),
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_eventOnlyExport.json',
            get_events_by_lowering(lowering['id']),
            "Export Events (json-format)",
        ),
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_auxDataExport.json',
            get_event_aux_data_by_lowering(lowering['id']),
            "Export Aux Data",
        ),
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_sealogExport.json',
            get_event_exports_by_lowering(lowering['id'], add_record_ids=True),
            "Export Events with Aux Data (json-format)",
        ),
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_eventTemplates.json',
            get_event_templates(),
            "Export Event Templates",
        ),
    ]

    for filename, contents, log_message in json_exports:
        logging.info("%s: %s", log_message, filename)
        try:
            with open(os.path.join(lowering_export_dir, filename), 'w', encoding='utf-8') as file:
                json.dump(contents, file)
        except Exception as err:
            logging.error('Could not create data file: %s', filename)
            logging.debug(str(err))

    csv_exports = [
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_eventOnlyExport.csv',
            get_events_by_lowering(lowering['id'], 'csv'),
            "Export Events (csv-format)",
        ),
        (
            cruise['cruise_id'] + '_' + lowering['lowering_id'] + '_sealogExport.csv',
            get_event_exports_by_lowering(lowering['id'], 'csv', add_record_ids=True),
            "Export Events with Aux Data (csv-format)",
        ),
    ]

    for filename, contents, log_message in csv_exports:
        logging.info("%s: %s", log_message, filename)
        try:
            with open(os.path.join(lowering_export_dir, filename), 'w', encoding='utf-8') as file:
                file.write(contents)
        except Exception as err:
            logging.error('Could not create data file: %s', filename)
            logging.debug(str(err))

    _export_lowering_images(cruise, lowering)


def _export_cruise_sealog_data_files(cruise):
    '''
    Export cruise-level Sealog data files.
    '''

    logging.info("Exporting cruise-level data files")

    cruise_export_dir = os.path.join(EXPORT_ROOT_DIR, cruise['cruise_id'])
    exports = [
        (
            cruise['cruise_id'] + '_' + VEHICLE_NAME + '_cruiseRecord.json',
            cruise,
            "Export Cruise Record",
        ),
        (
            cruise['cruise_id'] + '_' + VEHICLE_NAME + '_eventTemplates.json',
            get_event_templates(),
            "Export Event Templates",
        ),
    ]

    for filename, contents, log_message in exports:
        logging.info("%s: %s", log_message, filename)
        try:
            with open(os.path.join(cruise_export_dir, filename), 'w', encoding='utf-8') as file:
                json.dump(contents, file)
        except Exception as err:
            logging.error('Could not create data file: %s', filename)
            logging.debug(str(err))


def _stage_lowering_files(lowering, lowering_source_dir):
    '''
    Copy non-report files uploaded to the lowering into the export staging area.
    '''

    logging.info("Export User Uploaded Files")

    files_dest_dir = os.path.join(lowering_source_dir, FILES_DIRNAME)
    os.makedirs(files_dest_dir, exist_ok=True)

    try:
        subprocess.run([
            'rsync',
            '-avi',
            '--progress',
            '--delete',
            '--exclude=*_Report.pdf',
            os.path.join(API_SERVER_FILE_PATH, 'lowerings', lowering['id'], ''),
            files_dest_dir,
        ], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as err:
        logging.error("Failed to sync user files for lowering %s: %s", lowering['lowering_id'], err.stderr)
        return False

    return True


def _push_2_data_warehouse(cruise, lowerings): # pylint: disable=redefined-outer-name
    '''
    Push the staged export files to CruiseData.
    '''

    cruise_source_dir = os.path.join(EXPORT_ROOT_DIR, cruise['cruise_id'])
    if not os.path.isdir(cruise_source_dir):
        logging.error('Exported directory for cruise data not found: %s', cruise_source_dir)
        return False

    transfer_success = True

    for lowering in lowerings:
        lowering_dir_name = _export_dir_name(cruise['cruise_id'], lowering['lowering_id'])
        lowering_source_dir = os.path.join(cruise_source_dir, lowering_dir_name)

        if not os.path.isdir(lowering_source_dir):
            logging.error('Exported directory for lowering data not found: %s', lowering_source_dir)
            transfer_success = False
            continue

        if not _stage_lowering_files(lowering, lowering_source_dir):
            transfer_success = False
            continue

        warehouse_dest_dir = os.path.join(
            CRUISEDATA_LOCAL_MOUNT,
            cruise['cruise_id'],
            OPENVDM_VEHICLE_DIR,
            lowering_dir_name,
            SEALOG_DIR,
        )

        if CREATE_DEST_DIR:
            try:
                os.makedirs(warehouse_dest_dir, exist_ok=True)
            except Exception as err:
                logging.error("Failed to create Sealog directory: %s", warehouse_dest_dir)
                logging.debug(str(err))
                transfer_success = False
                continue

        try:
            logging.info("Rclone syncing Sealog data for %s", lowering['lowering_id'])
            subprocess.run([
                'rclone',
                'sync',
                '--transfers=16',
                '--checkers=16',
                '--size-only',
                '--progress',
                lowering_source_dir,
                warehouse_dest_dir,
            ], check=True, capture_output=False, text=True)
        except subprocess.CalledProcessError as err:
            logging.error("Failed to sync Sealog data for lowering %s: %s", lowering['lowering_id'], err.stderr)
            logging.debug(str(err))
            transfer_success = False

    return transfer_success


def _select_export_scope(parsed_args: Any) -> tuple[SealogRecord, SealogRecords]:
    '''
    Select the cruise and lowerings requested by the command-line arguments.
    '''

    if parsed_args.current_cruise:
        cruises = cast(SealogRecords, get_cruises())
        selected_cruise = cruises[0] if cruises else None

        if selected_cruise is None:
            logging.error("There are no cruises available for export")
            sys.exit(0)

        selected_lowerings = cast(SealogRecords, get_lowerings_by_cruise(selected_cruise['id']))
        return selected_cruise, selected_lowerings

    if parsed_args.cruise_id:
        selected_cruise = cast(SealogRecord | None, get_cruise_by_id(parsed_args.cruise_id))

        if selected_cruise is None:
            logging.error("Cruise %s not found", parsed_args.cruise_id)
            sys.exit(0)

        selected_lowerings = cast(SealogRecords, get_lowerings_by_cruise(selected_cruise['id']))
        return selected_cruise, selected_lowerings

    if parsed_args.lowering_id:
        selected_lowering = cast(SealogRecord | None, get_lowering_by_id(parsed_args.lowering_id))

        if selected_lowering is None:
            logging.error("Lowering %s not found", parsed_args.lowering_id)
            sys.exit(0)

        selected_cruise = cast(SealogRecord | None, get_cruise_by_lowering(selected_lowering['id']))
        if selected_cruise is None:
            logging.error("No cruise found for lowering %s", parsed_args.lowering_id)
            sys.exit(0)

        return selected_cruise, [selected_lowering]

    lowerings = cast(SealogRecords, get_lowerings())
    selected_lowering = lowerings[0] if lowerings else None

    if selected_lowering is None:
        logging.error("There are no lowerings available for export")
        sys.exit(0)

    selected_cruise = cast(SealogRecord | None, get_cruise_by_lowering(selected_lowering['id']))
    if selected_cruise is None:
        logging.error("No cruise found for lowering %s", selected_lowering['lowering_id'])
        sys.exit(0)

    return selected_cruise, [selected_lowering]


if __name__ == '__main__':

    import argparse

    parser = argparse.ArgumentParser(description='Sealog ' + VEHICLE_NAME + ' Data export')
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')
    parser.add_argument('-n', '--no_transfer', action='store_true', default=False,
                        help='build the export but do not push to the data warehouse')
    parser.add_argument('-t', '--transfer_only', action='store_true', default=False,
                        help='only push the previously exported data to the data warehouse')
    parser.add_argument('-c', '--current_cruise', action='store_true', default=False,
                        help='export the data for the most recent cruise')
    parser.add_argument('-L', '--lowering_id',
                        help='export data for the specified lowering (i.e. S0314)')
    parser.add_argument('-C', '--cruise_id',
                        help='export all cruise and lowering data for the specified cruise (i.e. FK200126)')

    parsed_args = parser.parse_args()
    logging.basicConfig(format='%(asctime)-15s %(levelname)s - %(message)s')
    log_levels = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(log_levels))
    logging.getLogger().setLevel(log_levels[parsed_args.verbosity])

    if parsed_args.current_cruise and (parsed_args.lowering_id or parsed_args.cruise_id):
        logging.error("Can not specify current_cruise with a lowering or cruise")
        sys.exit(0)

    if parsed_args.lowering_id and parsed_args.cruise_id:
        logging.error("Can not specify both a lowering and cruise")
        sys.exit(0)

    selected_cruise, selected_lowerings = _select_export_scope(parsed_args)

    if len(selected_lowerings) == 0:
        logging.warning("There are no lowerings for the specified cruise")

    logging.info("Exporting the following data:")
    logging.info("\tCruise: %s", selected_cruise['cruise_id'])
    logging.info(
        "\tLowering(s): %s",
        ', '.join([lowering['lowering_id'] for lowering in selected_lowerings])
        if selected_lowerings else "NONE",
    )

    if parsed_args.transfer_only:
        _push_2_data_warehouse(selected_cruise, selected_lowerings)
        logging.debug("Done")
        sys.exit(0)

    report_title = "Sealog Export Summary Report - %s" % selected_cruise['cruise_id']
    if len(selected_lowerings) == 1:
        report_title += " - %s" % selected_lowerings[0]['lowering_id']

    slack_handler = PooledSlackHandler(
        SLACK_WEBHOOK_URL,
        minimum_level=SLACK_LOG_LEVEL,
        report_title=report_title,
    )
    slack_handler.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger().addHandler(slack_handler)

    success, msg = _verify_source_directories()
    if not success:
        logging.error(msg)
        sys.exit(0)

    if not os.path.isdir(EXPORT_ROOT_DIR):
        logging.error("Cannot find export directory: %s", EXPORT_ROOT_DIR)
        sys.exit(1)

    cruise_source_dir = os.path.join(CRUISES_FILE_PATH, selected_cruise['id'])
    if not os.path.isdir(cruise_source_dir):
        logging.error('Cannot find source directory for cruise: %s', cruise_source_dir)
        sys.exit(1)

    try:
        logging.info("Building cruise-level export directory")
        os.makedirs(os.path.join(EXPORT_ROOT_DIR, selected_cruise['cruise_id']), exist_ok=True)
    except Exception as err:
        logging.error("Could not create cruise export directory")
        logging.debug(str(err))
        sys.exit(1)

    _export_cruise_sealog_data_files(selected_cruise)

    for selected_lowering in selected_lowerings:
        logging.info("Exporting data for lowering: %s", selected_lowering['lowering_id'])

        lowering_source_dir = os.path.join(LOWERINGS_FILE_PATH, selected_lowering['id'])
        if not os.path.isdir(lowering_source_dir):
            logging.error('Cannot find source directory for lowering: %s', lowering_source_dir)
            sys.exit(1)

        lowering_export_dir = os.path.join(
            EXPORT_ROOT_DIR,
            selected_cruise['cruise_id'],
            _export_dir_name(selected_cruise['cruise_id'], selected_lowering['lowering_id']),
        )

        try:
            logging.info("Building lowering-level export directories")
            logging.debug(lowering_export_dir)
            os.makedirs(lowering_export_dir, exist_ok=True)
            os.makedirs(os.path.join(lowering_export_dir, IMAGES_DIRNAME), exist_ok=True)
            os.makedirs(os.path.join(lowering_export_dir, FILES_DIRNAME), exist_ok=True)
        except Exception as err:
            logging.error("Could not create lowering export directories")
            logging.debug(str(err))
            sys.exit(1)

        _export_lowering_sealog_data_files(selected_cruise, selected_lowering)

    if not parsed_args.no_transfer:
        success = _push_2_data_warehouse(selected_cruise, selected_lowerings)
        if success:
            logging.warning(":white_check_mark: Completed export and transfer")
        else:
            logging.error("Export completed but one or more transfers failed, check logs.")
    else:
        logging.warning("Export completed (data transfer skipped).")

    logging.shutdown()
