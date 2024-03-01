#!/usr/bin/env python3
'''
FILE:           sealog_build_cruise_summary_report_sio.py

DESCRIPTION:    Build the cruise summary report.

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    1.0
CREATED:    2021-05-03
REVISION:   2023-05-18

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
'''

import sys
import logging
from io import BytesIO
from datetime import datetime

from reportlab.platypus import Paragraph, PageBreak, Spacer, NextPageTemplate, Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm, mm

from os.path import dirname, realpath
sys.path.append(dirname(dirname(dirname(realpath(__file__)))))

from misc.reporting.sealog_doc_template_Sub import RLDocTemplate
from misc.reporting.sealog_report_builder_Sub import CruiseReportCreator

from misc.python_sealog.cruises import get_cruise_uid_by_id
from misc.python_sealog.settings import API_SERVER_FILE_PATH

PAGE_SIZE = A4
PAGE_WIDTH, PAGE_HEIGHT = PAGE_SIZE
BASE_MARGIN = 5 * mm

AUTHOR = "Schmidt Ocean Institute"
VEHICLE_NAME = 'SuBastian'

class CruiseSummaryReport(CruiseReportCreator): # pylint: disable=too-few-public-methods
    '''
    Class to build the cruise summary report
    '''

    def export_pdf(self):
        '''
        Exports the report in pdf format as a bytes stream
        '''

        report_buffer = BytesIO()

        doc = RLDocTemplate(
            report_buffer,
            pagesize=PAGE_SIZE,
            leftMargin=BASE_MARGIN,
            rightMargin=BASE_MARGIN,
            topMargin=BASE_MARGIN,
            bottomMargin=BASE_MARGIN,
            title="Cruise Summary Report: " + self.cruise_record['cruise_id'],
            subtitle="Remotely Operated Vehicle: " + VEHICLE_NAME,
            author=AUTHOR
        )

        stat_table = self._build_stat_table()

        dive_locations_image = self._build_lowerings_map()
        watch_change_summary_table = self._build_watch_change_summary_table()

        flowables = []

        flowables.append(NextPageTemplate('Normal'))
        flowables.append(Paragraph("<b>Cruise ID:</b> %s" % self.cruise_record['cruise_id'], self.body_text))
        flowables.append(Paragraph("<b>Cruise PI:</b> %s" % self.cruise_record['cruise_additional_meta']['cruise_pi'], self.body_text))
        flowables.append(Paragraph("<b>Summary:</b> %s" % self.cruise_record['cruise_additional_meta']['cruise_description'], self.body_text))
        flowables.append(Paragraph("<b>Location:</b> %s" % self.cruise_record['cruise_location'], self.body_text))
        flowables.append(Paragraph("<b>Ports:</b> %s --> %s" % (self.cruise_record['cruise_additional_meta']['cruise_departure_location'], self.cruise_record['cruise_additional_meta']['cruise_arrival_location']), self.body_text))
        flowables.append(Paragraph("<b>Dates:</b> %s --> %s" % (datetime.fromisoformat(self.cruise_record['start_ts'][:-1]).strftime('%d-%m-%Y'), datetime.fromisoformat(self.cruise_record['stop_ts'][:-1]).strftime('%d-%m-%Y')), self.body_text))
        flowables.append(Paragraph("<b>Dive Stats:</b>", self.body_text))
        flowables.append(Spacer(PAGE_WIDTH, 5 * mm))
        flowables.append(stat_table)
        flowables.append(NextPageTemplate('Normal'))
        flowables.append(PageBreak())

        if dive_locations_image:
            dive_locations = Image(dive_locations_image)
            dive_locations._restrictSize(PAGE_WIDTH - 1 * cm, PAGE_HEIGHT - 7 * cm) # pylint: disable=protected-access
            dive_locations.hAlign = 'CENTER'

            flowables.append(Paragraph("Dive Locations:", self.heading_1))
            flowables.append(Spacer(PAGE_WIDTH, 5 * mm))
            flowables.append(dive_locations)

        if watch_change_summary_table:
            flowables.append(PageBreak())
            flowables.append(Paragraph("Watch Standing Stats:", self.heading_1))
            flowables.append(Spacer(PAGE_WIDTH, 5 * mm))
            flowables.append(watch_change_summary_table)

        logging.info('Building report')

        doc.multiBuild(
            flowables
        )

        pdf_data = report_buffer.getvalue()
        report_buffer.close()

        return pdf_data


# -------------------------------------------------------------------------------------
# Required python code for running the script as a stand-alone utility
# -------------------------------------------------------------------------------------
if __name__ == '__main__':

    import argparse
    import os

    parser = argparse.ArgumentParser(description='Build Cruise Summary Report for %s' % VEHICLE_NAME)
    parser.add_argument('-v', '--verbosity', dest='verbosity',
                        default=0, action='count',
                        help='Increase output verbosity')
    parser.add_argument('-o','--output_dir', help='output directory to save report')
    parser.add_argument('cruise_id', help='cruise_id to build report for (i.e. FKt230417).')

    parsed_args = parser.parse_args()

    ############################
    # Set up logging before we do any other argument parsing (so that we
    # can log problems with argument parsing).

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    # verify lowering exists
    cruise_uid = get_cruise_uid_by_id(parsed_args.cruise_id)

    if cruise_uid is None:
        logging.error("No cruise found for cruise_id: %s", parsed_args.cruise_id)
        sys.exit(0)

    try:
        summary_report = CruiseSummaryReport(cruise_uid)
        OUTPUT_PATH = parsed_args.output_dir if parsed_args.output_dir else os.path.join(API_SERVER_FILE_PATH, 'cruises', cruise_uid)
        REPORT_FILENAME = parsed_args.cruise_id + '_Cruise_Summary_Report_' + VEHICLE_NAME + '.pdf'

        try:
            with open(os.path.join(OUTPUT_PATH, REPORT_FILENAME), 'wb') as file:
                file.write(summary_report.export_pdf())

        except Exception as error:
            logging.error("Unable to build report")
            logging.error(str(error))
    except KeyboardInterrupt:
        logging.warning('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0) # pylint: disable=protected-access