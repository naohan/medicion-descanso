"""
Script para crear todas las tablas en PostgreSQL.
Ejecutar UNA sola vez después de configurar DATABASE_URL en .env:

    python init_db.py

Si las tablas ya existen no las borra (checkfirst=True por defecto en SQLAlchemy).
"""
from database import engine, Base
import models  # noqa: F401 — importar para que SQLAlchemy registre los modelos

if __name__ == "__main__":
    print("Creando tablas en PostgreSQL…")
    Base.metadata.create_all(bind=engine)
    print("Listo. Tablas creadas:")
    for table_name in Base.metadata.tables:
        print(f"  ✓ {table_name}")
