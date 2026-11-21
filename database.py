import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()


class Base(DeclarativeBase):
    pass


def make_engine(url):
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg://monitor:monitor-dev@127.0.0.1:5432/monitor",
))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as session:
        yield session
