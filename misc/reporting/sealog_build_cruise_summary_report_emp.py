#!/usr/bin/env python3
'''
FILE:           sealog_build_cruise_summary_report_emp.py

DESCRIPTION:    Minimal Empress cruise metrics PDF reports.

                Reports are template-first and rendered to PDF. This keeps
                the workflow lightweight, source-controllable, and independent
                from the legacy PDF reporting stack.
'''

from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

VEHICLE_NAME = 'Empress'
TEMPLATE_DIR = Path(__file__).parent / 'templates'

SealogRecord = dict[str, Any]
Seconds = int | None

MILESTONE_OPTION_NAME = 'milestone'


@dataclass(frozen=True)
class StageDefinition:
    '''
    Time span definition for Empress operations
    '''

    label: str
    start: tuple[str, ...]
    stop: tuple[str, ...]
    start_fallback: str | None = None
    stop_fallback: str | None = None


@dataclass(frozen=True)
class LoweringMetrics:
    '''
    Computed metrics for one lowering
    '''

    lowering_id: str
    location: str
    start_ts: datetime | None
    stop_ts: datetime | None
    stage_durations: dict[str, Seconds]
    max_depth: float | None
    bounding_box: list[float]


@dataclass(frozen=True)
class DiveTrack:
    '''
    One dive route plotted from event navigation data
    '''

    lowering_id: str
    points: list[tuple[float, float]]


@dataclass(frozen=True)
class CruiseMapAssets:
    '''
    Cruise-level plot image assets
    '''

    dive_locations_uri: str | None
    dive_count: int


STAGE_DEFINITIONS = (
    StageDefinition(
        'Deck to Deck',
        ('Deployment',),
        ('Mission Key Inserted',),
        start_fallback='start_ts',
        stop_fallback='stop_ts',
    ),
    StageDefinition(
        'Deployment',
        ('Deployment',),
        ('Descent Initiated', 'Initial Descent', 'lowering_descending'),
    ),
    StageDefinition(
        'Descent',
        ('Descent Initiated', 'Initial Descent', 'lowering_descending'),
        ('Reached Survey Depth', 'At Depth', 'lowering_on_bottom'),
    ),
    StageDefinition(
        'Survey Depth',
        ('Reached Survey Depth', 'At Depth', 'lowering_on_bottom'),
        ('Leaving Survey Depth', 'lowering_off_bottom'),
    ),
    StageDefinition(
        'Ascent',
        ('Leaving Survey Depth', 'lowering_off_bottom'),
        ('Vehicle on Surface', 'lowering_on_surface'),
    ),
    StageDefinition(
        'Recovery',
        ('Vehicle on Surface', 'lowering_on_surface', 'Recovery'),
        ('Mission Key Inserted',),
        stop_fallback='stop_ts',
    ),
)


def lowering_with_event_milestones(
    lowering: SealogRecord,
    event_exports: list[SealogRecord] | None,
) -> SealogRecord:
    '''
    Return a lowering record with event milestones filling missing record milestones
    '''

    event_milestones = event_milestones_dict(event_exports or [])
    if not event_milestones:
        return lowering

    output = dict(lowering)
    meta = output.get('lowering_additional_meta', {})
    meta = dict(meta) if isinstance(meta, dict) else {}
    milestones = meta.get('milestones', {})
    milestones = dict(milestones) if isinstance(milestones, dict) else {}
    meta['milestones'] = {**event_milestones, **milestones}
    output['lowering_additional_meta'] = meta

    return output


def event_milestone_records(event_exports: list[SealogRecord]) -> list[SealogRecord]:
    '''
    Extract milestone rows from exported Sealog events
    '''

    records = []

    for event in event_exports:
        milestone = event_milestone_value(event)
        timestamp = parse_timestamp(event.get('ts'))
        if milestone is None or timestamp is None:
            continue

        records.append({
            'name': milestone,
            'ts': timestamp,
            'raw_value': event.get('ts'),
        })

    return sorted(records, key=_milestone_event_sort_key)


def event_milestones_dict(event_exports: list[SealogRecord]) -> dict[str, Any]:
    '''
    Extract first-seen milestone timestamps from exported Sealog events
    '''

    milestones = {}

    for record in event_milestone_records(event_exports):
        milestones.setdefault(str(record['name']), record['raw_value'])

    return milestones


def event_milestone_value(event: SealogRecord) -> str | None:
    '''
    Return the milestone event option value for an event, or None
    '''

    for option in event.get('event_options', []):
        if not isinstance(option, dict):
            continue

        if option.get('event_option_name') != MILESTONE_OPTION_NAME:
            continue

        value = str(option.get('event_option_value', '')).strip()
        return value or None

    return None


def _milestone_event_sort_key(record: SealogRecord) -> tuple[datetime, str]:
    timestamp = record.get('ts')
    if isinstance(timestamp, datetime):
        return (timestamp, str(record.get('name', '')).lower())

    return (datetime.max.replace(tzinfo=timezone.utc), str(record.get('name', '')).lower())


def parse_timestamp(value: Any) -> datetime | None:
    '''
    Parse a Sealog ISO timestamp as UTC
    '''

    if isinstance(value, datetime):
        if value.tzinfo:
            return value.astimezone(timezone.utc)
        return value.replace(tzinfo=timezone.utc)

    if not isinstance(value, str) or value == '':
        return None

    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None

    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_timestamp(value: datetime | None) -> str:
    '''
    Format a timestamp for reports
    '''

    if value is None:
        return ''

    return value.strftime('%Y-%m-%d %H:%M:%SZ')


def format_duration(seconds: Seconds) -> str:
    '''
    Format a duration as total hours, minutes, and seconds
    '''

    if seconds is None:
        return ''

    hours, remainder = divmod(max(seconds, 0), 3600)
    minutes, secs = divmod(remainder, 60)

    return f'{hours:02d}:{minutes:02d}:{secs:02d}'


def format_optional_float(value: float | None) -> str:
    '''
    Format optional floating point values for reports
    '''

    return '' if value is None else f'{value:g}'


def format_float_list(values: list[float]) -> str:
    '''
    Format a list of floats for reports
    '''

    return ', '.join(f'{value:g}' for value in values)


def get_stage_boundary(
    lowering: SealogRecord,
    names: tuple[str, ...],
    fallback_key: str | None = None,
) -> datetime | None:
    '''
    Return the first matching milestone timestamp, with optional lowering field fallback
    '''

    milestones = _get_meta_dict(lowering, 'milestones')

    for name in names:
        timestamp = parse_timestamp(milestones.get(name))
        if timestamp is not None:
            return timestamp

    if fallback_key is not None:
        return parse_timestamp(lowering.get(fallback_key))

    return None


def build_lowering_metrics(lowering: SealogRecord) -> LoweringMetrics:
    '''
    Build Empress stage metrics for one lowering
    '''

    stage_durations: dict[str, Seconds] = {}

    for stage in STAGE_DEFINITIONS:
        start = get_stage_boundary(lowering, stage.start, stage.start_fallback)
        stop = get_stage_boundary(lowering, stage.stop, stage.stop_fallback)
        stage_durations[stage.label] = _duration_seconds(start, stop)

    stats = _get_meta_dict(lowering, 'stats')

    return LoweringMetrics(
        lowering_id=str(lowering.get('lowering_id', '')),
        location=str(lowering.get('lowering_location', '')),
        start_ts=get_stage_boundary(lowering, ('Deployment',), 'start_ts'),
        stop_ts=get_stage_boundary(lowering, ('Mission Key Inserted',), 'stop_ts'),
        stage_durations=stage_durations,
        max_depth=_optional_float(stats.get('max_depth')),
        bounding_box=_float_list(stats.get('bounding_box')),
    )


def write_cruise_metrics_report(
    cruise: SealogRecord,
    lowerings: list[SealogRecord],
    output_dir: str | Path,
    event_exports_by_lowering: dict[str, list[SealogRecord]] | None = None,
) -> list[Path]:
    '''
    Write cruise-level Empress metrics as PDF
    '''

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cruise_id = str(cruise.get('cruise_id', 'cruise'))
    event_exports_by_lowering = event_exports_by_lowering or {}
    report_lowerings = [
        lowering_with_event_milestones(
            lowering,
            _event_exports_for_lowering(lowering, event_exports_by_lowering),
        )
        for lowering in lowerings
    ]
    metrics = [build_lowering_metrics(lowering) for lowering in report_lowerings]
    map_assets = _build_cruise_map_assets(
        cruise_id,
        lowerings,
        event_exports_by_lowering,
        output_path / 'assets',
    )

    pdf_path = output_path / f'{cruise_id}_{VEHICLE_NAME}_Cruise_Metrics.pdf'
    html = _render_cruise_metrics_html(cruise, metrics, map_assets)
    write_pdf_report(html, pdf_path)

    return [pdf_path]


def _render_cruise_metrics_html(
    cruise: SealogRecord,
    metrics: list[LoweringMetrics],
    map_assets: CruiseMapAssets,
) -> str:
    cruise_meta = cruise.get('cruise_additional_meta', {})
    cruise_meta = cruise_meta if isinstance(cruise_meta, dict) else {}

    return render_template(
        'emp_cruise_metrics.html.j2',
        cruise=cruise,
        cruise_meta=cruise_meta,
        generated_ts=datetime.now(timezone.utc),
        metrics=metrics,
        stage_definitions=STAGE_DEFINITIONS,
        stage_totals=_stage_totals(metrics),
        vehicle_name=VEHICLE_NAME,
        max_depth=_max_depth(metrics),
        map_assets=map_assets,
    )


def render_template(template_name: str, **context: Any) -> str:
    '''
    Render an Empress report template
    '''

    return _template_environment().get_template(template_name).render(**context)


def write_pdf_report(html: str, pdf_path: str | Path) -> None:
    '''
    Render HTML to PDF using WeasyPrint
    '''

    os.environ.setdefault('XDG_CACHE_HOME', tempfile.gettempdir())

    from weasyprint import HTML  # pylint: disable=import-outside-toplevel

    HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf(pdf_path)


@lru_cache(maxsize=1)
def _template_environment() -> Environment:
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(default=True),
    )
    environment.filters['duration'] = format_duration
    environment.filters['timestamp'] = format_timestamp
    environment.filters['optional_float'] = format_optional_float
    environment.filters['float_list'] = format_float_list

    return environment


def _duration_seconds(start: datetime | None, stop: datetime | None) -> Seconds:
    if start is None or stop is None:
        return None

    return max(int((stop - start).total_seconds()), 0)


def _get_meta_dict(lowering: SealogRecord, key: str) -> SealogRecord:
    meta = lowering.get('lowering_additional_meta', {})
    if not isinstance(meta, dict):
        return {}

    value = meta.get(key, {})
    return value if isinstance(value, dict) else {}


def _optional_float(value: Any) -> float | None:
    if value in (None, ''):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []

    output = []
    for item in value:
        parsed = _optional_float(item)
        if parsed is not None:
            output.append(parsed)

    return output


def _build_cruise_map_assets(
    cruise_id: str,
    lowerings: list[SealogRecord],
    event_exports_by_lowering: dict[str, list[SealogRecord]],
    assets_dir: Path,
) -> CruiseMapAssets:
    tracks = []

    for lowering in lowerings:
        lowering_id = str(lowering.get('lowering_id', ''))
        event_exports = _event_exports_for_lowering(lowering, event_exports_by_lowering)
        track = _dive_track(lowering_id, event_exports)
        if track is not None:
            tracks.append(track)

    if not tracks:
        return CruiseMapAssets(dive_locations_uri=None, dive_count=0)

    map_path = assets_dir / f'{cruise_id}_dive_locations.png'

    try:
        _write_dive_locations_map(tracks, map_path)
    except Exception as err:  # pylint: disable=broad-exception-caught
        logging.warning("Unable to build cruise dive location map for %s", cruise_id)
        logging.debug(str(err))
        return CruiseMapAssets(dive_locations_uri=None, dive_count=len(tracks))

    return CruiseMapAssets(
        dive_locations_uri=map_path.resolve().as_uri(),
        dive_count=len(tracks),
    )


def _event_exports_for_lowering(
    lowering: SealogRecord,
    event_exports_by_lowering: dict[str, list[SealogRecord]],
) -> list[SealogRecord]:
    return (
        event_exports_by_lowering.get(str(lowering.get('lowering_id', '')))
        or event_exports_by_lowering.get(str(lowering.get('id', '')))
        or []
    )


def _dive_track(lowering_id: str, event_exports: list[SealogRecord]) -> DiveTrack | None:
    points = []

    for event in event_exports:
        values = _preferred_aux_values(event.get('aux_data'), ('latitude', 'longitude'))
        latitude = _bounded_float(_aux_value(values, 'latitude'), -90, 90)
        longitude = _bounded_float(_aux_value(values, 'longitude'), -180, 180)
        if latitude is None or longitude is None:
            continue

        point = (longitude, latitude)
        if not points or points[-1] != point:
            points.append(point)

    return DiveTrack(lowering_id=lowering_id, points=points) if points else None


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


def _valid_latitude(value: float) -> bool:
    return -90 <= value <= 90


def _valid_longitude(value: float) -> bool:
    return -180 <= value <= 180


def _bounded_float(value: Any, minimum: float, maximum: float) -> float | None:
    parsed = _optional_float(value)
    if parsed is None or parsed < minimum or parsed > maximum:
        return None

    return parsed


def _write_dive_locations_map(tracks: list[DiveTrack], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pyplot = _pyplot()

    latitudes = [latitude for track in tracks for _, latitude in track.points]
    longitudes = [longitude for track in tracks for longitude, _ in track.points]
    latitude_padding = max(max(latitudes) - min(latitudes), 0.01) * 0.18
    longitude_padding = max(max(longitudes) - min(longitudes), 0.01) * 0.18

    figure, axis = pyplot.subplots(figsize=(7.6, 4.8), dpi=160)
    color_map = pyplot.get_cmap('tab10')
    for index, track in enumerate(tracks):
        longitudes_for_track = [longitude for longitude, _ in track.points]
        latitudes_for_track = [latitude for _, latitude in track.points]
        color = color_map(index % color_map.N)
        axis.plot(
            longitudes_for_track,
            latitudes_for_track,
            color=color,
            linewidth=1.5,
            alpha=0.92,
            label=track.lowering_id,
        )
        _draw_track_start_arrow(axis, longitudes_for_track, latitudes_for_track, color)
        axis.annotate(
            track.lowering_id,
            (longitudes_for_track[-1], latitudes_for_track[-1]),
            textcoords='offset points',
            xytext=(4, 4),
            fontsize=7,
            color='#151a17',
        )

    axis.set_xlim(min(longitudes) - longitude_padding, max(longitudes) + longitude_padding)
    axis.set_ylim(min(latitudes) - latitude_padding, max(latitudes) + latitude_padding)
    axis.set_title('All Dive Tracklines')
    axis.set_xlabel('Longitude')
    axis.set_ylabel('Latitude')
    axis.grid(True, color='#d7dce2', linewidth=0.6)
    axis.set_aspect('equal', adjustable='box')
    if len(tracks) <= 12:
        axis.legend(loc='best', frameon=False, fontsize=7)
    figure.tight_layout()
    figure.savefig(output_path, bbox_inches='tight')
    pyplot.close(figure)


def _draw_track_start_arrow(
    axis: Any, longitudes: list[float], latitudes: list[float], color: Any,
) -> None:
    if len(longitudes) < 2:
        axis.scatter(
            longitudes[0],
            latitudes[0],
            color=color,
            edgecolor='#151a17',
            linewidth=0.5,
            s=18,
            zorder=3,
        )
        return

    start_index = 0
    next_index = next(
        (
            index
            for index in range(1, len(longitudes))
            if (longitudes[index] != longitudes[start_index]
                or latitudes[index] != latitudes[start_index])
        ),
        None,
    )
    if next_index is None:
        axis.scatter(
            longitudes[start_index],
            latitudes[start_index],
            color=color,
            edgecolor='#151a17',
            linewidth=0.5,
            s=18,
            zorder=3,
        )
        return

    axis.annotate(
        '',
        xy=(longitudes[next_index], latitudes[next_index]),
        xytext=(longitudes[start_index], latitudes[start_index]),
        arrowprops={
            'arrowstyle': '-|>',
            'color': color,
            'linewidth': 1.5,
            'mutation_scale': 10,
            'shrinkA': 0,
            'shrinkB': 0,
        },
        zorder=4,
    )


def _max_depth(metrics: list[LoweringMetrics]) -> float | None:
    depths = [metric.max_depth for metric in metrics if metric.max_depth is not None]
    return None if not depths else max(depths)


def _stage_totals(metrics: list[LoweringMetrics]) -> dict[str, int]:
    return {
        stage.label: sum((metric.stage_durations.get(stage.label) or 0) for metric in metrics)
        for stage in STAGE_DEFINITIONS
    }


def _pyplot():
    import matplotlib  # pylint: disable=import-outside-toplevel

    matplotlib.use('Agg')
    from matplotlib import pyplot  # pylint: disable=import-outside-toplevel

    return pyplot
