"""Every test uses local inputs and forbids HTTP requests."""

import osmnx as ox
import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_network(monkeypatch, tmp_path):
    monkeypatch.setattr(ox.settings, "cache_folder", tmp_path / "cache")
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline tests")
    monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
