"""
Configuración de la conexión a PostgreSQL usando SQLAlchemy.
La URL se lee desde la variable de entorno DATABASE_URL (archivo .env).
"""
import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/serenity_fatiga",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Dependency de FastAPI: abre y cierra la sesión por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
