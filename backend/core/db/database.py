from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from contextlib import contextmanager

DATABASE_URL = "postgresql://nexusops:nexusops_password@localhost:5432/nexusops_db"

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

@contextmanager
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
