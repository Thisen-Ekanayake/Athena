import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://athena:athena_password@localhost:5432/athena_db")
# A plain postgresql:// names no driver, and SQLAlchemy 2.1 then picks psycopg 3; the driver installed is psycopg2.
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg2://" + DATABASE_URL[len("postgresql://"):]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Bring the schema up to date with the Alembic revisions (athena.database.migrate)."""
    from athena.database.migrate import upgrade
    upgrade()
