import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("--- [SISTEMA MAESTRO] INICIANDO SINCRONIZACIÓN AROW / NASA ARTEMIS II ---")

DATABASE_URL = os.getenv("DATABASE_ARTEMIS")
eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

LAUNCH_DATE = datetime(2026, 4, 1, 0, 0, 0)
state_vector = {"pos": None, "vel": None, "timestamp": datetime.utcnow(), "source": "INIT"}

async def fetch_arow_telemetry():
    """Captura telemetría real desde el endpoint de AROW (Artemis Real-time Orbit Website)"""
    # Endpoint oficial que usa la NASA para su dashboard público
    url = "https://www.nasa.gov/specials/trackartemis/telemetry/telemetry.json"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "application/json"
    }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                data = r.json()
                # AROW entrega coordenadas en KM y KM/S directamente
                # Buscamos los datos de la cápsula Orion (habitualmente bajo el key 'orion')
                v = data.get('orion', {})
                if v:
                    state_vector.update({
                        "pos": [v['x'], v['y'], v['z']],
                        "vel": [v['vx'], v['vy'], v['vz']],
                        "timestamp": datetime.utcnow(),
                        "source": "NASA AROW LIVE"
                    })
                    return True
        except Exception as e:
            print(f"Error capturando AROW: {e}")
    return False

async def update_loop():
    while True:
        await fetch_arow_telemetry()
        await asyncio.sleep(30) # AROW actualiza cada 30-60 segundos

async def physics_loop():
    if not DATABASE_URL:
        print("ERROR: DATABASE_ARTEMIS no configurada.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    asyncio.create_task(update_loop())

    while True:
        t = ts.now()
        now = datetime.utcnow()
        
        ast_moon = earth_eph.at(t).observe(moon_eph).position.km
        mx, my, mz = [float(c) for c in ast_moon]
        ast_sun = earth_eph.at(t).observe(sun_eph).position.km
        sx, sy, sz = [float(c) for c in ast_sun]

        # MODO FALLBACK: Si AROW no responde, usamos el simulador inercial
        if state_vector["pos"] is None:
            dist_luna_total = math.sqrt(mx**2 + my**2 + mz**2)
            dir_x, dir_y, dir_z = mx / dist_luna_total, my / dist_luna_total, mz / dist_luna_total
            state_vector.update({
                "pos": [mx * 0.72, my * 0.72, mz * 0.72], 
                "vel": [dir_x * 1.105, dir_y * 1.105, dir_z * 1.105], 
                "source": "SIMULACIÓN INERCIAL", "timestamp": now
            })

        # Extrapolación de movimiento (Dead Reckoning entre actualizaciones de la NASA)
        dt = (now - state_vector["timestamp"]).total_seconds()
        ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
        oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
        oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
        ovx, ovy, ovz = state_vector["vel"][0], state_vector["vel"][1], state_vector["vel"][2]
        
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)
        v_mag = math.sqrt(ovx**2 + ovy**2 + ovz**2)
        
        # Matemática Selenocéntrica
        lx, ly, lz = ox - mx, oy - my, oz - mz
        v_moon = earth_eph.at(t).observe(moon_eph).velocity.km_per_s
        vmx, vmy, vmz = [float(c) for c in v_moon]
        lvx, lvy, lvz = ovx - vmx, ovy - vmy, ovz - vmz
        v_rel_m = math.sqrt(lvx**2 + lvy**2 + lvz**2)
        lat_m = math.degrees(math.asin(lz / dist_m)) if dist_m > 0 else 0
        lon_m = math.degrees(math.atan2(ly, lx)) % 360

        # MET
        delta = now - LAUNCH_DATE
        met_str = f"T+ {delta.days:02d}:{delta.seconds // 3600:02d}:{(delta.seconds // 60) % 60:02d}:{delta.seconds % 60:02d}"

        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": state_vector["source"],
            "met": met_str,
            "moon": {"x": mx, "y": my, "z": mz},
            "ship": {
                "x": ox, "y": oy, "z": oz, "vx": ovx, "vy": ovy, "vz": ovz, "v": v_mag,
                "dist_e": dist_e, "dist_m": dist_m, "v_rel_m": v_rel_m,
                "lat_m": lat_m, "lon_m": lon_m, "light_e": dist_e / 299792.458,
                "mach": v_mag * 3600 / 1234.8, "ra": math.degrees(math.atan2(oy, ox)) % 360,
                "dec": math.degrees(math.asin(oz / dist_e)) if dist_e > 0 else 0
            }
        }
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(physics_loop())
