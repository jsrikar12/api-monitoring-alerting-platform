import os
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from main import create_app
from monitoring import probe


@pytest.fixture
def engine(tmp_path):
    test_url = os.getenv("TEST_DATABASE_URL")
    if test_url:
        # Every test gets its own PostgreSQL schema, even when run against a shared server.
        admin = create_engine(test_url)
        schema = f"monitor_test_{uuid4().hex}"
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        database = create_engine(test_url, connect_args={"options": f"-csearch_path={schema}"})
        try:
            yield database
        finally:
            database.dispose()
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            admin.dispose()
    else:
        database = create_engine(f"sqlite:///{tmp_path / 'test.sqlite'}")

        @event.listens_for(database, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        try:
            yield database
        finally:
            database.dispose()


@pytest.fixture
def api(engine):
    outcomes = []
    requests = []

    def reply(request):
        requests.append(request)
        outcome = outcomes.pop(0)
        if isinstance(outcome, type):
            raise outcome("mock failure", request=request)
        return httpx.Response(outcome, headers={"Location": "http://127.0.0.1/"})

    def mock_probe(url):
        return probe(url, transport=httpx.MockTransport(reply))

    sessions = sessionmaker(engine, expire_on_commit=False)
    app = create_app(db_engine=engine, session_factory=sessions,
                     scheduler_enabled=False, probe_fn=mock_probe)
    with TestClient(app) as client:
        yield client, outcomes, requests, sessions
