"""Milestone casing regressions, with every API interaction mocked."""

from contextlib import ExitStack
from copy import deepcopy
import importlib
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Load the checked-in defaults, never an operator's local API credentials.
SETTINGS = ModuleType('misc.python_sealog.settings')
SETTINGS.__dict__.update(runpy.run_path(str(ROOT / 'misc/python_sealog/settings.py.dist')))
with patch.dict(sys.modules, {'misc.python_sealog.settings': SETTINGS}):
    EMP = importlib.import_module('misc.sealog_auto_actions_emp')
    SUB = importlib.import_module('misc.sealog_auto_actions_sub')
    SYNC = importlib.import_module('misc.sealog_lowering_sync')

TIMESTAMP = '2026-10-08T10:00:00.000Z'
EARLIER = '2026-10-08T09:00:00.000Z'


def event(value, option_name='MILESTONE'):
    return {
        'id': 'event-1', 'ts': TIMESTAMP, 'event_value': 'VEHICLE',
        'event_options': [{'event_option_name': option_name, 'event_option_value': value}],
    }


class MilestoneConsumerTests(unittest.TestCase):
    def test_lowering_sync_subscribes_to_new_and_updated_events(self):
        self.assertEqual(SYNC.SUBSCRIPTION_PATHS, (
            '/ws/status/newEvents',
            '/ws/status/updateEvents',
        ))

    def handle(self, module, value, existing=None, option_name='MILESTONE', watch_events=None):
        lowering = {
            'id': 'lowering-1',
            'lowering_additional_meta': {'milestones': deepcopy(existing or {})},
        }
        with ExitStack() as mocks:
            mocks.enter_context(patch.object(
                module.requests.sessions.Session, 'request',
                side_effect=AssertionError('Tests must not contact a live API'),
            ))
            mocks.enter_context(patch.object(
                module, 'get_lowering_by_event', return_value=lowering,
            ))
            watches_mock = watch_events or [{'id': 'watch-1', 'ts': EARLIER}]
            mocks.enter_context(patch.object(
                module, 'get_events_by_lowering', return_value=watches_mock, create=True,
            ))
            self.get_events = mocks.enter_context(patch.object(
                module, 'get_events', return_value=watches_mock, create=True,
            ))
            mocks.enter_context(patch.object(
                module, 'get_custom_var_uid_by_name', return_value='asnap-1',
            ))
            status = mocks.enter_context(patch.object(module, 'set_custom_var'))
            http_patch = mocks.enter_context(patch.object(module.requests, 'patch'))
            update = mocks.enter_context(patch.object(module, 'update_lowering', create=True))
            module._handle_vehicle_event(event(value, option_name))
        updates = [json.loads(call.kwargs['data']) for call in http_patch.call_args_list
                   if call.args[0].endswith('/lowerings/lowering-1')]
        updates.extend(call.args[1] for call in update.call_args_list)
        watches = [json.loads(call.kwargs['data']) for call in http_patch.call_args_list
                   if call.args[0].endswith('/events/watch-1')]
        return updates, watches, status

    def test_emp_water_casing_controls_asnap_watch_and_legacy_timestamps(self):
        for label, status, alias in (
            ('In water', 'On', 'lowering_in_water'),
            ('Out of water', 'Off', 'lowering_out_of_water'),
        ):
            variants = (label, label.title(), label.upper(), label.lower())
            option_names = ('milestone', 'Milestone', 'MILESTONE', 'mIlEsToNe')
            for value, option_name in zip(variants, option_names):
                with self.subTest(value=value, option_name=option_name):
                    updates, watches, calls = self.handle(EMP, value, option_name=option_name)
                    calls.assert_called_once_with('asnap-1', status)
                    self.assertEqual(watches, [])
                    self.assertEqual(updates[0]['lowering_additional_meta']['milestones'], {
                        label: TIMESTAMP, alias: TIMESTAMP,
                    })

    def test_lowercase_emp_start_stop_and_survey_depth(self):
        for label, field in (('pre-dive', 'start_ts'), ('mission key inserted', 'stop_ts')):
            with self.subTest(label=label):
                updates, _, _ = self.handle(EMP, label)
                self.assertEqual(updates[0][field], TIMESTAMP)
                self.assertEqual(updates[0]['lowering_additional_meta']['milestones'], {
                    label.capitalize(): TIMESTAMP,
                })
        updates, _, _ = self.handle(EMP, 'reached survey depth')
        self.assertEqual(updates[0]['lowering_additional_meta']['milestones'], {
            'Reached survey depth': TIMESTAMP, 'lowering_on_bottom': TIMESTAMP,
        })

    def test_every_checked_in_emp_milestone_template_updates_the_lowering(self):
        templates = json.loads((ROOT / 'init_data/system_templates_emp.json').read_text())
        values = [option['event_option_default_value'] for template in templates
                  for option in template['event_options']
                  if option['event_option_name'].casefold() == 'milestone']
        self.assertIn('Dive aborted', values)
        for value in values:
            with self.subTest(value=value):
                updates, _, _ = self.handle(EMP, value)
                milestones = updates[0]['lowering_additional_meta']['milestones']
                expected = [value.capitalize()] + EMP.MILESTONE_LOOKUP.get(value.capitalize(), [])
                self.assertEqual(milestones, dict.fromkeys(expected, TIMESTAMP))
        updates, _, _ = self.handle(EMP, 'Dive aborted')
        self.assertIn('lowering_aborted', updates[0]['lowering_additional_meta']['milestones'])

    def test_pre_dive_pulls_in_the_watch_logged_just_before_it(self):
        # E0021: the first watch was logged 11 s before Pre-dive, outside the deployment.
        pre_dive = '2026-10-18T17:02:18.945Z'
        watch_events = [{'id': 'watch-0', 'ts': '2026-10-18T16:50:00.000Z'},
                        {'id': 'watch-1', 'ts': '2026-10-18T17:02:07.000Z'}]
        with patch.object(sys.modules[__name__], 'TIMESTAMP', pre_dive):
            _, watches, _ = self.handle(EMP, 'Pre-dive', watch_events=watch_events)
        self.assertEqual(watches, [{'ts': pre_dive}])
        self.assertEqual(self.get_events.call_args.kwargs, {
            'event_filter': ['WATCH CHANGE'],
            'start_ts': '2026-10-18T16:47:18.945000Z', 'stop_ts': pre_dive,
        })

    def test_pre_dive_leaves_a_watch_already_at_pre_dive(self):
        _, watches, _ = self.handle(
            EMP, 'Pre-dive', watch_events=[{'id': 'watch-1', 'ts': TIMESTAMP}],
        )
        self.assertEqual(watches, [])

    def test_existing_emp_keys_are_reused_and_recorded_timestamps_preserved(self):
        for label in ('Reached Survey Depth', 'REACHED SURVEY DEPTH'):
            for previous in (EARLIER, None, ''):
                with self.subTest(label=label, previous=previous):
                    updates, _, _ = self.handle(EMP, 'Reached survey depth', {
                        label: previous, 'LOWERING_ON_BOTTOM': previous,
                    })
                    expected = (
                        {label: previous, 'LOWERING_ON_BOTTOM': previous} if previous else
                        {'Reached survey depth': TIMESTAMP, 'lowering_on_bottom': TIMESTAMP}
                    )
                    self.assertEqual(updates[0]['lowering_additional_meta']['milestones'], expected)

    def test_sub_watch_start_stop_asnap_and_aliases_ignore_case(self):
        updates, watches, _ = self.handle(SUB, 'OFF DECK')
        self.assertEqual(updates[0]['start_ts'], TIMESTAMP)
        self.assertEqual(watches, [{'ts': TIMESTAMP}])
        updates, _, _ = self.handle(SUB, 'on deck')
        self.assertEqual(updates[0]['stop_ts'], TIMESTAMP)
        for label, status in (('IN WATER', 'On'), ('out of water', 'Off')):
            _, _, calls = self.handle(SUB, label)
            calls.assert_called_once_with('asnap-1', status)
        for existing in ({}, {'lowering_on_bottom': EARLIER}):
            updates, _, _ = self.handle(SUB, 'ON BOTTOM', existing)
            self.assertEqual(updates[0]['lowering_additional_meta']['milestones'],
                             existing or {'lowering_on_bottom': TIMESTAMP})

    def test_fkt_forwarding_retains_case_insensitive_milestone_matching(self):
        for instance, label, status in (
            ('emp', 'IN WATER', 'Deployed'), ('emp', 'out of water', 'Recovered'),
            ('sub', 'OFF DECK', 'Deployed'), ('sub', 'on deck', 'Recovered'),
        ):
            with self.subTest(instance=instance, label=label):
                self.assertEqual(SYNC.destination_status(instance, event(label)), status)


if __name__ == '__main__':
    unittest.main()
