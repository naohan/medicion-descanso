"""
GET endpoints: el dashboard web consulta los datos aquí.

Rutas:
  GET /api/devices                       → lista de device_id conocidos
  GET /api/windows?device_id=&from=&to=  → ventanas de 1 minuto (para gráficos)
  GET /api/sessions?device_id=           → sesiones de sueño
  GET /api/summary?device_id=&days=      → resumen diario (últimos N días)
  GET /api/hrv?device_id=&from=&to=      → HRV estimado por ventana
  GET /api/latest?device_id=             → último estado conocido
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from database import get_db
import models

router = APIRouter(prefix="/api", tags=["query"])


# ---------------------------------------------------------------------------
# GET /api/devices
# ---------------------------------------------------------------------------
@router.get("/devices")
def list_devices(db: Session = Depends(get_db)):
    """Devuelve todos los device_id que han enviado datos."""
    rows = db.query(models.RawSample.device_id).distinct().all()
    return {"devices": [r[0] for r in rows]}


# ---------------------------------------------------------------------------
# GET /api/windows
# ---------------------------------------------------------------------------
@router.get("/windows")
def get_windows(
    device_id: str,
    from_dt: Optional[datetime] = Query(default=None, alias="from"),
    to_dt: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=1440, le=5000),  # max 5000 ventanas (~3.5 días)
    db: Session = Depends(get_db),
):
    """
    Devuelve ventanas de 1 minuto.
    Útil para dibujar FC, HRV estimado y estado sueño/vigilia en el tiempo.
    """
    q = (
        db.query(models.SleepWindow)
        .filter(models.SleepWindow.device_id == device_id)
    )
    if from_dt:
        q = q.filter(models.SleepWindow.window_start >= from_dt)
    if to_dt:
        q = q.filter(models.SleepWindow.window_start <= to_dt)

    rows = q.order_by(models.SleepWindow.window_start).limit(limit).all()
    return {
        "device_id": device_id,
        "count": len(rows),
        "windows": [_window_to_dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# GET /api/hrv
# ---------------------------------------------------------------------------
@router.get("/hrv")
def get_hrv(
    device_id: str,
    from_dt: Optional[datetime] = Query(default=None, alias="from"),
    to_dt: Optional[datetime] = Query(default=None, alias="to"),
    db: Session = Depends(get_db),
):
    """
    Devuelve solo el HRV estimado por ventana (más ligero para gráficos de HRV).
    """
    q = (
        db.query(
            models.SleepWindow.window_start,
            models.SleepWindow.hrv_rmssd_estimated,
            models.SleepWindow.sleep_state,
        )
        .filter(
            models.SleepWindow.device_id == device_id,
            models.SleepWindow.hrv_rmssd_estimated.isnot(None),
        )
    )
    if from_dt:
        q = q.filter(models.SleepWindow.window_start >= from_dt)
    if to_dt:
        q = q.filter(models.SleepWindow.window_start <= to_dt)

    rows = q.order_by(models.SleepWindow.window_start).all()
    return {
        "device_id": device_id,
        "count": len(rows),
        "hrv": [
            {
                "t": r[0].isoformat(),
                "hrv": round(r[1], 2) if r[1] else None,
                "state": r[2],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/sessions
# ---------------------------------------------------------------------------
@router.get("/sessions")
def get_sessions(
    device_id: str,
    limit: int = Query(default=30, le=365),
    db: Session = Depends(get_db),
):
    """Devuelve las últimas N sesiones de sueño."""
    rows = (
        db.query(models.SleepSession)
        .filter(models.SleepSession.device_id == device_id)
        .order_by(models.SleepSession.session_start.desc())
        .limit(limit)
        .all()
    )
    return {
        "device_id": device_id,
        "count": len(rows),
        "sessions": [_session_to_dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# GET /api/summary
# ---------------------------------------------------------------------------
@router.get("/summary")
def get_summary(
    device_id: str,
    days: int = Query(default=7, le=90),
    db: Session = Depends(get_db),
):
    """Devuelve el resumen de los últimos N días."""
    rows = (
        db.query(models.DailySummary)
        .filter(models.DailySummary.device_id == device_id)
        .order_by(models.DailySummary.summary_date.desc())
        .limit(days)
        .all()
    )
    return {
        "device_id": device_id,
        "days": len(rows),
        "summary": [_daily_to_dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# GET /api/latest
# ---------------------------------------------------------------------------
@router.get("/latest")
def get_latest(device_id: str, db: Session = Depends(get_db)):
    """Devuelve el estado más reciente del dispositivo (última muestra + última ventana)."""
    last_sample = (
        db.query(models.RawSample)
        .filter(models.RawSample.device_id == device_id)
        .order_by(models.RawSample.recorded_at.desc())
        .first()
    )
    last_window = (
        db.query(models.SleepWindow)
        .filter(models.SleepWindow.device_id == device_id)
        .order_by(models.SleepWindow.window_start.desc())
        .first()
    )
    return {
        "device_id": device_id,
        "last_bpm": last_sample.bpm if last_sample else None,
        "last_bpm_at": last_sample.recorded_at.isoformat() if last_sample else None,
        "last_sleep_state": last_window.sleep_state if last_window else None,
        "last_hrv": last_window.hrv_rmssd_estimated if last_window else None,
        "last_window_at": last_window.window_start.isoformat() if last_window else None,
    }


# ---------------------------------------------------------------------------
# Serializers privados
# ---------------------------------------------------------------------------
def _window_to_dict(r: models.SleepWindow) -> dict:
    return {
        "id": r.id,
        "t": r.window_start.isoformat(),
        "t_end": r.window_end.isoformat() if r.window_end else None,
        "avg_hr": r.avg_hr,
        "min_hr": r.min_hr,
        "max_hr": r.max_hr,
        "std_hr": r.std_hr,
        "hrv": r.hrv_rmssd_estimated,
        "samples": r.sample_count,
        "steps": r.steps,
        "accel": r.accel_mean,
        "activity": r.activity_state,
        "state": r.sleep_state,
        "conf": r.confidence,
    }


def _session_to_dict(r: models.SleepSession) -> dict:
    return {
        "id": r.id,
        "start": r.session_start.isoformat() if r.session_start else None,
        "end": r.session_end.isoformat() if r.session_end else None,
        "total_min": r.total_minutes,
        "sleep_min": r.sleep_minutes,
        "awake_min": r.awake_minutes,
        "awakenings": r.awakenings,
        "resting_hr": r.resting_hr,
        "avg_hr": r.avg_hr,
        "hrv_avg": r.hrv_rmssd_avg,
        "hrv_min": r.hrv_rmssd_min,
        "fatigue_score": r.fatigue_score,
        "fatigue_label": r.fatigue_label,
    }


def _daily_to_dict(r: models.DailySummary) -> dict:
    return {
        "date": r.summary_date.isoformat() if r.summary_date else None,
        "sleep_min": r.sleep_minutes,
        "awakenings": r.awakenings,
        "resting_hr": r.resting_hr,
        "avg_hr": r.avg_hr_day,
        "hrv_avg": r.hrv_avg,
        "hrv_min": r.hrv_min,
        "steps": r.steps_total,
        "fatigue_score": r.fatigue_score,
        "fatigue_label": r.fatigue_label,
    }
