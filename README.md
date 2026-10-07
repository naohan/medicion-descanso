# Serenity — Backend Sueño & Fatiga

Backend FastAPI + PostgreSQL para monitorear datos del Xiaomi Watch 2.

## Requisitos

- Python 3.11 o superior
- PostgreSQL 15 o superior (descarga desde https://www.postgresql.org/download/windows/)
- pgAdmin (opcional, para ver las tablas visualmente)

---

## 1. Instalar PostgreSQL

1. Descarga e instala PostgreSQL para Windows.
2. Durante la instalación elige contraseña para el usuario `postgres` (anótala).
3. Abre **pgAdmin** → crea una base de datos llamada `serenity_fatiga`.

---

## 2. Configurar el backend

```powershell
cd backend

# Crear entorno virtual
python -m venv venv
.\venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Crear archivo .env con tu contraseña de PostgreSQL
Copy-Item .env.example .env
notepad .env
```

Edita `.env` y pon tu contraseña:
```
DATABASE_URL=postgresql://postgres:TU_CONTRASEÑA@localhost:5432/serenity_fatiga
```

---

## 3. Crear las tablas

```powershell
python init_db.py
```

Salida esperada:
```
Creando tablas en PostgreSQL…
Listo. Tablas creadas:
  ✓ raw_samples
  ✓ sleep_windows
  ✓ sleep_sessions
  ✓ daily_summary
```

### Actualizar una base creada antes de la deduplicación

Las bases antiguas no impedían guardar dos veces la misma muestra o ventana
cuando el reloj reenviaba un lote. Para limpiarlas (haz antes una copia):

```powershell
pg_dump -U postgres -F c -f serenity_backup.dump serenity_fatiga
python migrate_dedupe.py --dry-run   # muestra qué cambiaría, sin guardar
python migrate_dedupe.py
```

El script borra duplicados, crea las restricciones `UNIQUE`, corrige los minutos
SLEEPING imposibles (más de 10 pasos o FC > 100) y reconstruye `daily_summary`
y las sesiones automáticas. Se puede ejecutar más de una vez.

---

## 4. Iniciar el servidor

```powershell
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

- API docs: http://localhost:8000/docs
- Dashboard: http://localhost:8000/
- Health check: http://localhost:8000/health

### Proteger la API (obligatorio si el servidor es público)

Sin clave, cualquiera que conozca la dirección puede leer los datos de salud e
insertar datos falsos. Genera una clave y ponla en el `.env` del servidor:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```
API_KEY=la_clave_generada
```

Con `API_KEY` definida, todas las rutas `/api/...` exigen la cabecera
`X-API-Key: la_clave_generada`:

- **Reloj / app emisora:** debe añadir esa cabecera en cada `POST`.
- **Dashboard:** escribe la clave en el campo *Clave*; se guarda solo en tu navegador.

`/health`, `/docs` y el HTML del dashboard siguen abiertos (no contienen datos).

---

## 5. Endpoints principales

### Recibir datos desde el reloj

| Método | Ruta | Descripción |
|--------|------|-------------|
| POST | `/api/samples` | Muestras brutas de FC (hasta 500 por petición) |
| POST | `/api/windows` | Ventanas de 1 minuto procesadas |
| POST | `/api/sessions` | Sesión de sueño completa |

### Consultar desde el dashboard

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/devices` | Lista dispositivos registrados |
| GET | `/api/windows?device_id=X&from=ISO` | Ventanas para gráficos |
| GET | `/api/hrv?device_id=X&from=ISO` | HRV estimado |
| GET | `/api/sessions?device_id=X` | Sesiones de sueño |
| GET | `/api/summary?device_id=X&days=7` | Resumen diario |
| GET | `/api/latest?device_id=X` | Último estado |

---

## 6. Ejemplo de envío desde el reloj (JSON)

### Muestras de FC
```json
POST /api/samples
X-API-Key: la_clave_generada   ← solo si el servidor define API_KEY
{
  "samples": [
    {
      "device_id": "xiaomi-watch2",
      "recorded_at": "2026-09-08T02:30:00Z",
      "bpm": 62.5,
      "accel_magnitude": 9.73,
      "gyro_magnitude": 0.003,
      "steps_delta": 0,
      "accuracy": "HIGH"
    }
  ]
}
```

### Ventanas de 1 minuto
```json
POST /api/windows
{
  "windows": [
    {
      "device_id": "xiaomi-watch2",
      "window_start": "2026-09-08T02:30:00Z",
      "window_end": "2026-09-08T02:31:00Z",
      "avg_hr": 63.2,
      "min_hr": 60.1,
      "max_hr": 66.8,
      "std_hr": 1.8,
      "hrv_rmssd_estimated": 28.4,
      "sample_count": 58,
      "steps": 0,
      "activity_state": "ASLEEP",
      "sleep_state": "SLEEPING",
      "confidence": 0.86
    }
  ]
}
```

---

## 7. Estructura del proyecto

```
app-fatiga/
  backend/
    main.py          ← FastAPI app principal
    auth.py          ← clave API opcional (X-API-Key)
    database.py      ← conexión SQLAlchemy
    models.py        ← tablas ORM (4 tablas)
    schemas.py       ← validación Pydantic
    init_db.py       ← crea las tablas en PostgreSQL
    migrate_dedupe.py ← limpia duplicados en bases antiguas
    sleep_logic.py   ← corrección de minutos y detección de la noche
    requirements.txt
    .env             ← DATABASE_URL, LOCAL_TZ, API_KEY (no subir a git)
    .env.example     ← plantilla
    routers/
      ingest.py      ← POST /api/samples, /api/windows, /api/sessions
      query.py       ← GET endpoints para el dashboard
  dashboard/
    index.html       ← dashboard web con Chart.js
```

---

## Notas sobre el sueño

El reloj etiqueta cada minuto, pero sin acelerómetro confunde reposo con sueño.
El backend guarda esa etiqueta en `device_sleep_state` y en `sleep_state` la corrige:
un minuto con más de 10 pasos o FC media > 100 pasa a `AWAKE`.

El sueño de cada día es la **sesión principal** de la noche (18:00 del día anterior
a 18:00 de ese día, hora `LOCAL_TZ`): episodios de ≥ 20 min dormidos, unidos si los
separan ≤ 30 min, y la sesión más larga solo cuenta si suma ≥ 2 h. Se guarda en
`daily_summary` y en `sleep_sessions` (con `notes = 'auto'`). Los umbrales están en
`sleep_logic.py`.

## Notas sobre HRV

El Watch 2 no expone IBI (inter-beat interval) crudo.
El campo `hrv_rmssd_estimated` es una **aproximación** calculada así:
1. Cada BPM se convierte a RR: `RR = 60000 / BPM` ms
2. Se calculan las diferencias sucesivas: `ΔRR[i] = RR[i+1] - RR[i]`
3. `RMSSD = √(media de ΔRR²)`

Útil para **tendencias personales** (tu HRV de hoy vs. tu media),
no para comparaciones clínicas absolutas.
