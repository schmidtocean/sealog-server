#!/usr/bin/env python3
'''
FILE:           sealog_vehicle_data_export_Sub.py

DESCRIPTION:    This script exports all the data for a given lowering, creates
                all the reports for that lowering, and pushes the data to the
                OpenVDM data directory for that lowering.

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
import glob
import tempfile
from datetime import datetime

from os.path import dirname, realpath
sys.path.append(dirname(dirname(realpath(__file__))))

from misc.reporting.sealog_build_lowering_vehicle_report import LoweringVehicleReport
from misc.reporting.sealog_build_lowering_summary_report import LoweringSummaryReport
from misc.reporting.sealog_build_cruise_summary_report_Sub import CruiseSummaryReport
from misc.filecrop_utility import FileCropUtility
from misc.combine_csv_files import combine_files_at_1hz
from misc.python_sealog.event_templates import get_event_templates
from misc.python_sealog.event_exports import get_event_exports_by_lowering
from misc.python_sealog.event_aux_data import get_event_aux_data_by_lowering
from misc.python_sealog.events import get_events_by_lowering
from misc.python_sealog.misc import get_framegrab_list_by_lowering
from misc.python_sealog.lowerings import get_lowerings, get_lowering_by_id, get_lowerings_by_cruise
from misc.python_sealog.cruises import get_cruises, get_cruise_by_id, get_cruise_by_lowering
from misc.python_sealog.event_exports import get_event_export
from misc.python_sealog.settings import API_SERVER_FILE_PATH
from misc.slack_sealog.slack_logger import PooledSlackHandler
from misc.slack_sealog.settings import SLACK_WEBHOOK_URL, SLACK_LOG_LEVEL
from misc.base_data_exporter import SealogDataExporter

# from misc.reporting.sealog_build_lowering_sample_report_soi import LoweringSampleReport

EXPORT_ROOT_DIR = '/data/sealog-Sub-export'
VEHICLE_NAME = 'SuBastian'
EXPORT_IMAGES = True
IMAGE_DATASOURCES = ['vehicleRealtimeFramegrabberData']

CRUISEDATA_LOCAL_MOUNT = '/mnt/CruiseData'
OPENVDM_VEHICLE_DIR = 'Vehicles/' + VEHICLE_NAME
SEALOG_DIR = 'Sealog'
CREATE_DEST_DIR = False

NAV_DATASOURCE = 'vehicleRealtimeNavData'
CROPPED_DATA_DIR = '/data/sealog_Sub_cropped_data'
OPENRVDAS_SOURCE_DIR = 'Falkor_too/Raw/OpenRVDAS'
OPENRVDAS_DEST_DIR = 'OpenRVDAS'
POST_CRUISE_REPORT_DIR = 'Vehicles/SuBastian'

DATA_FILES_DEFS = [
    {'source_regex': '*sb_ctd_sbe49-*', 'output_prefix': 'sb_ctd_sbe49_'},
    {'source_regex': '*sb_ctd_sbe49_depth_corr-*', 'output_prefix': 'sb_ctd_sbe49_depth_corr_'},
    {'source_regex': '*sb_ctd_uvsvx-*', 'output_prefix': 'sb_ctd_uvsvx_'},
    {'source_regex': '*sb_ctd_uvsvx_depth_corr-*', 'output_prefix': 'sb_ctd_uvsvx_depth_corr_'},
    {'source_regex': '*sb_hightemp_pt100-*', 'output_prefix': 'sb_hightemp_pt100_'},
    {'source_regex': '*sb_mech_comps-*', 'output_prefix': 'sb_mech_comps_'},
    {'source_regex': '*sb_mech_valves-*', 'output_prefix': 'sb_mech_valves_'},
    {'source_regex': '*sb_miniips-*', 'output_prefix': 'sb_miniips_'},
    {'source_regex': '*sb_miniips_depth_corr-*', 'output_prefix': 'sb_miniips_depth_corr_'},
    {'source_regex': '*sb_oxygen-*', 'output_prefix': 'sb_oxygen_'},
    {'source_regex': '*sb_oxygen_corr_sbe49-*', 'output_prefix': 'sb_oxygen_corr_sbe49_'},
    {'source_regex': '*sb_oxygen_corr_uvsvx-*', 'output_prefix': 'sb_oxygen_corr_uvsvx_'},
    {'source_regex': '*sb_ph-*', 'output_prefix': 'sb_ph_'},
    {'source_regex': '*sb_ph_corr_sbe49-*', 'output_prefix': 'sb_ph_corr_sbe49_'},
    {'source_regex': '*sb_paro-*', 'output_prefix': 'sb_paro_'},
    {'source_regex': '*sb_paro_depth_corr-*', 'output_prefix': 'sb_paro_depth_corr_'},
    {'source_regex': '*sb_sprint-*', 'output_prefix': 'sb_sprint_'},
    {'source_regex': '*sb_sprint_depth_corr-*', 'output_prefix': 'sb_sprint_depth_corr_'},
    {'source_regex': '*sb_sprint_diag-*', 'output_prefix': 'sb_sprint_diag_'},
    {'source_regex': '*usbl_alpha_gga-*', 'output_prefix': 'usbl_alpha_gga_'},
    {'source_regex': '*usbl_bravo_gga-*', 'output_prefix': 'usbl_bravo_gga_'},
    {'source_regex': '*usbl_hotel_gga-*', 'output_prefix': 'usbl_hotel_gga_'},
]


class SubVehicleDataExporter(SealogDataExporter):
    """Exports lowering-level event data, reports, and files for SuBastian."""

    REPORTS_DIRNAME = 'Reports'

    def __init__(self, name, export_root_dir, export_images=True, image_datasources=None):
        super().__init__(name, export_root_dir, export_images, image_datasources)
        self.lowerings_file_path = os.path.join(API_SERVER_FILE_PATH, 'lowerings')

    def _cruise_file_prefix(self, cruise):
        return f"{cruise['cruise_id']}_{self.name}"

    def _lowering_file_prefix(self, cruise, lowering):
        return f"{cruise['cruise_id']}_{lowering['lowering_id']}"

    def _build_lowering_name(self, cruise, lowering):
        """Build the SOI lowering directory name used in OpenVDM."""
        lowering_id = lowering['lowering_id']
        if lowering_id[1:].isnumeric():
            return f"{cruise['cruise_id']}_{lowering_id}"
        return lowering_id

    def verify_source_directories(self, cruise, lowerings=None):
        """Verify that all required source directories exist."""
        ok, err_msg = super().verify_source_directories(cruise)
        if not ok:
            return ok, err_msg
        lowerings = lowerings or []
        checks = [
            (self.images_file_path, "cannot find images file path"),
            (self.lowerings_file_path, "cannot find lowerings file path"),
            (CRUISEDATA_LOCAL_MOUNT, "cannot find local CruiseData mount"),
        ] + [
            (os.path.join(self.lowerings_file_path, lo['id']),
             f"cannot find source directory for lowering: {lo['lowering_id']}")
            for lo in lowerings
        ]
        for path, message in checks:
            if not os.path.isdir(path):
                return False, message
        return True, 'success'

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
                'description': 'Event Templates',
                'path': lambda c, dirs: os.path.join(
                    dirs['cruise'], self._cruise_file_prefix(c) + '_eventTemplates.json'
                ),
                'data_fn': lambda c: json.dumps(get_event_templates()),
            },
        ]

    def _get_lowering_export_tasks(self):
        return [
            {
                'description': 'Lowering Record',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_loweringRecord.json'
                ),
                'data_fn': json.dumps,
            },
            {
                'description': 'Events (json)',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_eventOnlyExport.json'
                ),
                'data_fn': lambda lo: json.dumps(get_events_by_lowering(lo['id'])),
            },
            {
                'description': 'Events (csv)',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_eventOnlyExport.csv'
                ),
                'data_fn': lambda lo: get_events_by_lowering(lo['id'], 'csv'),
            },
            {
                'description': 'Aux Data',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_auxDataExport.json'
                ),
                'data_fn': lambda lo: json.dumps(get_event_aux_data_by_lowering(lo['id'])),
            },
            {
                'description': 'Events with Aux Data (json)',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_sealogExport.json'
                ),
                'data_fn': lambda lo: json.dumps(
                    get_event_exports_by_lowering(lo['id'], add_record_ids=True)
                ),
            },
            {
                'description': 'Events with Aux Data (csv)',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_sealogExport.csv'
                ),
                'data_fn': lambda lo: get_event_exports_by_lowering(
                    lo['id'], 'csv', add_record_ids=True
                ),
            },
            {
                'description': 'Event Templates',
                'path': lambda c, lo, dirs: os.path.join(
                    dirs['lowering'],
                    self._lowering_file_prefix(c, lo) + '_eventTemplates.json'
                ),
                'data_fn': lambda lo: json.dumps(get_event_templates()),
            },
        ]

    def _export_images(self, lowering, lowering_dir):
        logging.info("Exporting Images")
        framegrab_list = get_framegrab_list_by_lowering(lowering['id'], self.image_datasources)
        images_dir = os.path.join(lowering_dir, self.IMAGES_DIRNAME)

        expected_images = {os.path.basename(filepath) for filepath in framegrab_list}
        for filename in set(os.listdir(images_dir)) - expected_images:
            try:
                logging.info("Deleting: %s", filename)
                os.remove(os.path.join(images_dir, filename))
            except OSError as err:
                logging.error("Could not delete stale image %s: %s", filename, err)

        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', delete=False) as file:
            for framegrab in framegrab_list:
                file.write(os.path.basename(framegrab) + '\n')
            framegrab_list_path = file.name

        logging.info("Starting rclone transfer for images")
        try:
            subprocess.run(
                ['rclone', 'copy', '--transfers=16', '--checkers=16',
                 '--size-only', '--progress', '--no-traverse',
                 '--files-from', framegrab_list_path,
                 os.path.join(self.images_file_path, ''), images_dir],
                check=True, capture_output=False, text=True)
        except subprocess.CalledProcessError as err:
            logging.error("Failed to sync images with exit code %s", err.returncode)
            raise
        finally:
            try:
                os.remove(framegrab_list_path)
            except FileNotFoundError:
                pass

    def _export_lowering_openrvdas_data_files(self, cruise, lowering):
        """Crop and export the OpenRVDAS files for the given cruise/lowering."""
        logging.info("Exporting lowering-level OpenRVDAS data files")

        fcu = FileCropUtility(
            datetime.strptime(lowering['start_ts'], '%Y-%m-%dT%H:%M:%S.%fZ'),
            datetime.strptime(lowering['stop_ts'], '%Y-%m-%dT%H:%M:%S.%fZ'),
            header=True)

        for data_file_def in DATA_FILES_DEFS:
            source_files = glob.glob(os.path.join(
                CRUISEDATA_LOCAL_MOUNT, cruise['cruise_id'],
                OPENRVDAS_SOURCE_DIR, data_file_def['source_regex']))
            logging.debug('Source files: \n\t%s', '\n\t'.join(source_files))

            destination_file = os.path.join(
                CROPPED_DATA_DIR, cruise['cruise_id'],
                self._build_lowering_name(cruise, lowering),
                OPENRVDAS_DEST_DIR,
                f"{cruise['cruise_id']}_{data_file_def['output_prefix']}"
                f"{lowering['lowering_id']}.txt")
            logging.debug('Destination file: %s', destination_file)

            try:
                culled_files = fcu.cull_files(source_files)
                if culled_files:
                    with open(destination_file, 'w', encoding='utf-8') as file:
                        for line in fcu.crop_file_data(culled_files):
                            file.write(line)
                    logging.info(
                        "Data exported for instrument: %s", data_file_def['output_prefix'])
                else:
                    logging.warning(
                        "No files containing data in the specified range for : %s",
                        data_file_def['output_prefix'])
            except Exception as err:  # pylint: disable=broad-except
                logging.warning("Could not create cropped data file: %s", destination_file)
                logging.debug(str(err))

    def _export_combined_csv_file(self, cruise, lowering, cropped_dir):
        """Combine the lowering's cropped OpenRVDAS files into a 1 Hz CSV."""
        logging.info("Building combined OpenRVDAS 1 Hz CSV file")

        source_files = glob.glob(os.path.join(cropped_dir, '*.txt'))
        destination_file = os.path.join(
            cropped_dir,
            f"{cruise['cruise_id']}_combined_1Hz_{lowering['lowering_id']}.csv"
        )

        if not source_files:
            logging.warning(
                "No cropped OpenRVDAS files found for lowering %s; skipping combined CSV",
                lowering['lowering_id'])
            return

        try:
            combine_files_at_1hz(source_files, destination_file)
        except Exception as err:  # pylint: disable=broad-except
            logging.error("Combining OpenRVDAS files failed: %s", err)

    def _build_lowering_marker(self, lowering):
        """Return a CSV line with the on_bottom position for the lowering, or None."""
        try:
            on_bottom_event = list(filter(
                lambda event: event['ts'] == lowering['lowering_additional_meta'][
                    'milestones']['lowering_on_bottom'],
                get_events_by_lowering(lowering['id'])))[0]
        except Exception as err:  # pylint: disable=broad-except
            logging.warning(
                'Could not find on_bottom milestone for lowering %s', lowering['lowering_id'])
            logging.debug(str(err))
            return None

        try:
            on_bottom_export = get_event_export(on_bottom_event['id'])
            nav = list(filter(
                lambda aux: aux['data_source'] == NAV_DATASOURCE,
                on_bottom_export['aux_data']))[0]
            lat = list(filter(
                lambda d: d['data_name'] == 'latitude', nav['data_array']))[0]['data_value']
            lon = list(filter(
                lambda d: d['data_name'] == 'longitude', nav['data_array']))[0]['data_value']
            depth = list(filter(
                lambda d: d['data_name'] == 'depth', nav['data_array']))[0]['data_value']
            return f"{lowering['lowering_id']},{lat},{lon},{depth * -1}"
        except Exception as err:  # pylint: disable=broad-except
            logging.warning(
                'Could not extract nav data from on_bottom event for lowering: %s',
                lowering['lowering_id'])
            logging.debug(str(err))
        return None

    def _export_lowering_markers_file(self, cruise):
        """Export a CSV file containing on_bottom positions for all lowerings in the cruise."""
        logging.info("Exporting lowering markers file")

        markers = [
            m for m in (
                self._build_lowering_marker(lo)
                for lo in get_lowerings_by_cruise(cruise['id'])
            ) if m is not None
        ]

        filename = f"{self.name}_{cruise['cruise_id']}_loweringMarkers.txt"
        dest_filepath = os.path.join(
            API_SERVER_FILE_PATH, 'cruises', cruise['id'], filename)
        try:
            with open(dest_filepath, 'w', encoding='utf-8') as file:
                for marker in markers:
                    file.write(marker + '\r\n')
        except OSError as err:
            logging.error('could not create data file: %s', dest_filepath)
            logging.debug(str(err))

    def _build_cruise_reports(self, cruise):
        """Build the cruise-level PDF report."""
        logging.info("Building cruise reports")
        report_dest_dir = os.path.join(API_SERVER_FILE_PATH, 'cruises', cruise['id'])
        report_filename = f"{cruise['cruise_id']}_{self.name}_Cruise_Summary_Report.pdf"
        logging.info("Building Cruise Summary Report: %s", report_filename)
        try:
            with open(os.path.join(report_dest_dir, report_filename), 'wb') as file:
                file.write(CruiseSummaryReport(cruise['id']).export_pdf())
        except Exception as err:  # pylint: disable=broad-except
            logging.error("Unable to build report")
            logging.debug(str(err))

    def _build_lowering_reports(self, cruise, lowering):
        """Build the lowering summary and vehicle PDF reports."""
        logging.info("Building lowering reports")
        report_dest_dir = os.path.join(API_SERVER_FILE_PATH, 'lowerings', lowering['id'])
        prefix = self._lowering_file_prefix(cruise, lowering)

        summary_filename = f"{prefix}_Summary_Report.pdf"
        logging.info("Building Lowering Summary Report: %s", summary_filename)
        try:
            with open(os.path.join(report_dest_dir, summary_filename), 'wb') as file:
                file.write(LoweringSummaryReport(lowering['id']).export_pdf())
        except Exception as err:  # pylint: disable=broad-except
            logging.error("Unable to build report")
            logging.error(str(err))

        vehicle_filename = f"{prefix}_Vehicle_Report.pdf"
        logging.info("Building Lowering Vehicle Report: %s", vehicle_filename)
        try:
            with open(os.path.join(report_dest_dir, vehicle_filename), 'wb') as file:
                file.write(LoweringVehicleReport(lowering['id']).export_pdf())
        except Exception as err:  # pylint: disable=broad-except
            logging.error("Unable to build report")
            logging.error(str(err))

    def push_to_data_warehouse(self, cruise, lowerings):  # pylint: disable=too-many-statements
        """Push exported files to the OpenVDM cruise data warehouse."""
        cruise_source_dir = os.path.join(self.export_root_dir, cruise['cruise_id'])
        if not os.path.isdir(cruise_source_dir):
            logging.error('Exported directory for cruise data not found')
            return False

        logging.info("Syncing cruise reports")
        try:
            subprocess.run(
                ['rsync', '-avi', '--progress', '--delete',
                 '--include=*.pdf', '--exclude=*',
                 os.path.join(API_SERVER_FILE_PATH, 'cruises', cruise['id'], ''),
                 os.path.join(cruise_source_dir, self.REPORTS_DIRNAME)],
                check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to sync cruise reports: %s", e.stderr)
            return False

        warehouse_cruise_dir = os.path.join(
            CRUISEDATA_LOCAL_MOUNT, cruise['cruise_id'],
            POST_CRUISE_REPORT_DIR, '')

        try:
            subprocess.run(
                ['rclone', 'sync', '--transfers=16', '--checkers=16',
                 '--size-only', '--progress', '--include=*.pdf',
                 os.path.join(cruise_source_dir, self.REPORTS_DIRNAME, ''),
                 warehouse_cruise_dir],
                check=True, capture_output=False, text=True)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to sync cruise reports to warehouse with exit code %s",
                          e.returncode)
            return False

        logging.info("Syncing cruise files")
        try:
            subprocess.run(
                ['rclone', 'sync', '--transfers=16', '--checkers=16',
                 '--size-only', '--progress', '--exclude=*.pdf',
                 os.path.join(cruise_source_dir, self.FILES_DIRNAME, ''),
                 warehouse_cruise_dir],
                check=True, capture_output=False, text=True)
        except subprocess.CalledProcessError as e:
            logging.error("Failed to sync cruise files to warehouse with exit code %s",
                          e.returncode)
            return False

        for lowering in lowerings:
            lowering_name = self._build_lowering_name(cruise, lowering)
            lowering_source_dir = os.path.join(cruise_source_dir, lowering_name)

            try:
                subprocess.run(
                    ['rsync', '-avi', '--progress', '--delete',
                     '--include=*_Report.pdf', '--exclude=*',
                     os.path.join(API_SERVER_FILE_PATH, 'lowerings', lowering['id'], ''),
                     os.path.join(lowering_source_dir, self.REPORTS_DIRNAME)],
                    check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                logging.error("Failed to sync reports for lowering %s: %s",
                              lowering['lowering_id'], e.stderr)
                continue

            try:
                subprocess.run(
                    ['rsync', '-avi', '--progress', '--delete',
                     '--exclude=*_Report.pdf',
                     os.path.join(API_SERVER_FILE_PATH, 'lowerings', lowering['id'], ''),
                     os.path.join(lowering_source_dir, self.FILES_DIRNAME)],
                    check=True, capture_output=True, text=True)
            except subprocess.CalledProcessError as e:
                logging.error("Failed to sync user files for lowering %s: %s",
                              lowering['lowering_id'], e.stderr)
                continue

            if not os.path.isdir(lowering_source_dir):
                logging.error('Exported directory for lowering data not found')
                continue

            warehouse_lowering_sealog = os.path.join(
                CRUISEDATA_LOCAL_MOUNT, cruise['cruise_id'],
                OPENVDM_VEHICLE_DIR, lowering_name, SEALOG_DIR, '')

            if CREATE_DEST_DIR:
                try:
                    os.makedirs(warehouse_lowering_sealog, exist_ok=True)
                except OSError as e:
                    logging.error("Failed to create sealog directory for lowering %s: %s",
                                  lowering['lowering_id'], e)
                    continue

            try:
                subprocess.run(
                    ['rclone', 'sync', '--transfers=16', '--checkers=16',
                     '--size-only', '--progress',
                     os.path.join(lowering_source_dir, ''),
                     warehouse_lowering_sealog],
                    check=True, capture_output=False, text=True)
            except subprocess.CalledProcessError as e:
                logging.error("Failed to sync sealog data for lowering %s with exit code %s",
                              lowering['lowering_id'], e.returncode)
                continue

            cropped_source_dir = os.path.join(
                CROPPED_DATA_DIR, cruise['cruise_id'], lowering_name, OPENRVDAS_DEST_DIR)
            if not os.path.isdir(cropped_source_dir):
                logging.error('Cropped data directory for lowering data not found')
                continue

            warehouse_lowering_openrvdas = os.path.join(
                CRUISEDATA_LOCAL_MOUNT, cruise['cruise_id'],
                OPENVDM_VEHICLE_DIR, lowering_name, OPENRVDAS_DEST_DIR, '')

            if CREATE_DEST_DIR:
                try:
                    os.makedirs(warehouse_lowering_openrvdas, exist_ok=True)
                except OSError as e:
                    logging.error("Failed to create OpenRVDAS directory for lowering %s: %s",
                                  lowering['lowering_id'], e)
                    continue

            try:
                subprocess.run(
                    ['rclone', 'sync', '--transfers=16', '--checkers=16',
                     '--size-only', '--progress',
                     os.path.join(cropped_source_dir, ''),
                     warehouse_lowering_openrvdas],
                    check=True, capture_output=False, text=True)
            except subprocess.CalledProcessError as e:
                logging.error("Failed to sync OpenRVDAS data for lowering %s with exit code %s",
                              lowering['lowering_id'], e.returncode)
                continue

        return True

    def export_cruise(self, cruise):
        """Export cruise-level data files and build cruise reports."""
        logging.info("Exporting data for cruise %s", cruise['cruise_id'])

        cruise_dir = os.path.join(self.export_root_dir, cruise['cruise_id'])
        dirs = {
            'cruise': cruise_dir,
            'files': os.path.join(cruise_dir, self.FILES_DIRNAME),
            'reports': os.path.join(cruise_dir, self.REPORTS_DIRNAME),
        }
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

        self._build_cruise_reports(cruise)
        self._export_cruise_files(cruise, cruise_dir)

    def export_lowering(self, cruise, lowering):
        """Export all data for the given lowering."""
        logging.info("Exporting data for lowering %s", lowering['lowering_id'])

        lowering_dir = os.path.join(
            self.export_root_dir, cruise['cruise_id'],
            self._build_lowering_name(cruise, lowering))
        cropped_dir = os.path.join(
            CROPPED_DATA_DIR, cruise['cruise_id'],
            self._build_lowering_name(cruise, lowering), OPENRVDAS_DEST_DIR)
        dirs = {
            'cruise': os.path.join(self.export_root_dir, cruise['cruise_id']),
            'lowering': lowering_dir,
            'files': os.path.join(lowering_dir, self.FILES_DIRNAME),
            'reports': os.path.join(lowering_dir, self.REPORTS_DIRNAME),
            'images': os.path.join(lowering_dir, self.IMAGES_DIRNAME),
            'cropped': cropped_dir,
        }
        self._build_export_directories(dirs)

        self._export_lowering_openrvdas_data_files(cruise, lowering)
        self._export_combined_csv_file(cruise, lowering, cropped_dir)

        for task in self._get_lowering_export_tasks():
            filepath = task['path'](cruise, lowering, dirs)
            if filepath is not None:
                try:
                    content = task['data_fn'](lowering)
                except Exception as err:  # pylint: disable=broad-except
                    logging.error("Failed to export %s: %s", task['description'], err)
                    continue
                self._write_file(filepath, content, task['description'])

        if self.export_images:
            self._export_images(lowering, lowering_dir)

        self._build_lowering_reports(cruise, lowering)


if __name__ == '__main__':

    import argparse

    exporter = SubVehicleDataExporter(
        name=VEHICLE_NAME,
        export_root_dir=EXPORT_ROOT_DIR,
        export_images=EXPORT_IMAGES,
        image_datasources=IMAGE_DATASOURCES,
    )

    parser = argparse.ArgumentParser(description='Sealog ' + VEHICLE_NAME + ' Data export')
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')
    parser.add_argument('-n', '--no_transfer', action='store_true', default=False,
                        help='build reports and export data but do not push to data warehouse')
    parser.add_argument('-t', '--transfer_only', action='store_true', default=False,
                        help='only push the exported data to data warehouse')
    parser.add_argument('-c', '--current_cruise', action='store_true', default=False,
                        help='export the data for the most recent cruise')
    parser.add_argument('-L', '--lowering_id',
                        help='export data for the specified lowering (i.e. S0314)')
    parser.add_argument('-C', '--cruise_id',
                        help='export all cruise and lowering data for the specified cruise')

    parsed_args = parser.parse_args()

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    selection_count = sum((
        parsed_args.current_cruise,
        parsed_args.lowering_id is not None,
        parsed_args.cruise_id is not None,
    ))
    if selection_count > 1:
        logging.error(
            "Specify only one of -c/--current_cruise, -L/--lowering_id, or -C/--cruise_id")
        sys.exit(0)

    selected_cruise = None
    selected_lowerings = []

    if parsed_args.current_cruise:
        selected_cruise = next(iter(get_cruises()), None)
        if selected_cruise is None:
            logging.error("There are no cruises available for export")
            sys.exit(0)
        selected_lowerings = get_lowerings_by_cruise(selected_cruise['id'])

    elif parsed_args.cruise_id:
        selected_cruise = get_cruise_by_id(parsed_args.cruise_id)
        if selected_cruise is None:
            logging.error("Cruise %s not found", parsed_args.cruise_id)
            sys.exit(0)
        selected_lowerings = get_lowerings_by_cruise(selected_cruise['id'])

    elif parsed_args.lowering_id:
        selected_lowerings = [get_lowering_by_id(parsed_args.lowering_id)]
        if selected_lowerings[0] is None:
            logging.error("Lowering %s not found", parsed_args.lowering_id)
            sys.exit(0)
        selected_cruise = get_cruise_by_lowering(selected_lowerings[0]['id'])

    else:
        selected_lowerings = [next(iter(get_lowerings()), None)]
        if selected_lowerings[0] is None:
            logging.error("There are no lowerings available for export")
            sys.exit(0)
        selected_cruise = get_cruise_by_lowering(selected_lowerings[0]['id'])

    if selected_cruise is None:
        logging.error("There is no cruise for the specified lowering")
        sys.exit(0)

    if not selected_lowerings:
        logging.warning("There are no lowerings for the specified cruise")

    logging.info("Exporting the following data:")
    logging.info("\tCruise: %s", selected_cruise['cruise_id'])
    LOWERING_IDS = ', '.join(
        lo['lowering_id'] for lo in selected_lowerings
    ) if selected_lowerings else "\t NONE"
    logging.info("\tLowering(s): %s", LOWERING_IDS)

    if parsed_args.transfer_only:
        exporter.push_to_data_warehouse(selected_cruise, selected_lowerings)
        logging.debug("Done")
        sys.exit(0)

    report_title = f"Sealog Export Summary Report - {selected_cruise['cruise_id']}"
    if selected_lowerings and len(selected_lowerings) == 1:
        report_title += f" - {selected_lowerings[0]['lowering_id']}"

    if SLACK_WEBHOOK_URL is not None:
        slack_handler = PooledSlackHandler(
            SLACK_WEBHOOK_URL,
            minimum_level=SLACK_LOG_LEVEL,
            report_title=report_title
        )
        slack_handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(slack_handler)

    success, msg = exporter.verify_source_directories(selected_cruise, selected_lowerings)
    if not success:
        logging.error(msg)
        sys.exit(0)

    if not os.path.isdir(EXPORT_ROOT_DIR):
        logging.error("Cannot find export directory: %s", EXPORT_ROOT_DIR)
        sys.exit(1)

    exporter.export_cruise(selected_cruise)

    for selected_lowering in selected_lowerings:
        exporter.export_lowering(selected_cruise, selected_lowering)

    if not parsed_args.no_transfer:
        transfer_success = exporter.push_to_data_warehouse(
            selected_cruise, selected_lowerings)
        if transfer_success:
            logging.warning(":white_check_mark: Completed export and transfer")
        else:
            logging.error(
                "Export completed but one or more transfers failed, check logs.")
    else:
        logging.warning("Export completed (data transfer skipped).")

    logging.debug("Done")
