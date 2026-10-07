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
    from_raw = {r[0] for r in db.query(models.RawSample.device_id).distinct().all()}
    from_windows = {r[0] for r in db.query(models.SleepWindow.device_id).distinct().all()}
    devices = sorted(from_raw | from_windows)
    return {"devices": devices}


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
    sample_count = (
        db.query(func.count(models.RawSample.id))
        .filter(models.RawSample.device_id == device_id)
        .scalar()
    ) or 0
    window_count = (
        db.query(func.count(models.SleepWindow.id))
        .filter(models.SleepWindow.device_id == device_id)
        .scalar()
    ) or 0
    return {
        "device_id": device_id,
        "last_bpm": last_sample.bpm if last_sample else (last_window.avg_hr if last_window else None),
        "last_bpm_at": (
            last_sample.recorded_at.isoformat() if last_sample
            else (last_window.window_start.isoformat() if last_window else None)
        ),
        "last_sleep_state": last_window.sleep_state if last_window else None,
        "last_hrv": last_window.hrv_rmssd_estimated if last_window else None,
        "last_window_at": last_window.window_start.isoformat() if last_window else None,
        "raw_sample_count": sample_count,
        "window_count": window_count,
    }


# ---------------------------------------------------------------------------
# GET /api/samples  — FC bruta (~1 s) para maximizar datos visibles
# ---------------------------------------------------------------------------
@router.get("/samples")
def get_samples(
    device_id: str,
    from_dt: Optional[datetime] = Query(default=None, alias="from"),
    to_dt: Optional[datetime] = Query(default=None, alias="to"),
    limit: int = Query(default=2000, le=10000),
    db: Session = Depends(get_db),
):
    q = db.query(models.RawSample).filter(models.RawSample.device_id == device_id)
    if from_dt:
        q = q.filter(models.RawSample.recorded_at >= from_dt)
    if to_dt:
        q = q.filter(models.RawSample.recorded_at <= to_dt)
    rows = q.order_by(models.RawSample.recorded_at.desc()).limit(limit).all()
    rows = list(reversed(rows))
    return {
        "device_id": device_id,
        "count": len(rows),
        "samples": [
            {
                "t": r.recorded_at.isoformat() if r.recorded_at else None,
                "bpm": r.bpm,
                "rr": r.rr_estimated_ms,
                "steps": r.steps_delta,
                "accel": r.accel_magnitude,
                "gyro": r.gyro_magnitude,
                "accuracy": r.accuracy,
            }
            for r in rows
        ],
    }


@router.get("/samples/series")
def get_samples_series(
    device_id: str,
    from_dt: Optional[datetime] = Query(default=None, alias="from"),
    to_dt: Optional[datetime] = Query(default=None, alias="to"),
    bucket_seconds: int = Query(default=60, ge=10, le=3600),
    db: Session = Depends(get_db),
):
    """
    Serie agregada (promedio por minuto/bucket) para graficar noches completas
    sin traer 90k puntos al navegador.
    """
    from sqlalchemy import text

    params = {"device_id": device_id, "bucket": bucket_seconds}
    where = ["device_id = :device_id"]
    if from_dt is not None:
        where.append("recorded_at >= :from_dt")
        params["from_dt"] = from_dt
    if to_dt is not None:
        where.append("recorded_at <= :to_dt")
        params["to_dt"] = to_dt
    sql = text(
        f"""
        SELECT
          to_timestamp(floor(extract(epoch from recorded_at) / :bucket) * :bucket) AS bucket_ts,
          AVG(bpm) AS avg_bpm,
          MIN(bpm) AS min_bpm,
          MAX(bpm) AS max_bpm,
          COUNT(*) AS n,
          SUM(COALESCE(steps_delta, 0)) AS steps
        FROM raw_samples
        WHERE {' AND '.join(where)}
        GROUP BY 1
        ORDER BY 1
        """
    )
    rows = db.execute(sql, params).fetchall()
    return {
        "device_id": device_id,
        "bucket_seconds": bucket_seconds,
        "count": len(rows),
        "points": [
            {
                "t": r[0].isoformat() if r[0] else None,
                "bpm": round(float(r[1]), 2) if r[1] is not None else None,
                "min": round(float(r[2]), 2) if r[2] is not None else None,
                "max": round(float(r[3]), 2) if r[3] is not None else None,
                "n": int(r[4] or 0),
                "steps": int(r[5] or 0),
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# GET /api/stats  — conteos rápidos para el dashboard
# ---------------------------------------------------------------------------
@router.get("/stats")
def get_stats(device_id: str, db: Session = Depends(get_db)):
    raw_n = db.query(func.count(models.RawSample.id)).filter(
        models.RawSample.device_id == device_id
    ).scalar() or 0
    win_n = db.query(func.count(models.SleepWindow.id)).filter(
        models.SleepWindow.device_id == device_id
    ).scalar() or 0
    sess_n = db.query(func.count(models.SleepSession.id)).filter(
        models.SleepSession.device_id == device_id
    ).scalar() or 0
    first_raw = (
        db.query(func.min(models.RawSample.recorded_at))
        .filter(models.RawSample.device_id == device_id)
        .scalar()
    )
    last_raw = (
        db.query(func.max(models.RawSample.recorded_at))
        .filter(models.RawSample.device_id == device_id)
        .scalar()
    )
    return {
        "device_id": device_id,
        "raw_samples": raw_n,
        "windows": win_n,
        "sessions": sess_n,
        "first_sample_at": first_raw.isoformat() if first_raw else None,
        "last_sample_at": last_raw.isoformat() if last_raw else None,
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
        "device_state": r.device_sleep_state,
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
