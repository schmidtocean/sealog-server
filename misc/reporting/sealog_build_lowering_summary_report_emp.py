#!/usr/bin/env python3
'''
FILE:           sealog_build_lowering_summary_report_emp.py

DESCRIPTION:    Minimal Empress lowering summary PDF reports
'''

from datetime import datetime, timezone
from pathlib import Path

from misc.reporting.sealog_build_cruise_summary_report_emp import (
    STAGE_DEFINITIONS,
    VEHICLE_NAME,
    SealogRecord,
    build_lowering_metrics,
    format_float_list,
    format_optional_float,
    get_stage_boundary,
    render_template,
    write_pdf_report,
)


def write_lowering_summary_report(cruise: SealogRecord, lowering: SealogRecord, output_dir: str | Path) -> Path:
    '''
    Write a minimal PDF report for one Empress lowering
    '''

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    cruise_id = str(cruise.get('cruise_id', 'cruise'))
    lowering_id = str(lowering.get('lowering_id', 'lowering'))
    report_path = output_path / f'{cruise_id}_{lowering_id}_{VEHICLE_NAME}_Lowering_Summary.pdf'

    write_pdf_report(_render_lowering_summary_html(cruise, lowering), report_path)

    return report_path


def _render_lowering_summary_html(cruise: SealogRecord, lowering: SealogRecord) -> str:
    metrics = build_lowering_metrics(lowering)
    meta = lowering.get('lowering_additional_meta', {})
    meta = meta if isinstance(meta, dict) else {}

    return render_template(
        'emp_lowering_summary.html.j2',
        cruise=cruise,
        lowering=lowering,
        lowering_meta=meta,
        metrics=metrics,
        generated_ts=datetime.now(timezone.utc),
        stage_definitions=STAGE_DEFINITIONS,
        stage_boundaries=[
            {
                'stage': stage,
                'start': get_stage_boundary(lowering, stage.start, stage.start_fallback),
                'stop': get_stage_boundary(lowering, stage.stop, stage.stop_fallback),
            }
            for stage in STAGE_DEFINITIONS
        ],
        vehicle_name=VEHICLE_NAME,
        max_depth=format_optional_float(metrics.max_depth),
        bounding_box=format_float_list(metrics.bounding_box),
    )
