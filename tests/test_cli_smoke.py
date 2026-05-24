"""CLI smoke: argparse layout doesn't crash on --help."""

from __future__ import annotations

import subprocess
import sys


def test_cli_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "create-user" in proc.stdout
    assert "list-users" in proc.stdout


def test_cli_create_user_help_runs() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "create-user", "--help"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0
    assert "--username" in proc.stdout
    assert "--display-name" in proc.stdout
    assert "--admin" in proc.stdout
