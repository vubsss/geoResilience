import osmnx as ox
import pytest
import requests


def pytest_addoption(parser):
    parser.addoption("--network", action="store_true", help="Run tests that contact OSM services")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--network"):
        for item in items:
            if item.get_closest_marker("network"):
                item.add_marker(pytest.mark.skip(reason="requires --network"))


@pytest.fixture(autouse=True)
def isolate_network(request, monkeypatch, tmp_path):
    monkeypatch.setattr(ox.settings, "cache_folder", tmp_path / "cache")
    if request.node.get_closest_marker("network") is None:
        def forbidden(*args, **kwargs):
            raise AssertionError("Network access is forbidden in offline tests")
        monkeypatch.setattr(requests.sessions.Session, "request", forbidden)
