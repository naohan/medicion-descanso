"""
Schemas Pydantic: validan el JSON que llega desde el reloj o el teléfono.
Cada campo opcional tiene None como default para no romper si el reloj
no envía ese campo en versiones anteriores del firmware.
"""
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Muestra bruta de FC
# ---------------------------------------------------------------------------
class RawSampleIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    recorded_at: datetime            # ISO 8601 con timezone, ej. "2026-09-08T02:30:00Z"
    bpm: float = Field(..., gt=0, lt=300)
    accel_magnitude: Optional[float] = None
    gyro_magnitude: Optional[float] = None
    steps_delta: Optional[int] = Field(default=0, ge=0)
    accuracy: Optional[str] = None   # "HIGH" / "MEDIUM" / "LOW"


class RawSampleBatchIn(BaseModel):
    """El reloj puede enviar hasta 1000 muestras por petición."""
    samples: list[RawSampleIn] = Field(..., max_length=1000)


# ---------------------------------------------------------------------------
# Ventana de 1 minuto
# ---------------------------------------------------------------------------
class SleepWindowIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    window_start: datetime
    window_end: datetime
    avg_hr: Optional[float] = None
    min_hr: Optional[float] = None
    max_hr: Optional[float] = None
    std_hr: Optional[float] = None
    hrv_rmssd_estimated: Optional[float] = None
    sample_count: Optional[int] = Field(default=0, ge=0)
    steps: Optional[int] = Field(default=0, ge=0)
    accel_mean: Optional[float] = None
    activity_state: Optional[str] = None
    sleep_state: Optional[str] = None     # "SLEEPING" / "AWAKE" / "UNKNOWN"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class SleepWindowBatchIn(BaseModel):
    windows: list[SleepWindowIn] = Field(..., max_length=1500)


# ---------------------------------------------------------------------------
# Sesión de sueño completa
# ---------------------------------------------------------------------------
class SleepSessionIn(BaseModel):
    device_id: str = Field(..., max_length=64)
    session_start: datetime
    session_end: Optional[datetime] = None
    total_minutes: Optional[int] = Field(default=None, ge=0)
    sleep_minutes: Optional[int] = Field(default=None, ge=0)
    awake_minutes: Optional[int] = Field(default=None, ge=0)
    awakenings: Optional[int] = Field(default=0, ge=0)
    resting_hr: Optional[float] = None
    avg_hr: Optional[float] = None
    hrv_rmssd_avg: Optional[float] = None
    hrv_rmssd_min: Optional[float] = None
    fatigue_score: Optional[int] = Field(default=None, ge=0, le=100)
    fatigue_label: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Responses (lo que el API devuelve)
# ---------------------------------------------------------------------------
class IngestResponse(BaseModel):
    inserted: int
    duplicates: int = 0                   # filas ya guardadas que se ignoraron
    message: str = "OK"
