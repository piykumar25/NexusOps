"""
NexusOps Database Configuration
=================================
Production-grade connection management for PostgreSQL.
Features:
  - Centralized configuration via NexusOpsSettings
  - Connection retry logic for cold starts
  - Connection pooling with pre-ping validation
  - Health check utility
"""

import logging
import time
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from backend.core.config.settings import get_settings

logger = logging.getLogger("nexusops.db")
settings = get_settings()

# Avoid exposing password in logs
_safe_url = settings._mask_url(settings.database_url)
logger.info(f"Initializing database connections to: {_safe_url}")

engine = create_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Detects stale connections before use
    pool_recycle=3600,   # Recycle connections after an hour
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def wait_for_db(max_retries: int = 5, retry_delay: int = 2):
    """
    Attempt to connect to the database with exponential backoff.
    Crucial for Docker Compose where the DB container might start
    before it's actually ready to accept connections.
    """
    retry_count = 0
    while retry_count < max_retries:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection established successfully.")
            return True
        except Exception as e:
            retry_count += 1
            logger.warning(
                f"Database connection failed (Attempt {retry_count}/{max_retries}): {e}. "
                f"Retrying in {retry_delay} seconds..."
            )
            time.sleep(retry_delay)
            retry_delay *= 2  # Exponential backoff

    logger.error("Failed to connect to the database after maximum retries.")
    return False


def check_db_health() -> bool:
    """Fast health check for readiness probes."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@contextmanager
def get_db():
    """Yield a database session with automatic cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
