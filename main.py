import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import SQLAlchemyError

from database import Base, SessionLocal, engine, get_db
from monitoring import probe, run_due_checks
from routes import router

logger = logging.getLogger(__name__)


def create_app(*, db_engine=engine, session_factory=SessionLocal,
               scheduler_enabled=None, probe_fn=probe):
    if scheduler_enabled is None:
        scheduler_enabled = os.getenv("ENABLE_SCHEDULER", "true").lower() == "true"

    @asynccontextmanager
    async def lifespan(app):
        Base.metadata.create_all(db_engine)
        scheduler = None
        if scheduler_enabled:
            scheduler = BackgroundScheduler(timezone="UTC")
            scheduler.add_job(run_due_checks, "interval", seconds=1,
                              args=[session_factory, probe_fn], max_instances=1, coalesce=True)
            scheduler.start()
        try:
            yield
        finally:
            if scheduler:
                scheduler.shutdown(wait=True)

    app = FastAPI(
        title="API Monitoring & Alerting Platform",
        description="Monitor HTTP endpoints, inspect check history, and track outages.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.probe = probe_fn
    if session_factory is not SessionLocal:
        def test_database():
            with session_factory() as session:
                yield session

        app.dependency_overrides[get_db] = test_database

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        logger.exception("Database request failed on %s", request.url.path, exc_info=exc)
        return JSONResponse(status_code=503, content={"detail": "Database operation failed"})

    @app.get("/", include_in_schema=False)
    def home():
        return RedirectResponse("/docs")

    app.include_router(router)
    return app


app = create_app()
