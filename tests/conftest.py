import pytest


@pytest.fixture(autouse=True)
def _isolated_request_ledger(tmp_path, monkeypatch):
    """Tests must never count against (or read) the real free-tier ledger in results/."""
    monkeypatch.setenv("PAYGYM_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.delenv("PAYGYM_DAILY_CAP", raising=False)
