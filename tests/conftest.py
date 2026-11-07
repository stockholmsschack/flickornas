from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from flickornas_standings.web import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "STATE_DIRECTORY": tmp_path / "state",
            "OUTPUT_DIRECTORY": tmp_path / "output",
        }
    )


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def run_browser_script():
    """Run a `tests/browser` script with Node; skip when Node is missing."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is not installed")

    def run(name: str) -> None:
        completed = subprocess.run(
            [node, f"tests/browser/{name}"],
            cwd=PROJECT_ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr

    return run


@pytest.fixture
def assert_served(client):
    """Assert that the app serves a non-trivial static file at a path."""

    def check(path: str) -> None:
        response = client.get(path)
        try:
            assert response.status_code == 200
            assert len(response.data) > 100
        finally:
            response.close()

    return check
