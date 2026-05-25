"""Subprocess safety: arg validation.

The actual subprocess execution path is exercised in integration tests
(skipped without a real shell); here we test the validator that runs
before any process spawn.
"""

from __future__ import annotations

import pytest

from app.integrations.computer.subprocess_safe import UnsafeArgError, validate_args


def test_clean_args_pass() -> None:
    out = validate_args(["python", "-c", "print('hi')"])
    assert out == ["python", "-c", "print('hi')"]


def test_null_byte_blocked() -> None:
    with pytest.raises(UnsafeArgError, match="null byte"):
        validate_args(["x\x00y"])


@pytest.mark.parametrize("bad", ["a|b", "x;rm -rf /", "a&b", "a`b`c", "a>b", "$VAR"])
def test_shell_metachars_blocked(bad: str) -> None:
    with pytest.raises(UnsafeArgError, match="denied shell"):
        validate_args([bad])


def test_path_traversal_blocked() -> None:
    with pytest.raises(UnsafeArgError, match="traversal"):
        validate_args(["../secret"])


def test_non_string_arg_blocked() -> None:
    with pytest.raises(UnsafeArgError, match="not a string"):
        validate_args([42])  # type: ignore[list-item]
