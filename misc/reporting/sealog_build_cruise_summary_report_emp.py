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
import os
from pathlib import Path
import tempfile
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

VEHICLE_NAME = 'Empress'
TEMPLATE_DIR = Path(__file__).parent / 'templates'

SealogRecord = dict[str, Any]
Seconds = int | None


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


STAGE_DEFINITIONS = (
    StageDefinition(
        'Deck to Deck',
        ('In water',),
        ('Out of water',),
        start_fallback='start_ts',
        stop_fallback='stop_ts',
    ),
    StageDefinition('Deployment', ('Deployment',), ('Descent Initiated', 'Initial Descent', 'lowering_descending')),
    StageDefinition('Descent', ('Descent Initiated', 'Initial Descent', 'lowering_descending'), ('Reached Survey Depth', 'At Depth', 'lowering_on_bottom')),
    StageDefinition('Survey Depth', ('Reached Survey Depth', 'At Depth', 'lowering_on_bottom'), ('Leaving Survey Depth', 'lowering_off_bottom')),
    StageDefinition('Ascent', ('Leaving Survey Depth', 'lowering_off_bottom'), ('Vehicle on Surface', 'lowering_on_surface')),
    StageDefinition(
        'Recovery',
        ('Vehicle on Surface', 'lowering_on_surface', 'Recovery'),
        ('Mission Key Inserted',),
        stop_fallback='stop_ts',
    ),
)


def parse_timestamp(value: Any) -> datetime | None:
    '''
    Parse a Sealog ISO timestamp as UTC
    '''

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

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


def get_stage_boundary(lowering: SealogRecord, names: tuple[str, ...], fallback_key: str | None = None) -> datetime | None:
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
        start_ts=get_stage_boundary(lowering, ('In water',), 'start_ts'),
        stop_ts=get_stage_boundary(lowering, ('Out of water',), 'stop_ts'),
        stage_durations=stage_durations,
        max_depth=_optional_float(stats.get('max_depth')),
        bounding_box=_float_list(stats.get('bounding_box')),
    )


def write_cruise_metrics_report(cruise: SealogRecord, lowerings: list[SealogRecord], output_dir: str | Path) -> list[Path]:
    '''
    Write cruise-level Empress metrics as PDF
    '''

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cruise_id = str(cruise.get('cruise_id', 'cruise'))
    metrics = [build_lowering_metrics(lowering) for lowering in lowerings]

    pdf_path = output_path / f'{cruise_id}_{VEHICLE_NAME}_Cruise_Metrics.pdf'
    html = _render_cruise_metrics_html(cruise, metrics)
    write_pdf_report(html, pdf_path)

    return [pdf_path]


def _render_cruise_metrics_html(cruise: SealogRecord, metrics: list[LoweringMetrics]) -> str:
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

    from weasyprint import HTML # pylint: disable=import-outside-toplevel

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


def _max_depth(metrics: list[LoweringMetrics]) -> float | None:
    depths = [metric.max_depth for metric in metrics if metric.max_depth is not None]
    return None if not depths else max(depths)


def _stage_totals(metrics: list[LoweringMetrics]) -> dict[str, int]:
    return {
        stage.label: sum((metric.stage_durations.get(stage.label) or 0) for metric in metrics)
        for stage in STAGE_DEFINITIONS
    }
