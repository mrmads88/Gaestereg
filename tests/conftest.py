import os
import shutil
import tempfile

import pytest

_tmp = tempfile.mkdtemp()
os.environ.update(DATA_DIR=_tmp, APP_ENV="local", ADMIN_PASSWORD="hemmelig", NOTIFY_MODE="test", SEED_DEMO="1",
                  REPORT_SCHEDULER="0")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def data_dir():
    return _tmp


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c
    shutil.rmtree(_tmp, ignore_errors=True)
