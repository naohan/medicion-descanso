"""
Modelos ORM: mapean directamente a las tablas de PostgreSQL.

Tablas:
  raw_samples      → una fila por muestra de FC (~1 s)
  sleep_windows    → ventanas de 1 minuto procesadas en el reloj
  sleep_sessions   → una fila por noche completa
  daily_summary    → resumen por día (una fila por día por dispositivo)
"""
from datetime import datetime, date
from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from database import Base


# ---------------------------------------------------------------------------
# 1. Muestras brutas de frecuencia cardíaca
# ---------------------------------------------------------------------------
class RawSample(Base):
    __tablename__ = "raw_samples"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # FC
    bpm = Column(Float, nullable=False)
    rr_estimated_ms = Column(Float, nullable=True)   # 60000 / bpm

    # Movimiento (puede ser null si no se captura en ese momento)
    accel_magnitude = Column(Float, nullable=True)   # magnitud |g|
    gyro_magnitude = Column(Float, nullable=True)    # magnitud |ω|

    # Pasos
    steps_delta = Column(Integer, nullable=True, default=0)

    # Metadatos
    accuracy = Column(String(32), nullable=True)     # HIGH / MEDIUM / LOW
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 2. Ventanas de 1 minuto (procesadas en el reloj)
# ---------------------------------------------------------------------------
class SleepWindow(Base):
    __tablename__ = "sleep_windows"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)

    window_start = Column(DateTime(timezone=True), nullable=False, index=True)
    window_end = Column(DateTime(timezone=True), nullable=False)

    # FC del minuto
    avg_hr = Column(Float, nullable=True)
    min_hr = Column(Float, nullable=True)
    max_hr = Column(Float, nullable=True)
    std_hr = Column(Float, nullable=True)

    # HRV aproximado calculado en el reloj (RMSSD estimado)
    hrv_rmssd_estimated = Column(Float, nullable=True)

    sample_count = Column(Integer, nullable=True, default=0)

    # Movimiento
    steps = Column(BigInteger, nullable=True, default=0)
    accel_mean = Column(Float, nullable=True)

    # Estado
    activity_state = Column(String(32), nullable=True)    # ASLEEP/AWAKE/PASSIVE
    sleep_state = Column(String(16), nullable=True)        # SLEEPING/AWAKE/UNKNOWN
    confidence = Column(Float, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 3. Sesiones de sueño (una por noche)
# ---------------------------------------------------------------------------
class SleepSession(Base):
    __tablename__ = "sleep_sessions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False, index=True)

    session_start = Column(DateTime(timezone=True), nullable=False)
    session_end = Column(DateTime(timezone=True), nullable=True)

    # Duración
    total_minutes = Column(Integer, nullable=True)
    sleep_minutes = Column(Integer, nullable=True)
    awake_minutes = Column(Integer, nullable=True)
    awakenings = Column(Integer, nullable=True, default=0)

    # FC
    resting_hr = Column(Float, nullable=True)
    avg_hr = Column(Float, nullable=True)

    # HRV
    hrv_rmssd_avg = Column(Float, nullable=True)
    hrv_rmssd_min = Column(Float, nullable=True)

    # Fatiga
    fatigue_score = Column(Integer, nullable=True)    # 0–100
    fatigue_label = Column(String(64), nullable=True)

    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)


# ---------------------------------------------------------------------------
# 4. Resumen diario (una fila por día y dispositivo)
# ---------------------------------------------------------------------------
class DailySummary(Base):
    __tablename__ = "daily_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(String(64), nullable=False)
    summary_date = Column(Date, nullable=False)

    # Sueño
    sleep_minutes = Column(Integer, nullable=True)
    awakenings = Column(Integer, nullable=True, default=0)

    # FC
    resting_hr = Column(Float, nullable=True)
    avg_hr_day = Column(Float, nullable=True)

    # HRV
    hrv_avg = Column(Float, nullable=True)
    hrv_min = Column(Float, nullable=True)

    # Actividad
    steps_total = Column(BigInteger, nullable=True, default=0)

    # Fatiga
    fatigue_score = Column(Integer, nullable=True)
    fatigue_label = Column(String(64), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("device_id", "summary_date", name="uq_daily_device_date"),
    )
