"""Integration tests use a unique, disposable database on a real MongoDB server."""

import os
from uuid import uuid4

import pytest

from app import create_app


@pytest.fixture
def app():
    name = "study_group_finder_test_" + uuid4().hex
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "test-key-only-not-for-real-accounts-123456789",
        "MONGO_URI": os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017/"),
        "MONGO_DB_NAME": name,
    })
    yield application
    store = application.extensions["store"]
    # This fixture only ever removes the new random database it created above.
    store.client.drop_database(name)
    store.close()


@pytest.fixture
def store(app):
    return app.extensions["store"]
