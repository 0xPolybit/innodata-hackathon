"""Smoke tests for the TaskFactory skeleton."""

import pytest

import taskfactory
from taskfactory.cli import COMMANDS, main


def test_version() -> None:
    assert taskfactory.__version__ == "0.1.0"


def test_help_exits_with_zero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


# "run", "eval", "report" and "diff" are implemented and tested in tests/test_pipeline.py,
# tests/test_benchmark.py, tests/test_report.py and tests/test_diff.py; only placeholders are
# listed here.
PLACEHOLDER_COMMANDS = [
    name for name in COMMANDS if name not in {"run", "eval", "report", "diff"}
]


@pytest.mark.parametrize("command", PLACEHOLDER_COMMANDS)
def test_subcommand_exits_with_zero(command: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([command]) == 0
    assert capsys.readouterr().out.strip() == "not implemented yet"
