'''Regression tests for Empress milestone casing in report data.'''

import copy
import unittest

from misc.reporting import sealog_build_cruise_summary_report_emp as cruise_report
from misc.reporting import sealog_build_lowering_summary_report_emp as lowering_report


def timestamp(hour):
    '''Return a fixed UTC timestamp for a test hour.'''
    return f'2026-10-01T{hour:02}:00:00Z'


def event(name, hour):
    '''Build an exported milestone event.'''
    return {
        'ts': timestamp(hour),
        'event_options': [{'event_option_name': 'milestone', 'event_option_value': name}],
    }


class EmpMilestoneReportsTest(unittest.TestCase):
    '''Exercise case compatibility without rendering PDFs.'''

    def test_event_extraction_keeps_first_timestamp_across_case_variants(self):
        '''Case variants are one milestone and display in sentence case.'''
        events = [event('In Water', 3), event(' in WATER ', 1), event('in water', 2)]
        events[1]['event_options'][0]['event_option_name'] = ' MILESTONE '
        self.assertEqual(cruise_report.event_milestones_dict(events), {'in water': timestamp(1)})
        self.assertEqual(
            [record['name'] for record in cruise_report.event_milestone_records(events)],
            ['In water'] * 3,
        )

    def test_stage_durations_accept_old_sentence_and_lowercase_values(self):
        '''Historical and newly formatted events produce the same durations.'''
        names = [
            'Pre-dive', 'Deployment', 'In Water', 'Descent Initiated', 'Reached Survey Depth',
            'Leaving Survey Depth', 'Vehicle on Surface', 'Out of Water', 'Mission Key Inserted',
        ]
        lowering = {'start_ts': timestamp(0), 'stop_ts': timestamp(8)}
        for transform in (str, str.capitalize, str.lower, str.swapcase):
            with self.subTest(transform=transform.__name__):
                events = [event(transform(name), hour) for hour, name in enumerate(names)]
                report_lowering = cruise_report.lowering_with_event_milestones(lowering, events)
                self.assertEqual(
                    cruise_report.build_lowering_metrics(report_lowering).stage_durations,
                    {
                        'Deck to Deck': 18000, 'Deployment': 7200, 'Descent': 3600,
                        'Survey Depth': 3600, 'Ascent': 3600, 'Recovery': 7200,
                    },
                )

    def test_stored_legacy_and_lowering_timestamps_keep_precedence(self):
        '''Stored values beat events; legacy aliases and start/stop fields still win.'''
        lowering = {
            'start_ts': timestamp(0),
            'stop_ts': timestamp(7),
            'lowering_additional_meta': {'milestones': {
                'Deployment': timestamp(2),
                'Reached Survey Depth': timestamp(3),
                'LOWERING_ON_BOTTOM': timestamp(4),
                'lowering_reached_survey_depth': timestamp(5),
                'PRE-DIVE': timestamp(1),
                'Mission Key Inserted': timestamp(6),
            }},
        }
        original = copy.deepcopy(lowering)
        events = [event('deployment', 1), event('reached survey depth', 2)]
        merged = cruise_report.lowering_with_event_milestones(lowering, events)
        milestones = merged['lowering_additional_meta']['milestones']
        self.assertEqual(milestones['deployment'], timestamp(2))
        self.assertEqual(milestones['reached survey depth'], timestamp(4))
        self.assertEqual(milestones['pre-dive'], timestamp(0))
        self.assertEqual(milestones['mission key inserted'], timestamp(7))
        self.assertEqual(lowering, original)

        # pylint: disable=protected-access
        rows = lowering_report._actual_milestones(
            merged, merged['lowering_additional_meta'], [], events,
        )
        self.assertEqual(
            {row['name']: row['raw_value'] for row in rows},
            {
                'Pre-dive': timestamp(0), 'Deployment': timestamp(2),
                'Reached survey depth': timestamp(4), 'Mission key inserted': timestamp(7),
            },
        )

    def test_mixed_stored_case_and_old_aliases_keep_survey_distance(self):
        '''Metadata and historical boundary names work without event fallback.'''
        lowering = {'lowering_additional_meta': {'milestones': {
            'initial DESCENT': timestamp(2),
            'at DEPTH': timestamp(3),
            ' LEAVING survey depth ': timestamp(4),
        }}}
        metrics = cruise_report.build_lowering_metrics(lowering)
        self.assertEqual(metrics.stage_durations['Descent'], 3600)
        self.assertEqual(metrics.stage_durations['Survey Depth'], 3600)
        points = [
            lowering_report.TrackPoint(
                cruise_report.parse_timestamp(timestamp(hour)), 0.0, longitude, None, None,
            )
            for hour, longitude in [(2, -2.0), (3, 0.0), (4, 1.0), (5, 3.0)]
        ]
        # pylint: disable=protected-access
        self.assertEqual(
            lowering_report._format_survey_depth_track_distance(lowering, points), '111.19km',
        )

    def test_empty_stored_milestones_do_not_hide_event_timestamps(self):
        '''Null stored values fall through to events; start/stop match Deck to Deck.'''
        lowering = {
            'start_ts': timestamp(0), 'stop_ts': timestamp(8),
            'lowering_additional_meta': {'milestones': {'In water': None, 'Out of water': ''}},
        }
        events = [event('In water', 2), event('Out of water', 6)]
        metrics = cruise_report.build_lowering_metrics(
            cruise_report.lowering_with_event_milestones(lowering, events),
        )
        self.assertEqual(metrics.stage_durations['Deck to Deck'], 4 * 3600)
        self.assertEqual(metrics.start_ts, cruise_report.parse_timestamp(timestamp(2)))
        self.assertEqual(metrics.stop_ts, cruise_report.parse_timestamp(timestamp(6)))

    def test_abort_milestone_is_listed_once(self):
        '''auto_actions stores both names for an abort; the report shows one.'''
        lowering = {'lowering_additional_meta': {'milestones': {
            'Dive aborted': timestamp(3), 'lowering_aborted': timestamp(3),
        }}}
        merged = cruise_report.lowering_with_event_milestones(lowering, [event('Dive aborted', 3)])
        # pylint: disable=protected-access
        rows = lowering_report._actual_milestones(
            merged, merged['lowering_additional_meta'], [], [event('Dive aborted', 3)],
        )
        self.assertEqual([row['name'] for row in rows if 'abort' in row['name'].lower()],
                         ['Dive aborted'])


if __name__ == '__main__':
    unittest.main()
