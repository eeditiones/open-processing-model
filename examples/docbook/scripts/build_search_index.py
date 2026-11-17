#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pagefind[bin]"]
# ///
"""
SPDX-FileCopyrightText: 2026 e-editiones
SPDX-License-Identifier: CC0-1.0

Convert opm index JSONL output to Pagefind search index.

Usage:
    python scripts/build_search_index.py --jsonl index.jsonl --output chunks/assets/search

This script:
1. Reads JSONL records from opm index output
2. Converts each record to a Pagefind CustomRecord
3. Builds a complete Pagefind search index
4. Writes the index to the specified output directory
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def load_jsonl_records(filepath):
    """Load JSONL records from a file."""
    records = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                records.append(record)
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse line {line_num} in {filepath}: {e}")
                continue
    logger.info(f"Loaded {len(records)} records from {filepath}")
    return records


async def build_pagefind_index(jsonl_path, output_dir, base_url=""):
    """
    Build Pagefind index from opm JSONL output.
    
    Args:
        jsonl_path: Path to the JSONL file from opm index
        output_dir: Directory to write the Pagefind index
        base_url: Optional base URL prefix for all search result URLs
    """
    try:
        from pagefind.index import PagefindIndex, IndexConfig
    except ImportError as e:
        logger.error(
            f"Pagefind Python package is not installed or cannot be imported: {e}. "
            "Run this script with: uv run scripts/build_search_index.py"
        )
        logger.error(f"Python executable: {sys.executable}")
        logger.error(f"Python path: {sys.path}")
        return False

    # Load the records
    records = load_jsonl_records(jsonl_path)
    if not records:
        logger.error(f"No records found in {jsonl_path}")
        return False

    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output directory: {output_path}")

    # Configure Pagefind
    config = IndexConfig(
        output_path=str(output_path),
        verbose=False,  # We handle our own logging
        default_language="en",
        # Force creation of search.json for debugging
        force_search_json=True,
    )

    async with PagefindIndex(config=config) as index:
        logger.info("Building Pagefind index...")

        # opm.toml sets [index] granularity = "page", so each record is one
        # published page
        for record in records:
            metadata = record.get('metadata', {})

            # opm index provides href like "001.html#introduction"; opm chunk
            # writes each document into a directory named after its source
            # file, so make the URL relative to the site root
            href = metadata.get('href', '')
            source = metadata.get('source')
            if href and source:
                href = f"{Path(source).name}/{href}"
            if base_url:
                url = f"{base_url.rstrip('/')}/{href}" if href else base_url
            else:
                url = href

            title = metadata.get('heading') or metadata.get('title', '')
            # Pagefind meta values must be strings
            meta = {
                'title': str(title),
                'doc': str(metadata.get('doc', '')),
                'source': str(metadata.get('source', '')),
                'chunk': str(metadata.get('chunk', '')),
                'breadcrumb': str(metadata.get('breadcrumb', '')),
            }
            await index.add_custom_record(
                url=url,
                content=record.get('document', ''),
                language="en",
                meta=meta,
            )

        logger.info(f"Added {len(records)} pages")

        # Build the final index
        logger.info("Finalizing index...")
        await index.write_files()
        logger.info(f"Pagefind index built successfully in {output_dir}")

    return True


async def main():
    parser = argparse.ArgumentParser(
        description='Build Pagefind search index from opm index output'
    )
    parser.add_argument(
        '--jsonl',
        default='index.jsonl',
        help='Path to opm index JSONL file (default: index.jsonl)'
    )
    parser.add_argument(
        '--output',
        default='chunks/assets/search',
        help='Output directory for Pagefind index (default: chunks/assets/search)'
    )
    parser.add_argument(
        '--base-url',
        default='',
        help='Base URL prefix for search result links (optional)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Check if input file exists
    if not os.path.exists(args.jsonl):
        logger.error(f"Input file not found: {args.jsonl}")
        return 1

    # Run the build
    success = await build_pagefind_index(
        jsonl_path=args.jsonl,
        output_dir=args.output,
        base_url=args.base_url
    )

    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
