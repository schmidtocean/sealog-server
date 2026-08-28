#!/usr/bin/env python3
'''
FILE:           sealog_backfill_lowering_stats_emp.py

DESCRIPTION:    Backfill Empress lowering stats from event export aux data.

HOW TO RUN:
                Preview one lowering:
                    ./venv/bin/python misc/sealog_backfill_lowering_stats_emp.py \
                        -L E0010 --dry_run -v

                Backfill one cruise:
                    ./venv/bin/python misc/sealog_backfill_lowering_stats_emp.py -C FKt260503 -v

                Recompute and overwrite existing stats:
                    ./venv/bin/python misc/sealog_backfill_lowering_stats_emp.py \
                        -C FKt260503 --overwrite -v

                If the API token is not configured in settings.py:
                    export SEALOG_API_TOKEN='<token>'
'''

import argparse
import json
import logging
import os
import sys
from typing import Any, cast

import requests

from os.path import dirname, realpath
sys.path.append(dirname(dirname(realpath(__file__))))

from misc.python_sealog.cruises import get_cruise_by_id, get_cruises
from misc.python_sealog.event_exports import get_event_exports_by_lowering
from misc.python_sealog.lowerings import get_lowering_by_id, get_lowerings, get_lowerings_by_cruise
from misc.python_sealog.settings import HEADERS, LOWERINGS_API_PATH
from misc.reporting.sealog_build_cruise_summary_report_emp import event_stats_dict

SealogRecord = dict[str, Any]
SealogRecords = list[SealogRecord]

EMP_REPORT_API_SERVER_URL = "http://10.23.9.25:8200/sealog-server"
SEALOG_API_TOKEN_ENV = "SEALOG_API_TOKEN"
LOGGING_FORMAT = '%(levelname)s: %(message)s'


def _configure_logging(verbosity: int) -> None:
    log_levels = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    selected_level = log_levels[min(verbosity, max(log_levels))]
    logging.basicConfig(format=LOGGING_FORMAT, level=selected_level)


def _api_headers(api_token: str | None = None) -> dict[str, str]:
    headers = HEADERS.copy()
    token = api_token or os.environ.get(SEALOG_API_TOKEN_ENV)

    if token:
        headers["authorization"] = token

    return headers


def _select_lowerings(
    parsed_args: argparse.Namespace,
    api_server_url: str,
    headers: dict[str, str],
) -> SealogRecords:
    if parsed_args.current_cruise:
        cruises = cast(
            SealogRecords,
            get_cruises(api_server_url=api_server_url, headers=headers),
        )
        cruise = cruises[0] if cruises else None
        if cruise is None:
            logging.error("There are no cruises available")
            sys.exit(1)

        return cast(
            SealogRecords,
            get_lowerings_by_cruise(
                cruise["id"], api_server_url=api_server_url, headers=headers
            ) or [],
        )

    if parsed_args.cruise_id:
        cruise = cast(
            SealogRecord | None,
            get_cruise_by_id(
                parsed_args.cruise_id,
                api_server_url=api_server_url,
                headers=headers,
            ),
        )
        if cruise is None:
            logging.error("Cruise %s not found", parsed_args.cruise_id)
            sys.exit(1)

        return cast(
            SealogRecords,
            get_lowerings_by_cruise(
                cruise["id"], api_server_url=api_server_url, headers=headers
            ) or [],
        )

    if parsed_args.lowering_id:
        lowering = cast(
            SealogRecord | None,
            get_lowering_by_id(
                parsed_args.lowering_id,
                api_server_url=api_server_url,
                headers=headers,
            ),
        )
        if lowering is None:
            logging.error("Lowering %s not found", parsed_args.lowering_id)
            sys.exit(1)

        return [lowering]

    if parsed_args.all_lowerings:
        return cast(
            SealogRecords,
            get_lowerings(api_server_url=api_server_url, headers=headers) or [],
        )

    logging.error("Select one scope: --lowering_id, --cruise_id, --current_cruise, or --all")
    sys.exit(1)


def _missing_stat(current_stats: SealogRecord, key: str) -> bool:
    if key not in current_stats:
        return True

    value = current_stats.get(key)
    return value is None or value == '' or (key == 'bounding_box' and value == [])


def _stats_patch(
    lowering: SealogRecord,
    computed_stats: SealogRecord,
    overwrite: bool,
) -> SealogRecord:
    meta = lowering.get('lowering_additional_meta', {})
    meta = dict(meta) if isinstance(meta, dict) else {}
    meta.pop('lowering_files', None)

    current_stats = meta.get('stats', {})
    current_stats = dict(current_stats) if isinstance(current_stats, dict) else {}

    update_stats = {
        key: value
        for key, value in computed_stats.items()
        if overwrite or _missing_stat(current_stats, key)
    }

    if not update_stats:
        return {}

    meta['stats'] = {**current_stats, **update_stats}
    return {'lowering_additional_meta': meta}


def _patch_lowering(
    lowering: SealogRecord,
    payload: SealogRecord,
    api_server_url: str,
    headers: dict[str, str],
) -> None:
    url = f"{api_server_url}{LOWERINGS_API_PATH}/{lowering['id']}"
    response = requests.patch(url, headers=headers, data=json.dumps(payload), timeout=30)
    response.raise_for_status()


def build_lowering_stats_patch(
    lowering: SealogRecord,
    event_exports: SealogRecords,
    overwrite: bool = False,
) -> SealogRecord:
    computed_stats = event_stats_dict(event_exports)
    if not computed_stats:
        return {}

    return _stats_patch(lowering, computed_stats, overwrite)


def backfill_lowering_stats(
    lowering: SealogRecord,
    api_server_url: str,
    headers: dict[str, str],
    overwrite: bool = False,
    dry_run: bool = False,
) -> SealogRecord:
    logging.info("Fetching event exports for %s", lowering['lowering_id'])
    event_exports = cast(
        SealogRecords,
        get_event_exports_by_lowering(
            lowering['id'],
            add_record_ids=True,
            api_server_url=api_server_url,
            headers=headers,
        ) or [],
    )
    payload = build_lowering_stats_patch(lowering, event_exports, overwrite)
    if not payload:
        computed_stats = event_stats_dict(event_exports)
        if computed_stats:
            logging.info("Skipping %s; stats already populated", lowering['lowering_id'])
            return {}
        logging.warning("No depth stats available for %s", lowering['lowering_id'])
        return {}

    logging.info(
        "Updating %s stats: %s",
        lowering['lowering_id'],
        payload['lowering_additional_meta']['stats'],
    )
    if dry_run:
        return payload

    _patch_lowering(lowering, payload, api_server_url, headers)
    return payload


def _scope_count(parsed_args: argparse.Namespace) -> int:
    return sum(
        bool(value)
        for value in (
            parsed_args.lowering_id,
            parsed_args.cruise_id,
            parsed_args.current_cruise,
            parsed_args.all_lowerings,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill Empress lowering stats from Sealog event exports"
    )
    parser.add_argument(
        '-v', '--verbosity', default=0, action='count', help='Increase output verbosity'
    )
    parser.add_argument(
        '--api_server_url', default=EMP_REPORT_API_SERVER_URL, help='Sealog API server URL'
    )
    parser.add_argument('--api_token', help='Sealog API token; prefer SEALOG_API_TOKEN')
    parser.add_argument(
        '-L', '--lowering_id', help='select one lowering/deployment, for example E0010'
    )
    parser.add_argument(
        '-C', '--cruise_id', help='select one cruise, for example FKt260503'
    )
    parser.add_argument(
        '-c', '--current_cruise', action='store_true', default=False,
        help='select the most recent cruise'
    )
    parser.add_argument(
        '--all', dest='all_lowerings', action='store_true', default=False,
        help='select all lowerings'
    )
    parser.add_argument(
        '--overwrite', action='store_true', default=False,
        help='overwrite existing stats values'
    )
    parser.add_argument(
        '--dry_run', action='store_true', default=False,
        help='show updates without PATCHing lowerings'
    )
    parsed_args = parser.parse_args()

    _configure_logging(parsed_args.verbosity)

    if _scope_count(parsed_args) != 1:
        logging.error(
            "Select exactly one scope: --lowering_id, --cruise_id, "
            "--current_cruise, or --all"
        )
        return 1

    headers = _api_headers(parsed_args.api_token)
    lowerings = _select_lowerings(parsed_args, parsed_args.api_server_url, headers)

    logging.info("Selected %s lowering(s)", len(lowerings))
    updated_count = 0
    failed_count = 0

    for lowering in lowerings:
        try:
            if backfill_lowering_stats(
                lowering,
                parsed_args.api_server_url,
                headers,
                parsed_args.overwrite,
                parsed_args.dry_run,
            ):
                updated_count += 1
        except Exception as err:  # pylint: disable=broad-exception-caught
            failed_count += 1
            logging.error(
                "Failed to update %s: %s",
                lowering.get('lowering_id', lowering.get('id')),
                err,
            )

    action = "Would update" if parsed_args.dry_run else "Updated"
    logging.warning(
        "%s %s lowering(s); %s failed", action, updated_count, failed_count
    )

    return 1 if failed_count else 0


if __name__ == '__main__':
    sys.exit(main())
