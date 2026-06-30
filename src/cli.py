#!/usr/bin/env python3
"""
CLI for the Multi-Source Candidate Data Transformer.

Usage:
    python -m src.cli --input-dir sample_inputs \
        --config config/example_custom_config.json \
        --out-default output/default_output.json \
        --out-custom output/custom_output.json
"""
from __future__ import annotations

import argparse
import json
import sys

from src.pipeline import run_pipeline, load_config


def main(argv=None):
    parser = argparse.ArgumentParser(description="Multi-Source Candidate Data Transformer")
    parser.add_argument("--input-dir", required=True, help="Directory containing source files")
    parser.add_argument("--config", default=None, help="Path to a custom runtime output config (JSON)")
    parser.add_argument("--out-default", default="output/default_output.json",
                         help="Where to write the default-schema output")
    parser.add_argument("--out-custom", default="output/custom_output.json",
                         help="Where to write the custom-config output (only if --config given)")
    parser.add_argument("--quiet", action="store_true", help="Suppress warning printout")
    args = parser.parse_args(argv)

    custom_config = load_config(args.config)
    result = run_pipeline(args.input_dir, custom_config)

    with open(args.out_default, "w", encoding="utf-8") as f:
        json.dump(result["default_output"], f, indent=2)
    print(f"Wrote {len(result['default_output'])} candidate(s) -> {args.out_default}")

    if custom_config is not None:
        with open(args.out_custom, "w", encoding="utf-8") as f:
            json.dump(result["custom_output"], f, indent=2)
        print(f"Wrote {len(result['custom_output'])} candidate(s) -> {args.out_custom}")
        if result["custom_validation_errors"]:
            print(f"  ({len(result['custom_validation_errors'])} validation issue(s) — see below)")

    if not args.quiet:
        if result["warnings"]:
            print(f"\n{len(result['warnings'])} warning(s):")
            for w in result["warnings"]:
                print(f"  - {w}")
        if result["custom_validation_errors"]:
            print(f"\n{len(result['custom_validation_errors'])} custom-config validation issue(s):")
            for e in result["custom_validation_errors"]:
                print(f"  - {e}")

    print(f"\n{result['candidate_count']} candidate(s) resolved from {result['source_record_count']} source record(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
