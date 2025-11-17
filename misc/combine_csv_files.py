#!/usr/bin/env python3
"""
FILE:           combine_csv_files.py

DESCRIPTION:    This utility program combines multiple CSV data files into a
                a single CSV file.

                Prior to combining the files are resampled at 1Hz.

                The files are assumed to have a header record and an ISO8601-
                compliant timestamp in a column named "Timestamp".

                The output will exclude any columns named "Header" and
                "Checksum".

                The output will include a header record that includes the
                "Timestamp" column followed by the combined header records of
                all files specified for combining. The header names will be
                prefixed with a subset of the column's original filename.

                i.e.:
                    Filename:      FKt250110_sb_ctd_sbe49_S0774.txt
                    Header Prefix: sb_ctd_sbe49_

REQUIREMENTS:   Python3.10
                Python Modules:
                    pandas==2.3.0
                    polars==1.31.0

POSITIONAL ARGUMENTS:
    files: one or more csv filepaths to combine

OPTIONAL ARGUMENTS:
    -o --output: Specifies the filepath for the output CSV file.
                 Default: ./combined_1Hz.csv

EXAMPLE USAGE:
    python3 combine_csv_files.py data1.csv data2.csv data3.csv -o merged_output.csv

BUGS:
NOTES:
AUTHOR:     Webb Pinner
COMPANY:    OceanDataTools.org
VERSION:    1.0
CREATED:    2025-06-25
REVISION:   

LICENSE INFO:   This code is licensed under MIT license (see LICENSE.txt for details)
                Copyright (C) OceanDataTools.org 2024
"""

import os
import argparse
import logging

import polars as pl
import pandas as pd


def combine_files_at_1hz(files, output_file):
    """
    Combine multiple timestamped CSV files into a single file sampled at 1Hz.
    Truncate lines on read means any malformed line will be ingested as is with no warning
    as long as it has enough commas in it, the rest after last required comma will be discarded
    Infer schema length 0 means every line will be read to determine dtype, this is a non-issue
    due to polars efficiencies at this scale

    The script:
    - Cleans column headers and values
    - Removes whitespace and 'Header' columns
    - Parses and truncates timestamps to 1-second resolution
    - Fills missing values forward/backward
    - Adds filename-based prefixes to columns
    - Writes the final joined CSV to disk

    Args:
        files (list of str): List of file paths to CSVs to combine.
        output_file (str): Path to the output CSV.
    """
    dfs = []

    for f in files:
        try:
            df = pl.read_csv(f, infer_schema_length=0, truncate_ragged_lines=True)
        except pl.ComputeError:
            logging.warning("Schema inference failed for %s. Reading all as text.", f)
            # Fallback: Read all columns as text, then try to convert them
            df = pl.read_csv(f, dtypes={col: pl.Utf8 for col in pl.read_csv(f, n_rows=1, truncate_ragged_lines=True).columns})
            df = df.with_columns(
                pl.col(pl.Utf8).exclude("Timestamp").cast(pl.Float64, strict=False)
            )

        df = df.rename({col: col.strip() for col in df.columns})

        if df.height == 0:
            logging.info("Warning: %s contains no data rows. Skipping.", f)
            continue

        df = df.drop([
            col for col in df.columns if col.lower() == "header"
        ])

        df = df.with_columns([
            pl.col(col).str.strip_chars()
            for col, dtype in zip(df.columns, df.dtypes)
            if dtype == pl.Utf8
        ])

        df = df.with_columns(
            pl.col("Timestamp")
            .str.to_datetime("%Y-%m-%dT%H:%M:%S%.fZ", strict=False)
            .dt.replace_time_zone(None)
        ).with_columns(
            pl.col("Timestamp").dt.truncate("1s")
        )

        # This resamples by taking the first entry for each second
        df = df.group_by("Timestamp").agg(
            pl.all().exclude("Timestamp").first()
        )

        basename = os.path.splitext(os.path.basename(f))[0]
        parts = basename.split("_")
        prefix = "_".join(parts[1:-1]) + "_"

        df = df.rename({
            col: f"{prefix}{col}" if col != "Timestamp" else col
            for col in df.columns
        })

        dfs.append(df)

    if not dfs:
        logging.info("Nothing to combine, quitting.")
        return

    all_timestamps = []
    for df in dfs:
        all_timestamps.extend(df["Timestamp"].to_list())

    min_timestamp = min(all_timestamps)
    max_timestamp = max(all_timestamps)

    pandas_range = pd.date_range(
        start=min_timestamp, end=max_timestamp, freq="1s"
    )

    timestamps_1hz = pl.DataFrame({
        "Timestamp": pl.Series("Timestamp", pandas_range).cast(pl.Datetime)
    })

    aligned_dfs = []
    for df in dfs:
        df_aligned = timestamps_1hz.join(df, on="Timestamp", how="left")

        aligned_dfs.append(df_aligned)

    combined = aligned_dfs[0]
    for i, df in enumerate(aligned_dfs[1:], start=1):
        combined = combined.join(
            df,
            on="Timestamp",
            how="left",
            suffix=f"_right{i}"
        )

    combined = combined.with_columns(
        pl.col("Timestamp")
        .dt.strftime("%Y-%m-%dT%H:%M:%S.%6fZ")
        .alias("Timestamp")
    )

    combined.write_csv(output_file)
    logging.info("✅ Combined CSV saved to %s", output_file)


if __name__ == "__main__":
    """
    Entry point: Parse command-line arguments and combine input CSV files.
    """
    parser = argparse.ArgumentParser(
        description="Combine multiple CSVs with Timestamp into 1Hz CSV."
    )
    parser.add_argument("files", nargs="+", help="Input CSV files")
    parser.add_argument(
        "-o", "--output", default="combined_1Hz.csv", help="Output file"
    )
    parser.add_argument("-v", "--verbosity", action="count", default=0)

    parsed_args = parser.parse_args()

    ############################
    # Set up logging before we do any other argument parsing (so that we
    # can log problems with argument parsing).

    LOGGING_FORMAT = '%(asctime)-15s %(levelname)s - %(message)s'
    logging.basicConfig(format=LOGGING_FORMAT)

    LOG_LEVELS = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    parsed_args.verbosity = min(parsed_args.verbosity, max(LOG_LEVELS))
    logging.getLogger().setLevel(LOG_LEVELS[parsed_args.verbosity])

    # Run the main function
    try:
        combine_files_at_1hz(parsed_args.files, parsed_args.output)

    except KeyboardInterrupt:
        logging.warning('Interrupted')
        try:
            sys.exit(0)
        except SystemExit:
            os._exit(0) # pylint: disable=protected-access
