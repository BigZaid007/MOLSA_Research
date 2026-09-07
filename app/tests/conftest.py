import pytest


@pytest.fixture(autouse=True)
def _skip_huggingface_download(monkeypatch):
    """Unit tests must not download Zarra. Ranker tests stub scores explicitly."""
    monkeypatch.setattr("services.semantic._enabled", lambda: False)
