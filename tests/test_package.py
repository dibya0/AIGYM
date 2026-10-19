import pytest

import paygym
from paygym.cli import main


def test_package_imports_with_version():
    assert paygym.__version__ == "0.1.0"


def test_cli_runs_without_command():
    assert main([]) == 0


def test_cli_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert "paygym 0.1.0" in capsys.readouterr().out
