#!/usr/bin/env python3
"""
Validate seed/*.json against authoring Pydantic models and optional template
placeholder ↔ concepts/mappings contract (see app.services.seed_validation).

Exit 0 if valid; exit 1 with errors on stderr.

Usage (from project root):
  python scripts/validate_seed.py

"""

from __future__ import annotations

import logging
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("validate_seed")


def main() -> int:
    from app.services.seed_validation import (
        load_seed_arrays,
        validate_seed_json_payloads,
        validate_template_placeholder_contract,
    )

    seed_dir = os.path.join(PROJECT_ROOT, "seed")
    concepts, mappings, templates, load_errors = load_seed_arrays(seed_dir)
    if load_errors:
        for err in load_errors:
            logger.error("%s", err)
        return 1

    errs = validate_seed_json_payloads(concepts, mappings, templates)
    if errs:
        for err in errs:
            logger.error("%s", err)
        return 1

    if templates:
        cdicts = [c for c in concepts if isinstance(c, dict)]
        mdicts = [m for m in mappings if isinstance(m, dict)]
        tdicts = [t for t in templates if isinstance(t, dict)]
        contract_errs = validate_template_placeholder_contract(cdicts, mdicts, tdicts)
        if contract_errs:
            for err in contract_errs:
                logger.error("%s", err)
            return 1

    tmpl_n = len(templates) if templates is not None else 0
    logger.info(
        "Seed validation OK (concepts=%d mappings=%d templates=%d)",
        len(concepts),
        len(mappings),
        tmpl_n,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
