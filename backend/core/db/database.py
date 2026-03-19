"""
NexusOps Database Configuration
=================================
Connection management via environment variables. NEVER hardcode credentials.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://nexusops:nexusops_password@localhost:5432/nexusops_db"
)

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Detects stale connections before use
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


@contextmanager
def get_db():
    """Yield a database session with automatic cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
