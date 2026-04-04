import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("INICIANDO MOTOR DE FÍSICA FIDO (POSTGRESQL EDITION)...")

# Railway inyecta esta variable automáticamente cuando enlazas Postgres
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")

eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

state_vector = {
    "pos": None, "vel": None, "timestamp": datetime.utcnow(), "source": "INIT"
}

async def fetch_nasa_jpl():
    now = datetime.utcnow()
    t_start = now.strftime('%Y-%m-%d %H:%M')
    t_stop = (now + timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M')
    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text", "COMMAND": "-121", "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "500@399",
        "START_TIME": t_start, "STOP_TIME": t_stop, "STEP_SIZE": "1m",
        "OUT_UNITS": "KM-S", "VEC_TABLE": "2"
    }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, params=params, timeout=10.0)
            if "$$SOE" in r.text:
                lines = r.text.split("$$SOE")[1].split("$$EOE")[0].strip().split('\n')
                for line in lines:
                    if "X =" in line and "Y =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    elif "VX=" in line and "VY=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                        state_vector["pos"] = [x, y, z]
                        state_vector["vel"] = [vx, vy, vz]
                        state_vector["timestamp"] = now
                        state_vector["source"] = "NASA JPL HORIZONS (LIVE)"
                        return True
        except Exception as e:
            print(f"Error NASA: {e}")
    return False

async def physics_loop():
    # Conectamos a PostgreSQL
    conn = await asyncpg.connect(DATABASE_URL)
    print("CONECTADO A POSTGRESQL NUCLEUS")

    await fetch_nasa_jpl() 
    
    async def nasa_updater():
        while True:
            await asyncio.sleep(45)
            await fetch_nasa_jpl()
    asyncio.create_task(nasa_updater())

    while True:
        t = ts.now()
        now = datetime.utcnow()
        
        ast_moon = earth_eph.at(t).observe(moon_eph)
        mx, my, mz = [float(c) for c in ast_moon.position.km]
        ast_sun = earth_eph.at(t).observe(sun_eph)
        sx, sy, sz = [float(c) for c in ast_sun.position.km]

        if state_vector["pos"] is None:
            state_vector["pos"] = [mx * 0.85, my * 0.85, mz * 0.85 + 15000]
            state_vector["vel"] = [0.5, 0.5, 0.5]
            state_vector["source"] = "INTERNAL SIM (FAIL-SAFE)"
            state_vector["timestamp"] = now

        dt = (now - state_vector["timestamp"]).total_seconds()
        ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
        oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
        oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
        
        v_mag = math.sqrt(sum(v**2 for v in state_vector["vel"]))
        if v_mag < 0.1: v_mag = 1.152
        
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)

        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": state_vector["source"],
            "moon": {"x": mx, "y": my, "z": mz},
            "sun_dir": {"x": sx, "y": sy, "z": sz},
            "orion": {"x": ox, "y": oy, "z": oz, "v": v_mag, "dist_e": dist_e, "dist_m": dist_m}
        }
        
        # LA MAGIA DE POSTGRES: Enviamos el JSON por el canal 'telemetry_stream' 
        # sin hacer un INSERT en ninguna tabla. Memoria pura.
        payload = json.dumps(packet)
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", payload)
        
        await asyncio.sleep(0.05) 

if __name__ == "__main__":
    asyncio.run(physics_loop())
