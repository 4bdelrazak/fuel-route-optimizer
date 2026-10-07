import pytest
import requests


class FakeResponse:
    def __init__(self, status_code=200, payload=None, body=None):
        self.status_code = status_code
        self._payload = payload
        self._body = body

    def json(self):
        if self._body is not None:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def fake_get(monkeypatch):
    """Replace `requests.get` for one module and record the calls made."""

    def install(module: str, response=None, error: Exception | None = None):
        calls = []

        def fake(url, **kwargs):
            calls.append({"url": url, **kwargs})
            if error is not None:
                raise error
            return response

        monkeypatch.setattr(f"{module}.requests.get", fake)
        return calls

    return install


@pytest.fixture
def timeout_error():
    return requests.Timeout("too slow")


@pytest.fixture
def connection_error():
    return requests.ConnectionError("no route to host")
