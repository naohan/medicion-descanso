"""
Reglas de sueÃ±o aplicadas en el backend.

El reloj envÃ­a su propia etiqueta por minuto (se guarda en device_sleep_state).
Como no manda acelerÃ³metro, marca como SLEEPING ratos de reposo diurno e incluso
minutos caminando. AquÃ­ se corrige la etiqueta minuto a minuto y se detecta la
sesiÃ³n principal de cada noche, que alimenta daily_summary y sleep_sessions.

ConvenciÃ³n de fechas (hora local LOCAL_TZ):
  - La "noche" del dÃ­a D va de D-1 18:00 a D 18:00: el sueÃ±o cuenta para el dÃ­a
    en que te despiertas.
  - Pasos y FC media del dÃ­a usan el dÃ­a calendario D.
"""
import os
from datetime import date, datetime, time, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

import models

LOCAL_TZ = os.getenv("LOCAL_TZ", "America/Bogota")

MAX_SLEEP_STEPS = 10           # pasos en un minuto por encima de esto = despierto
MAX_SLEEP_HR = 100.0           # FC media del minuto por encima de esto = despierto
NIGHT_START_HOUR = 18
EPISODE_MAX_GAP = 10           # minutos sin dormir que no cortan un episodio
EPISODE_MIN_SLEEP = 20         # minutos dormidos para que un episodio cuente
SESSION_MAX_GAP = 30           # minutos entre episodios que siguen siendo la misma sesiÃ³n
MAIN_SESSION_MIN_SLEEP = 120   # la sesiÃ³n principal necesita al menos 2 h dormidas
AWAKENING_MIN_GAP = 3          # minutos despierto dentro de la sesiÃ³n que cuentan como despertar

AUTO_SESSION_NOTE = "auto"
_EPOCH = datetime(1970, 1, 1)


def corrected_state(state: Optional[str], steps: Optional[int], avg_hr: Optional[float]) -> Optional[str]:
    if state != "SLEEPING":
        return state
    if (steps or 0) > MAX_SLEEP_STEPS or (avg_hr or 0) > MAX_SLEEP_HR:
        return "AWAKE"
    return state


def night_of(local_ts: datetime) -> date:
    return (local_ts + timedelta(hours=24 - NIGHT_START_HOUR)).date()


def dates_touched(db: Session, start_utc: datetime, end_utc: datetime) -> list[date]:
    """DÃ­as (calendario y noche) cuyos resÃºmenes dependen de ventanas en [start, end]."""
    a, b = db.execute(
        text(
            "SELECT CAST(:a AS timestamptz) AT TIME ZONE :tz, "
            "CAST(:b AS timestamptz) AT TIME ZONE :tz"
        ),
        {"a": start_utc, "b": end_utc, "tz": LOCAL_TZ},
    ).one()
    d, last = a.date(), night_of(b)
    out = []
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


# Una fila por minuto local; si hubiera dos ventanas en el mismo minuto se queda la primera
_MINUTES_SQL = text(
    """
    SELECT DISTINCT ON (date_trunc('minute', window_start AT TIME ZONE :tz))
      date_trunc('minute', window_start AT TIME ZONE :tz) AS ts,
      avg_hr, steps, hrv_rmssd_estimated AS hrv, sleep_state
    FROM sleep_windows
    WHERE device_id = :device_id
      AND window_start >= CAST(:a AS timestamp) AT TIME ZONE :tz
      AND window_start <  CAST(:b AS timestamp) AT TIME ZONE :tz
    ORDER BY date_trunc('minute', window_start AT TIME ZONE :tz), id
    """
)


def _minute(r) -> int:
    return int((r.ts - _EPOCH).total_seconds() // 60)


def _group(items, gap: int, key_first, key_last):
    groups, cur = [], []
    for it in items:
        if cur and key_first(it) - key_last(cur[-1]) - 1 > gap:
            groups.append(cur)
            cur = []
        cur.append(it)
    if cur:
        groups.append(cur)
    return groups


def main_session(rows) -> Optional[list]:
    """Minutos SLEEPING de la sesiÃ³n de sueÃ±o mÃ¡s larga, o None si no llega al mÃ­nimo."""
    sleeping = [r for r in rows if r.sleep_state == "SLEEPING"]
    episodes = _group(sleeping, EPISODE_MAX_GAP, _minute, _minute)
    episodes = [e for e in episodes if len(e) >= EPISODE_MIN_SLEEP]
    sessions = _group(
        episodes, SESSION_MAX_GAP,
        key_first=lambda e: _minute(e[0]),
        key_last=lambda e: _minute(e[-1]),
    )
    sessions = [[r for e in s for r in e] for s in sessions]
    if not sessions:
        return None
    best = max(sessions, key=len)
    return best if len(best) >= MAIN_SESSION_MIN_SLEEP else None


def recompute_day(db: Session, device_id: str, d: date) -> None:
    """Recalcula daily_summary y la sesiÃ³n automÃ¡tica del dÃ­a d desde la base de datos."""
    night_start = datetime.combine(d - timedelta(days=1), time(NIGHT_START_HOUR))
    night_end = datetime.combine(d, time(NIGHT_START_HOUR))
    day_start = datetime.combine(d, time())
    day_end = day_start + timedelta(days=1)

    rows = db.execute(
        _MINUTES_SQL,
        {"device_id": device_id, "tz": LOCAL_TZ, "a": night_start, "b": day_end},
    ).all()
    day_rows = [r for r in rows if day_start <= r.ts < day_end]
    night_rows = [r for r in rows if night_start <= r.ts < night_end]

    db.execute(
        text(
            """
            DELETE FROM sleep_sessions
            WHERE device_id = :device_id AND notes = :note
              AND session_start >= CAST(:a AS timestamp) AT TIME ZONE :tz
              AND session_start <  CAST(:b AS timestamp) AT TIME ZONE :tz
            """
        ),
        {"device_id": device_id, "note": AUTO_SESSION_NOTE, "tz": LOCAL_TZ,
         "a": night_start, "b": night_end},
    )

    if not day_rows and not night_rows:
        db.query(models.DailySummary).filter(
            models.DailySummary.device_id == device_id,
            models.DailySummary.summary_date == d,
        ).delete()
        return

    hr_day = [r.avg_hr for r in day_rows if r.avg_hr]
    values = {
        "avg_hr_day": round(sum(hr_day) / len(hr_day), 2) if hr_day else None,
        "steps_total": sum(r.steps or 0 for r in day_rows),
        "sleep_minutes": None,
        "awakenings": None,
        "resting_hr": None,
        "hrv_avg": None,
        "hrv_min": None,
    }

    session = main_session(night_rows)
    if session:
        minutes = [_minute(r) for r in session]
        awakenings = sum(
            1 for a, b in zip(minutes, minutes[1:]) if b - a - 1 >= AWAKENING_MIN_GAP
        )
        total = minutes[-1] - minutes[0] + 1
        hr = [r.avg_hr for r in session if r.avg_hr]
        hrv = [r.hrv for r in session if r.hrv]
        values.update(
            sleep_minutes=len(session),
            awakenings=awakenings,
            resting_hr=round(min(hr), 2) if hr else None,
            hrv_avg=round(sum(hrv) / len(hrv), 2) if hrv else None,
            hrv_min=round(min(hrv), 2) if hrv else None,
        )
        db.execute(
            text(
                """
                INSERT INTO sleep_sessions (
                  device_id, session_start, session_end, total_minutes, sleep_minutes,
                  awake_minutes, awakenings, resting_hr, avg_hr, hrv_rmssd_avg,
                  hrv_rmssd_min, notes, created_at
                ) VALUES (
                  :device_id,
                  CAST(:start AS timestamp) AT TIME ZONE :tz,
                  CAST(:end AS timestamp) AT TIME ZONE :tz,
                  :total, :sleep, :awake, :awakenings, :resting_hr, :avg_hr,
                  :hrv_avg, :hrv_min, :note, now()
                )
                """
            ),
            {
                "device_id": device_id, "tz": LOCAL_TZ,
                "start": session[0].ts, "end": session[-1].ts + timedelta(minutes=1),
                "total": total, "sleep": len(session), "awake": total - len(session),
                "awakenings": awakenings, "resting_hr": values["resting_hr"],
                "avg_hr": round(sum(hr) / len(hr), 2) if hr else None,
                "hrv_avg": values["hrv_avg"], "hrv_min": values["hrv_min"],
                "note": AUTO_SESSION_NOTE,
            },
        )

    stmt = (
        pg_insert(models.DailySummary)
        .values(device_id=device_id, summary_date=d, **values)
        .on_conflict_do_update(constraint="uq_daily_device_date", set_=values)
    )
    db.execute(stmt)


def recompute_range(db: Session, device_id: str, start_utc: datetime, end_utc: datetime) -> None:
    for d in dates_touched(db, start_utc, end_utc):
        recompute_day(db, device_id, d)


def recompute_all(db: Session) -> int:
    """Reconstruye los resÃºmenes de todos los dispositivos. Devuelve cuÃ¡ntos dÃ­as procesÃ³."""
    n = 0
    bounds = db.execute(
        text(
            "SELECT device_id, MIN(window_start), MAX(window_start) "
            "FROM sleep_windows GROUP BY device_id"
        )
    ).all()
    for device_id, first, last in bounds:
        days = dates_touched(db, first, last)
        for d in days:
            recompute_day(db, device_id, d)
        n += len(days)
    return n
