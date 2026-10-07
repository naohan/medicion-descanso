"""
Clave API opcional.

Si API_KEY está definida en el entorno (.env), todas las rutas /api exigen la
cabecera X-API-Key con ese valor. Si no está definida, la API queda abierta.
"""
import os
import secrets
from typing import Optional

from dotenv import load_dotenv
from fastapi import Header, HTTPException

load_dotenv()

API_KEY = os.getenv("API_KEY") or None


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    if API_KEY is None:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=401, detail="Falta la cabecera X-API-Key o no es válida")
