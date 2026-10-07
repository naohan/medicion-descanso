"""
Migración única para bases creadas antes de la deduplicación.

  1. Añade sleep_windows.device_sleep_state (etiqueta original del reloj).
  2. Borra filas duplicadas de raw_samples y sleep_windows (conserva la más antigua).
  3. Crea las restricciones UNIQUE que impiden nuevos duplicados.
  4. Corrige sleep_state con las reglas de sleep_logic.
  5. Reconstruye daily_summary y las sesiones automáticas.

Uso (haz antes una copia con pg_dump):
    python migrate_dedupe.py --dry-run   # muestra qué haría y deshace todo
    python migrate_dedupe.py
"""
import sys

from sqlalchemy import text

from database import SessionLocal
import sleep_logic

DUPLICATES = {
    "raw_samples": "device_id, recorded_at",
    "sleep_windows": "device_id, window_start",
}
CONSTRAINTS = {
    "uq_raw_device_time": ("raw_samples", "device_id, recorded_at"),
    "uq_window_device_start": ("sleep_windows", "device_id, window_start"),
}


def main(dry_run: bool) -> None:
    db = SessionLocal()
    try:
        db.execute(text(
            "ALTER TABLE sleep_windows ADD COLUMN IF NOT EXISTS device_sleep_state VARCHAR(16)"
        ))
        n = db.execute(text(
            "UPDATE sleep_windows SET device_sleep_state = sleep_state "
            "WHERE device_sleep_state IS NULL"
        )).rowcount
        print(f"device_sleep_state copiado en {n} ventanas")

        for table, cols in DUPLICATES.items():
            n = db.execute(text(f"""
                DELETE FROM {table} WHERE id IN (
                  SELECT id FROM (
                    SELECT id, row_number() OVER (PARTITION BY {cols} ORDER BY id) AS rn
                    FROM {table}
                  ) t WHERE rn > 1
                )
            """)).rowcount
            print(f"{table}: {n} duplicados borrados")

        for name, (table, cols) in CONSTRAINTS.items():
            exists = db.execute(
                text("SELECT 1 FROM pg_constraint WHERE conname = :n"), {"n": name}
            ).first()
            if not exists:
                db.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({cols})"))
                print(f"{table}: restricción {name} creada")

        n = db.execute(
            text("""
                UPDATE sleep_windows SET sleep_state = 'AWAKE'
                WHERE device_sleep_state = 'SLEEPING' AND sleep_state = 'SLEEPING'
                  AND (COALESCE(steps, 0) > :steps OR COALESCE(avg_hr, 0) > :hr)
            """),
            {"steps": sleep_logic.MAX_SLEEP_STEPS, "hr": sleep_logic.MAX_SLEEP_HR},
        ).rowcount
        print(f"{n} minutos SLEEPING pasados a AWAKE (pasos > "
              f"{sleep_logic.MAX_SLEEP_STEPS} o FC > {sleep_logic.MAX_SLEEP_HR:g})")

        db.execute(text("DELETE FROM daily_summary"))
        db.execute(
            text("DELETE FROM sleep_sessions WHERE notes = :note"),
            {"note": sleep_logic.AUTO_SESSION_NOTE},
        )
        days = sleep_logic.recompute_all(db)
        print(f"Resumen diario reconstruido ({days} días procesados):")
        for r in db.execute(text("""
            SELECT device_id, summary_date, sleep_minutes, awakenings, resting_hr, steps_total
            FROM daily_summary ORDER BY device_id, summary_date
        """)):
            sleep = f"{r.sleep_minutes // 60}h {r.sleep_minutes % 60:02d}m" if r.sleep_minutes else "—"
            print(f"  {r.device_id} {r.summary_date}: sueño {sleep}, "
                  f"despertares {r.awakenings if r.awakenings is not None else '—'}, "
                  f"FC reposo {r.resting_hr or '—'}, pasos {r.steps_total}")

        if dry_run:
            db.rollback()
            print("\n--dry-run: no se guardó ningún cambio")
        else:
            db.commit()
            print("\nMigración aplicada")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
