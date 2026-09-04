#!/usr/bin/env python3
'''
FILE:           sealog_build_lowering_summary_report_emp.py

DESCRIPTION:    Minimal Empress lowering summary PDF reports
'''

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
from pathlib import Path
from typing import Any

from misc.reporting.sealog_build_cruise_summary_report_emp import (
    STAGE_DEFINITIONS,
    VEHICLE_NAME,
    SealogRecord,
    build_lowering_metrics,
    event_milestone_records,
    format_float_list,
    format_optional_float,
    get_stage_boundary,
    lowering_with_event_milestones,
    parse_timestamp,
    render_template,
    write_pdf_report,
)

EVENT_EXCLUDE_VALUES = {
    'ASNAP', 'FRAME GRAB', 'FRAME_GRAB', 'FRAMEGRAB', 'WATCH CHANGE', 'WATCH_CHANGE',
}
EVENT_GROUP_ORDER = ('Vehicle', 'Problem', 'Other')
MILESTONE_LABELS = {
    'lowering_deployment': 'Deployment',
    'lowering_key_pulled': 'Mission Key Pulled',
    'lowering_in_water': 'In Water',
    'lowering_descent_initiated': 'Descent Initiated',
    'lowering_descending': 'Descent Initiated',
    'lowering_reached_survey_depth': 'Reached Survey Depth',
    'lowering_on_bottom': 'Reached Survey Depth',
    'lowering_ascent_initiated': 'Ascent Initiated',
    'lowering_leaving_survey_depth': 'Leaving Survey Depth',
    'lowering_off_bottom': 'Leaving Survey Depth',
    'lowering_vehicle_on_surface': 'Vehicle on Surface',
    'lowering_on_surface': 'Vehicle on Surface',
    'lowering_recovery': 'Recovery',
    'lowering_out_of_water': 'Out of Water',
    'lowering_aborted': 'Aborted',
}
LOWERING_START_MILESTONE = 'lowering_start'
LOWERING_STOP_MILESTONE = 'lowering_stop'
LOWERING_START_LABEL = 'Deployment Start'
LOWERING_STOP_LABEL = 'On Deck'


@dataclass(frozen=True)
class TrackPoint:
    '''
    One timestamped navigation sample
    '''

    ts: datetime
    latitude: float | None
    longitude: float | None
    depth: float | None
    altitude: float | None


@dataclass(frozen=True)
class PlotAssets:
    '''
    Lowering plot image assets
    '''

    route_uri: str | None
    depth_uri: str | None
    route_points: int
    depth_points: int


def write_lowering_summary_report(
    cruise: SealogRecord,
    lowering: SealogRecord,
    output_dir: str | Path,
    event_exports: list[SealogRecord] | None = None,
) -> Path:
    '''
    Write a minimal PDF report for one Empress lowering
    '''

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cruise_id = str(cruise.get('cruise_id', 'cruise'))
    lowering_id = str(lowering.get('lowering_id', 'lowering'))
    report_path = (
        output_path / f"{cruise_id}_{lowering_id}_{VEHICLE_NAME}_Deployment_Summary.pdf"
    )
    plots = _build_plot_assets(
        cruise_id, lowering_id, event_exports or [], output_path / 'assets',
    )

    write_pdf_report(
        _render_lowering_summary_html(cruise, lowering, plots, event_exports or []), report_path,
    )

    return report_path


def _render_lowering_summary_html(
    cruise: SealogRecord,
    lowering: SealogRecord,
    plots: PlotAssets,
    event_exports: list[SealogRecord],
) -> str:
    report_lowering = lowering_with_event_milestones(lowering, event_exports)
    metrics = build_lowering_metrics(report_lowering, event_exports)
    meta = report_lowering.get('lowering_additional_meta', {})
    meta = meta if isinstance(meta, dict) else {}
    track_points = _track_points(event_exports)
    minimum_distance_point = _minimum_distance_point(track_points)

    return render_template(
        'emp_lowering_summary.html.j2',
        cruise=cruise,
        lowering=lowering,
        lowering_meta=meta,
        metrics=metrics,
        generated_ts=datetime.now(timezone.utc),
        stage_definitions=STAGE_DEFINITIONS,
        milestones=_actual_milestones(report_lowering, meta, track_points, event_exports),
        vehicle_name=VEHICLE_NAME,
        max_depth=format_optional_float(metrics.max_depth),
        minimum_distance_to_seabed=_format_minimum_distance_to_seabed(minimum_distance_point),
        survey_depth_track_distance=_format_survey_depth_track_distance(
            report_lowering,
            track_points,
        ),
        bounding_box=format_float_list(metrics.bounding_box),
        plots=plots,
        event_groups=_event_groups(event_exports),
    )


def _build_plot_assets(
    cruise_id: str,
    lowering_id: str,
    event_exports: list[SealogRecord],
    assets_dir: Path,
) -> PlotAssets:
    points = _track_points(event_exports)
    route_points = [
        point for point in points if point.latitude is not None and point.longitude is not None
    ]
    depth_points = [point for point in points if point.depth is not None]

    route_path = assets_dir / f'{cruise_id}_{lowering_id}_route.png'
    depth_path = assets_dir / f'{cruise_id}_{lowering_id}_depth.png'

    route_uri = None
    depth_uri = None

    if route_points:
        try:
            _write_route_plot(route_points, route_path)
            route_uri = route_path.resolve().as_uri()
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning("Unable to build route plot for %s", lowering_id)
            logging.debug(str(err))

    if depth_points:
        try:
            _write_depth_plot(depth_points, depth_path)
            depth_uri = depth_path.resolve().as_uri()
        except Exception as err:  # pylint: disable=broad-exception-caught
            logging.warning("Unable to build depth plot for %s", lowering_id)
            logging.debug(str(err))

    return PlotAssets(
        route_uri=route_uri,
        depth_uri=depth_uri,
        route_points=len(route_points),
        depth_points=len(depth_points),
    )


def _actual_milestones(
    lowering: SealogRecord,
    meta: SealogRecord,
    track_points: list[TrackPoint],
    event_exports: list[SealogRecord] | None = None,
) -> list[SealogRecord]:
    milestone_map: dict[str, SealogRecord] = {}
    milestone_order: list[str] = []

    def add_milestone(
        name: str,
        value: Any,
        label: str | None = None,
        replace: bool = False,
    ) -> None:
        timestamp = parse_timestamp(value)
        if timestamp is None:
            return

        display_name = label or MILESTONE_LABELS.get(name, name)
        milestone_key = display_name.casefold()

        if milestone_key in milestone_map and not replace:
            return

        if milestone_key not in milestone_map:
            milestone_order.append(milestone_key)

        milestone_map[milestone_key] = {
            'name': display_name,
            'key': name,
            'ts': timestamp,
            'raw_value': value,
        }

    add_milestone(
        LOWERING_START_MILESTONE,
        lowering.get('start_ts'),
        label=LOWERING_START_LABEL,
    )

    milestones = meta.get('milestones', {})
    if isinstance(milestones, dict):
        for name, value in milestones.items():
            add_milestone(str(name), value, replace=True)

    event_records = event_milestone_records(event_exports or [])
    _warn_duplicate_event_milestones(event_records)

    for record in event_records:
        name = record.get('name')
        if not isinstance(name, str):
            continue

        add_milestone(name, record.get('raw_value') or record.get('ts'))

    add_milestone(
        LOWERING_STOP_MILESTONE,
        lowering.get('stop_ts'),
        label=LOWERING_STOP_LABEL,
    )

    output = [milestone_map[name] for name in milestone_order if name in milestone_map]

    return _milestone_rows_with_nav(output, track_points)


def _warn_duplicate_event_milestones(event_records: list[SealogRecord]) -> None:
    '''
    Warn when the event history contains the same milestone more than once
    '''

    records_by_type: dict[str, list[SealogRecord]] = {}

    for record in event_records:
        name = str(record.get('name', ''))
        display_name = MILESTONE_LABELS.get(name, name)
        records_by_type.setdefault(display_name.casefold(), []).append(record)

    for records in records_by_type.values():
        if len(records) > 1:
            name = str(records[0]['name'])
            logging.warning(
                "Multiple milestone events found for %s: %s",
                MILESTONE_LABELS.get(name, name),
                ', '.join(str(record['raw_value']) for record in records),
            )


def _milestone_rows_with_nav(
    milestones: list[SealogRecord],
    track_points: list[TrackPoint],
) -> list[SealogRecord]:
    output = []

    for milestone in milestones:
        timestamp = milestone.get('ts')
        timestamp = timestamp if isinstance(timestamp, datetime) else None
        point = _nearest_track_point(timestamp, track_points)
        output.append({
            **milestone,
            'latitude': point.latitude if point else None,
            'longitude': point.longitude if point else None,
            'depth': point.depth if point else None,
        })

    return output


def _milestone_sort_key(milestone: SealogRecord) -> tuple[int, datetime, str]:
    timestamp = milestone.get('ts')
    if isinstance(timestamp, datetime):
        return (0, timestamp, str(milestone.get('name', '')).lower())

    return (1, datetime.max.replace(tzinfo=timezone.utc), str(milestone.get('name', '')).lower())


def _nearest_track_point(timestamp: datetime | None, points: list[TrackPoint]) -> TrackPoint | None:
    if timestamp is None or not points:
        return None

    return min(points, key=lambda point: abs((point.ts - timestamp).total_seconds()))


def _minimum_distance_point(points: list[TrackPoint]) -> TrackPoint | None:
    altitude_points = [point for point in points if point.altitude is not None]
    if not altitude_points:
        return None

    return min(altitude_points, key=lambda point: point.altitude or 0)


def _format_minimum_distance_to_seabed(point: TrackPoint | None) -> str:
    if point is None or point.altitude is None:
        return ''

    return f'{format_optional_float(point.altitude)}m @ {point.ts:%Y-%m-%d %H:%M:%SZ}'


def _format_survey_depth_track_distance(
    lowering: SealogRecord,
    points: list[TrackPoint],
) -> str:
    survey_depth_stage = next(
        (stage for stage in STAGE_DEFINITIONS if stage.label == 'Survey Depth'),
        None,
    )
    if survey_depth_stage is None:
        return ''

    start = get_stage_boundary(
        lowering,
        survey_depth_stage.start,
        survey_depth_stage.start_fallback,
    )
    stop = get_stage_boundary(lowering, survey_depth_stage.stop, survey_depth_stage.stop_fallback)
    if start is None or stop is None:
        return ''

    return _format_track_distance(_total_track_distance_m(points, start, stop))


def _total_track_distance_m(
    points: list[TrackPoint],
    start: datetime | None = None,
    stop: datetime | None = None,
) -> float | None:
    route_points = [
        point
        for point in points
        if point.latitude is not None and point.longitude is not None
        and (start is None or point.ts >= start)
        and (stop is None or point.ts <= stop)
    ]
    if len(route_points) < 2:
        return None

    return sum(
        _distance_m(previous, current)
        for previous, current in zip(route_points, route_points[1:])
    )


def _distance_m(first: TrackPoint, second: TrackPoint) -> float:
    radius_m = 6371000
    first_lat = math.radians(first.latitude or 0)
    second_lat = math.radians(second.latitude or 0)
    delta_lat = math.radians((second.latitude or 0) - (first.latitude or 0))
    delta_lon = math.radians((second.longitude or 0) - (first.longitude or 0))

    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_m * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _format_track_distance(distance_m: float | None) -> str:
    if distance_m is None:
        return ''

    if distance_m < 1000:
        return f'{distance_m:.0f}m'

    return f'{distance_m / 1000:.2f}km'


def _event_groups(event_exports: list[SealogRecord] | None) -> list[SealogRecord]:
    grouped_events: dict[str, list[SealogRecord]] = {label: [] for label in EVENT_GROUP_ORDER}

    for event in event_exports or []:
        report_event = _report_event(event)
        if report_event is None:
            continue

        grouped_events[_event_group(event)].append(report_event)

    return [
        {
            'label': label,
            'events': grouped_events[label],
            'count': len(grouped_events[label]),
        }
        for label in EVENT_GROUP_ORDER
    ]


def _report_event(event: SealogRecord) -> SealogRecord | None:
    event_value = str(event.get('event_value', '')).strip()
    if event_value.upper() in EVENT_EXCLUDE_VALUES:
        return None

    timestamp = parse_timestamp(event.get('ts'))

    return {
        'ts': timestamp,
        'event_value': event_value,
        'author': str(event.get('event_author', '')).strip(),
        'mission_line': _event_mission_line(event),
        'details': _event_details(event),
    }


def _event_mission_line(event: SealogRecord) -> str:
    values = _preferred_aux_values(event.get('aux_data'), ('mission_line',))
    mission_line = _aux_value(values, 'mission_line')

    return '' if mission_line in (None, '') else str(mission_line).strip()


def _event_group(event: SealogRecord) -> str:
    event_text = _event_search_text(event)

    if 'problem' in event_text:
        return 'Problem'

    if str(event.get('event_value', '')).strip().upper() == 'VEHICLE':
        return 'Vehicle'

    if 'vehicle' in event_text:
        return 'Vehicle'

    return 'Other'


def _event_search_text(event: SealogRecord) -> str:
    parts = [
        str(event.get('event_value', '')),
        str(event.get('event_free_text', '')),
    ]

    for option in event.get('event_options', []):
        if not isinstance(option, dict):
            continue

        parts.append(str(option.get('event_option_name', '')))
        parts.append(str(option.get('event_option_value', '')))

    return ' '.join(parts).lower()


def _event_details(event: SealogRecord) -> str:
    details = []

    free_text = str(event.get('event_free_text', '')).strip()
    if free_text:
        details.append(free_text)

    for option in event.get('event_options', []):
        if not isinstance(option, dict):
            continue

        name = str(option.get('event_option_name', '')).strip()
        value = str(option.get('event_option_value', '')).strip()
        if name and value:
            details.append(f'{name}: {value}')
        elif value:
            details.append(value)

    return '; '.join(details)


def _track_points(event_exports: list[SealogRecord]) -> list[TrackPoint]:
    points = []

    for event in event_exports:
        timestamp = _parse_event_timestamp(event)
        if timestamp is None:
            continue

        nav_values = _preferred_aux_values(event.get('aux_data'), ('latitude', 'longitude'))
        depth_values = _preferred_aux_values(event.get('aux_data'), ('depth',))

        latitude = _bounded_float(_aux_value(nav_values, 'latitude'), -90, 90)
        longitude = _bounded_float(_aux_value(nav_values, 'longitude'), -180, 180)
        depth = _positive_float(_aux_value(depth_values, 'depth'))
        altitude = _positive_float(_aux_value(depth_values, 'altitude'))

        if latitude is None and longitude is None and depth is None and altitude is None:
            continue

        points.append(TrackPoint(timestamp, latitude, longitude, depth, altitude))

    return sorted(points, key=lambda point: point.ts)


def _preferred_aux_values(aux_data: Any, names: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(aux_data, list):
        return {}

    fallback_values = {}

    for aux_record in aux_data:
        if not isinstance(aux_record, dict):
            continue

        values = _aux_values(aux_record)
        if not all(_aux_value(values, name) is not None for name in names):
            continue

        source = str(aux_record.get('data_source', '')).lower()
        if 'vehicle' in source:
            return values

        if not fallback_values:
            fallback_values = values

    return fallback_values


def _aux_values(aux_record: SealogRecord) -> dict[str, Any]:
    values = {}

    for item in aux_record.get('data_array', []):
        if not isinstance(item, dict):
            continue

        data_name = item.get('data_name')
        if data_name is not None:
            values[str(data_name).lower()] = item.get('data_value')

    return values


def _aux_value(values: dict[str, Any], name: str) -> Any:
    return values.get(name.lower())


def _parse_event_timestamp(event: SealogRecord) -> datetime | None:
    timestamp = event.get('ts')
    if not isinstance(timestamp, str):
        return None

    try:
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        return None

    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bounded_float(value: Any, minimum: float, maximum: float) -> float | None:
    parsed = _float(value)
    if parsed is None or parsed < minimum or parsed > maximum:
        return None

    return parsed


def _positive_float(value: Any) -> float | None:
    parsed = _float(value)
    if parsed is None or parsed < 0:
        return None

    return parsed


def _float(value: Any) -> float | None:
    if value in (None, ''):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_route_plot(points: list[TrackPoint], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pyplot = _pyplot()

    longitudes = [point.longitude for point in points if point.longitude is not None]
    latitudes = [point.latitude for point in points if point.latitude is not None]

    figure, axis = pyplot.subplots(figsize=(6.8, 4.2), dpi=160)
    axis.plot(longitudes, latitudes, color='#1f78b4', linewidth=1.8)
    axis.scatter(longitudes[0], latitudes[0], color='#2a9d55', s=34, zorder=3, label='Start')
    axis.scatter(longitudes[-1], latitudes[-1], color='#c24132', s=34, zorder=3, label='End')
    axis.set_title('AUV Route')
    axis.set_xlabel('Longitude')
    axis.set_ylabel('Latitude')
    axis.grid(True, color='#d7dce2', linewidth=0.6)
    axis.legend(loc='best', frameon=False)
    axis.set_aspect('equal', adjustable='datalim')
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches='tight')
    pyplot.close(figure)


def _write_depth_plot(points: list[TrackPoint], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pyplot = _pyplot()

    timestamps = [point.ts for point in points if point.depth is not None]
    depths = [point.depth for point in points if point.depth is not None]
    bottom_timestamps = [
        point.ts
        for point in points
        if point.depth is not None and point.altitude is not None
    ]
    bottom_vehicle_depths = [
        point.depth
        for point in points
        if point.depth is not None and point.altitude is not None
    ]
    bottom_depths = [
        point.depth + point.altitude
        for point in points
        if point.depth is not None and point.altitude is not None
    ]
    near_bottom_timestamps = [
        point.ts
        for point in points
        if (
            point.depth is not None
            and point.altitude is not None
            and point.altitude < 1
        )
    ]
    near_bottom_depths = [
        point.depth
        for point in points
        if (
            point.depth is not None
            and point.altitude is not None
            and point.altitude < 1
        )
    ]

    figure, axis = pyplot.subplots(figsize=(6.8, 3.2), dpi=160)
    axis.plot(timestamps, depths, color='#7746a3', linewidth=1.6, label='Depth')
    if bottom_timestamps:
        axis.fill_between(
            bottom_timestamps,
            bottom_vehicle_depths,
            bottom_depths,
            color='#2f3b32',
            alpha=0.28,
            linewidth=0,
        )
        axis.plot(
            bottom_timestamps,
            bottom_depths,
            color='#151a17',
            linewidth=1.2,
            label='Altimeter',
        )
    if near_bottom_timestamps:
        axis.scatter(
            near_bottom_timestamps,
            near_bottom_depths,
            color='#c24132',
            s=14,
            zorder=5,
            label='Altimeter < 1 m',
        )
    axis.fill_between(timestamps, depths, color='#7746a3', alpha=0.12)
    axis.set_title('Depth Profile')
    axis.set_xlabel('Time (UTC)')
    axis.set_ylabel('Depth (m)')
    axis.grid(True, color='#d7dce2', linewidth=0.6)
    axis.legend(loc='best', frameon=False)
    axis.invert_yaxis()
    figure.autofmt_xdate(rotation=25)
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches='tight')
    pyplot.close(figure)


def _pyplot():
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use('Agg')
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    return pyplot
