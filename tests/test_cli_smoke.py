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


def test_cli_lists_init_and_backup_subcommands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    assert "init" in proc.stdout
    assert "backup" in proc.stdout


def test_cli_backup_help_lists_subcommands() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "backup", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    assert "create" in proc.stdout
    assert "list" in proc.stdout
    assert "restore" in proc.stdout


def test_cli_backup_create_help() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "app.cli", "backup", "create", "--help"],
        capture_output=True, text=True, timeout=15,
    )
    assert proc.returncode == 0
    assert "--output-dir" in proc.stdout
