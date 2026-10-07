"""
POST endpoints: el reloj (o el teléfono como intermediario) envía datos aquí.

Rutas:
  POST /api/samples          → muestras brutas de FC (batch hasta 500)
  POST /api/windows          → ventanas de 1 minuto (batch hasta 1500)
  POST /api/sessions         → sesión de sueño completa
"""
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
import models
import schemas
import sleep_logic

router = APIRouter(prefix="/api", tags=["ingest"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_rr(bpm: float) -> Optional[float]:
    """Convierte BPM a intervalo RR estimado en milisegundos."""
    if bpm and bpm > 0:
        return round(60_000.0 / bpm, 2)
    return None


def _rmssd_from_bpm_list(bpm_list: list[float]) -> Optional[float]:
    """
    Calcula RMSSD aproximado a partir de una lista de valores BPM.
    Convierte cada BPM a RR estimado y luego calcula las diferencias sucesivas.
    Devuelve None si hay menos de 2 muestras.
    """
    if len(bpm_list) < 2:
        return None
    rr = [60_000.0 / b for b in bpm_list if b > 0]
    if len(rr) < 2:
        return None
    diffs_sq = [(rr[i + 1] - rr[i]) ** 2 for i in range(len(rr) - 1)]
    return round(math.sqrt(sum(diffs_sq) / len(diffs_sq)), 2)


# ---------------------------------------------------------------------------
# POST /api/samples  — muestras brutas de FC
# ---------------------------------------------------------------------------
@router.post("/samples", response_model=schemas.IngestResponse)
def ingest_samples(payload: schemas.RawSampleBatchIn, db: Session = Depends(get_db)):
    """
    Recibe hasta 500 muestras brutas de FC desde el reloj.
    Calcula automáticamente rr_estimated_ms antes de guardar.
    """
    if not payload.samples:
        raise HTTPException(status_code=422, detail="Lista de muestras vacía")

    rows = [
        dict(
            device_id=s.device_id,
            recorded_at=s.recorded_at,
            bpm=s.bpm,
            rr_estimated_ms=_compute_rr(s.bpm),
            accel_magnitude=s.accel_magnitude,
            gyro_magnitude=s.gyro_magnitude,
            steps_delta=s.steps_delta or 0,
            accuracy=s.accuracy,
        )
        for s in payload.samples
    ]
    # El reloj reenvía lotes cuando no recibe respuesta: lo ya guardado se ignora
    stmt = (
        pg_insert(models.RawSample)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_raw_device_time")
    )
    inserted = db.execute(stmt).rowcount
    db.commit()
    return schemas.IngestResponse(inserted=inserted, duplicates=len(rows) - inserted)


# ---------------------------------------------------------------------------
# POST /api/windows  — ventanas de 1 minuto
# ---------------------------------------------------------------------------
@router.post("/windows", response_model=schemas.IngestResponse)
def ingest_windows(payload: schemas.SleepWindowBatchIn, db: Session = Depends(get_db)):
    """
    Recibe ventanas de 1 minuto ya procesadas por el reloj.
    Si la ventana no trae hrv_rmssd_estimated, el campo queda null.
    """
    if not payload.windows:
        raise HTTPException(status_code=422, detail="Lista de ventanas vacía")

    rows = [
        dict(
            device_id=w.device_id,
            window_start=w.window_start,
            window_end=w.window_end,
            avg_hr=w.avg_hr,
            min_hr=w.min_hr,
            max_hr=w.max_hr,
            std_hr=w.std_hr,
            hrv_rmssd_estimated=w.hrv_rmssd_estimated,
            sample_count=w.sample_count or 0,
            steps=w.steps or 0,
            accel_mean=w.accel_mean,
            activity_state=w.activity_state,
            sleep_state=sleep_logic.corrected_state(w.sleep_state, w.steps, w.avg_hr),
            device_sleep_state=w.sleep_state,
            confidence=w.confidence,
        )
        for w in payload.windows
    ]
    stmt = (
        pg_insert(models.SleepWindow)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_window_device_start")
    )
    inserted = db.execute(stmt).rowcount

    for device_id in {w.device_id for w in payload.windows}:
        starts = [w.window_start for w in payload.windows if w.device_id == device_id]
        sleep_logic.recompute_range(db, device_id, min(starts), max(starts))
    db.commit()

    return schemas.IngestResponse(inserted=inserted, duplicates=len(rows) - inserted)


# ---------------------------------------------------------------------------
# POST /api/sessions  — sesión de sueño completa
# ---------------------------------------------------------------------------
@router.post("/sessions", response_model=schemas.IngestResponse)
def ingest_session(payload: schemas.SleepSessionIn, db: Session = Depends(get_db)):
    """Guarda o actualiza la sesión de sueño de la noche."""
    row = models.SleepSession(
        device_id=payload.device_id,
        session_start=payload.session_start,
        session_end=payload.session_end,
        total_minutes=payload.total_minutes,
        sleep_minutes=payload.sleep_minutes,
        awake_minutes=payload.awake_minutes,
        awakenings=payload.awakenings or 0,
        resting_hr=payload.resting_hr,
        avg_hr=payload.avg_hr,
        hrv_rmssd_avg=payload.hrv_rmssd_avg,
        hrv_rmssd_min=payload.hrv_rmssd_min,
        fatigue_score=payload.fatigue_score,
        fatigue_label=payload.fatigue_label,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    return schemas.IngestResponse(inserted=1)
