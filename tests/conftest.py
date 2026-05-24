"""Shared test fixtures.

DB-backed tests are marked `requires_db` and skipped unless
`JARVIS_TEST_DB_URL` is set in the environment. CI can opt in by
spinning up Postgres and exporting that variable.
"""

from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("JARVIS_TEST_DB_URL"):
        return
    skip_db = pytest.mark.skip(reason="JARVIS_TEST_DB_URL not set; skipping DB tests")
    for item in items:
        if "requires_db" in item.keywords:
            item.add_marker(skip_db)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_db: test needs a live Postgres reachable via JARVIS_TEST_DB_URL"
    )
