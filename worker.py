"""
worker.py — Artemis II Telemetry Worker
Fuente de datos: JPL Horizons API (ssd.jpl.nasa.gov)
  · Orion / Integrity  → COMMAND='-1024'
  · Luna               → COMMAND='301'

Estrategia:
  - refresh_loop()  : cada 60 s consulta Horizons → guarda state vectors reales
  - telemetry_loop(): cada 0.5 s extrapola posición con velocidad actual → pg_notify
"""

import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta, timezone
import asyncpg

# ── Constantes de misión ─────────────────────────────────────────────────────
# Despegue real: 1 de abril de 2026, 6:35 PM EDT = 22:35:00 UTC
LAUNCH_DATE = datetime(2026, 4, 1, 22, 35, 0, tzinfo=timezone.utc)

DATABASE_URL      = os.getenv("DATABASE_ARTEMIS")
HORIZONS_URL      = "https://ssd.jpl.nasa.gov/api/horizons.api"
HORIZONS_INTERVAL = 60    # segundos entre refreshes de la API
TELEMETRY_FPS     = 2     # paquetes por segundo (sleep = 0.5 s)

# ── Cache compartido entre loops ─────────────────────────────────────────────
_cache: dict = {
    "ship": dict(x=0.0, y=0.0, z=0.0, vx=0.0, vy=0.0, vz=0.0, t=None),
    "moon": dict(x=0.0, y=0.0, z=0.0, t=None),
    "source": "INIT",
}


# ── Utilidades ───────────────────────────────────────────────────────────────

def to_jd(dt: datetime) -> float:
    """Convierte datetime UTC → Fecha Juliana (JD)."""
    epoch = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return 2451545.0 + (dt - epoch).total_seconds() / 86400.0


def parse_vectors(text: str) -> list[dict]:
    """
    Parsea la tabla de vectores en formato CSV de JPL Horizons.
    Columnas entre $$SOE y $$EOE:
      JDTDB, Calendar Date (TDB), X, Y, Z, VX, VY, VZ  [+LT, RG, RR si VEC_TABLE=3]
    """
    rows, active = [], False
    for line in text.splitlines():
        if "$$SOE" in line:
            active = True
            continue
        if "$$EOE" in line:
            break
        if not active:
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 8:
            continue
        try:
            rows.append({
                "jd": float(parts[0]),
                "x":  float(parts[2]),
                "y":  float(parts[3]),
                "z":  float(parts[4]),
                "vx": float(parts[5]),
                "vy": float(parts[6]),
                "vz": float(parts[7]),
            })
        except (ValueError, IndexError):
            pass
    return rows


def interp_state(rows: list[dict], jd: float) -> dict | None:
    """
    Interpolación lineal entre dos state vectors.
    Si el JD está fuera del rango, extrapola desde el punto más cercano
    usando la velocidad (integración de primer orden).
    """
    if not rows:
        return None
    if len(rows) == 1:
        # Solo hay un punto: extrapolar
        near = rows[0]
        dt = (jd - near["jd"]) * 86400.0
        return {
            "x": near["x"] + near["vx"] * dt,
            "y": near["y"] + near["vy"] * dt,
            "z": near["z"] + near["vz"] * dt,
            "vx": near["vx"], "vy": near["vy"], "vz": near["vz"],
        }

    # Buscar el par de puntos que rodea el JD objetivo
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if a["jd"] <= jd <= b["jd"]:
            t = (jd - a["jd"]) / (b["jd"] - a["jd"])
            return {k: a[k] + t * (b[k] - a[k]) for k in ("x", "y", "z", "vx", "vy", "vz")}

    # JD fuera del rango: extrapolar desde el punto más cercano
    near = min(rows, key=lambda r: abs(r["jd"] - jd))
    dt = (jd - near["jd"]) * 86400.0
    return {
        "x":  near["x"]  + near["vx"] * dt,
        "y":  near["y"]  + near["vy"] * dt,
        "z":  near["z"]  + near["vz"] * dt,
        "vx": near["vx"], "vy": near["vy"], "vz": near["vz"],
    }


# ── Consulta a JPL Horizons ──────────────────────────────────────────────────

async def fetch_vectors(client: httpx.AsyncClient, command: str, now: datetime) -> list[dict]:
    """
    Consulta JPL Horizons para obtener state vectors de un cuerpo dado.
    Ventana: [now-3min, now+5min] con paso de 2 minutos → 4-5 puntos para interpolar.
    """
    t0 = (now - timedelta(minutes=3)).strftime("%Y-%b-%d %H:%M")
    t1 = (now + timedelta(minutes=5)).strftime("%Y-%b-%d %H:%M")

    params = {
        "format":     "text",
        "COMMAND":    f"'{command}'",
        "OBJ_DATA":   "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "CENTER":     "'500@399'",   # geocéntrico, J2000
        "START_TIME": f"'{t0}'",
        "STOP_TIME":  f"'{t1}'",
        "STEP_SIZE":  "'2m'",
        "OUT_UNITS":  "'KM-S'",
        "REF_SYSTEM": "'J2000'",
        "VEC_TABLE":  "'2'",         # posición + velocidad
        "CSV_FORMAT": "'YES'",
    }

    resp = await client.get(HORIZONS_URL, params=params, timeout=20.0)
    resp.raise_for_status()

    rows = parse_vectors(resp.text)
    if not rows:
        # Loguear fragmento de respuesta para debug si no hay datos
        snippet = resp.text[:400].replace("\n", " ")
        raise ValueError(f"Sin datos en respuesta Horizons ({command}): {snippet}")

    return rows


# ── Loop de refresco de Horizons (background) ────────────────────────────────

async def refresh_loop(client: httpx.AsyncClient) -> None:
    """
    Cada HORIZONS_INTERVAL segundos consulta la API de JPL para Orion y la Luna
    en paralelo y actualiza el cache global.
    """
    while True:
        try:
            now = datetime.now(timezone.utc)

            ship_rows, moon_rows = await asyncio.gather(
                fetch_vectors(client, "-1024", now),   # Orion Integrity (Artemis II)
                fetch_vectors(client, "301",   now),   # Luna
            )

            jd = to_jd(now)
            ship_state = interp_state(ship_rows, jd)
            moon_state = interp_state(moon_rows, jd)

            if ship_state:
                _cache["ship"].update(ship_state)
                _cache["ship"]["t"] = now

            if moon_state:
                _cache["moon"].update({k: moon_state[k] for k in ("x", "y", "z")})
                _cache["moon"]["t"] = now

            _cache["source"] = "JPL HORIZONS"

            dist_e = math.sqrt(ship_state["x"]**2 + ship_state["y"]**2 + ship_state["z"]**2)
            speed  = math.sqrt(ship_state["vx"]**2 + ship_state["vy"]**2 + ship_state["vz"]**2)
            print(f"[{now:%H:%M:%S} UTC] Horizons OK | dist_tierra={dist_e:,.0f} km | v={speed:.3f} km/s")

        except Exception as exc:
            _cache["source"] = f"CACHE ({exc.__class__.__name__})"
            print(f"[{datetime.now(timezone.utc):%H:%M:%S}] Error Horizons: {exc}")

        await asyncio.sleep(HORIZONS_INTERVAL)


# ── Loop de telemetría (broadcast) ───────────────────────────────────────────

async def telemetry_loop(conn: asyncpg.Connection) -> None:
    """
    Cada 0.5 s extrapola la posición actual usando la última velocidad conocida
    y emite el paquete de telemetría vía pg_notify → WebSocket.
    """
    while True:
        now = datetime.now(timezone.utc)

        # Extrapolación de posición desde el último fix de Horizons
        s  = _cache["ship"]
        dt = (now - s["t"]).total_seconds() if s["t"] else 0.0
        ox = s["x"] + s["vx"] * dt
        oy = s["y"] + s["vy"] * dt
        oz = s["z"] + s["vz"] * dt
        vx, vy, vz = s["vx"], s["vy"], s["vz"]
        speed = math.sqrt(vx**2 + vy**2 + vz**2)

        # Posición de la Luna (geocéntrica)
        mx, my, mz = _cache["moon"]["x"], _cache["moon"]["y"], _cache["moon"]["z"]

        # Distancias
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx - ox)**2 + (my - oy)**2 + (mz - oz)**2) if mx else 0.0

        # Coordenadas selenocéntricas
        lx, ly, lz = ox - mx, oy - my, oz - mz

        # MET (Mission Elapsed Time) — nunca negativo
        met_s = max(0.0, (now - LAUNCH_DATE).total_seconds())

        packet = {
            "time":   now.strftime("%H:%M:%S.%f")[:-3] + " UTC",
            "source": _cache["source"],
            "met": (
                f"T+ {int(met_s // 86400):02d}:"
                f"{int(met_s % 86400 // 3600):02d}:"
                f"{int(met_s % 3600 // 60):02d}:"
                f"{int(met_s % 60):02d}"
            ),
            "moon": {"x": mx, "y": my, "z": mz},
            "ship": {
                # Posición J2000 geocéntrica (km)
                "x": ox, "y": oy, "z": oz,
                # Velocidad (km/s)
                "vx": vx, "vy": vy, "vz": vz,
                "v": speed,
                # Distancias
                "dist_e": dist_e,
                "dist_m": dist_m,
                # Latencia de luz hacia Tierra
                "light_e": dist_e / 299792.458,
                # Coordenadas selenocéntricas
                "lat_m": math.degrees(math.asin(max(-1.0, min(1.0, lz / dist_m)))) if dist_m > 1 else 0.0,
                "lon_m": math.degrees(math.atan2(ly, lx)) % 360 if dist_m > 1 else 0.0,
            },
        }

        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(1.0 / TELEMETRY_FPS)


# ── Punto de entrada ─────────────────────────────────────────────────────────

async def main() -> None:
    if not DATABASE_URL:
        print("❌  Variable de entorno DATABASE_ARTEMIS no definida — saliendo.")
        return

    conn = await asyncpg.connect(DATABASE_URL)

    # Tabla de persistencia (para recuperar último estado si el worker reinicia)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS mission_state (
            id          INT PRIMARY KEY,
            pos_x       FLOAT,
            pos_y       FLOAT,
            pos_z       FLOAT,
            last_update TIMESTAMPTZ
        )
    """)

    async with httpx.AsyncClient() as client:
        # ── Fetch inicial antes de empezar a emitir ──────────────────────────
        try:
            now = datetime.now(timezone.utc)
            sv, mv = await asyncio.gather(
                fetch_vectors(client, "-1024", now),
                fetch_vectors(client, "301",   now),
            )
            jd = to_jd(now)
            s, m = interp_state(sv, jd), interp_state(mv, jd)
            if s:
                _cache["ship"].update(s)
                _cache["ship"]["t"] = now
            if m:
                _cache["moon"].update({k: m[k] for k in ("x", "y", "z")})
                _cache["moon"]["t"] = now
            _cache["source"] = "JPL HORIZONS"
            dist = math.sqrt(s["x"]**2 + s["y"]**2 + s["z"]**2)
            print(f"✅  Fetch inicial OK — Orion a {dist:,.0f} km de la Tierra")
        except Exception as exc:
            print(f"⚠️   Fetch inicial fallido: {exc} — emitiendo con cache vacío")

        # ── Lanzar loops en paralelo ─────────────────────────────────────────
        try:
            await asyncio.gather(
                refresh_loop(client),
                telemetry_loop(conn),
            )
        finally:
            await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
