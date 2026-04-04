import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("INICIANDO MOTOR FÍSICO (TRACKING LRO - DATOS REALES)...")

DATABASE_URL = os.getenv("DATABASE_URL")

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
    
    # ID -85: Lunar Reconnaissance Orbiter (Misión REAL activa en la Luna)
    params = {
        "format": "text", "COMMAND": "-85", "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "399",
        "START_TIME": t_start, "STOP_TIME": t_stop, "STEP_SIZE": "1m",
        "OUT_UNITS": "KM-S", "VEC_TABLE": "2"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
    }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, params=params, headers=headers, timeout=15.0)
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
                        state_vector["source"] = "NASA JPL HORIZONS (LIVE LRO DATA)"
                        print("¡DATOS REALES RECIBIDOS DE LA NASA!")
                        return True
        except Exception as e:
            print(f"NASA Link Error: {e}")
    return False

async def physics_loop():
    conn = await asyncpg.connect(DATABASE_URL)
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
        sx, sy, sz = [float(c) for c in earth_eph.at(t).observe(sun_eph).position.km]

        if state_vector["pos"] is None:
            state_vector["pos"] = [mx, my, mz + 5000] # Orbitando cerca de la luna
            state_vector["vel"] = [1.5, 0.0, 0.0]
            state_vector["source"] = "BUSCANDO SEÑAL..."
            state_vector["timestamp"] = now

        dt = (now - state_vector["timestamp"]).total_seconds()
        ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
        oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
        oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
        
        v_mag = math.sqrt(sum(v**2 for v in state_vector["vel"]))
        
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)
        
        # MÁS DATOS REALES:
        light_time = dist_e / 299792.458 # Segundos que tarda la señal en llegar a la Tierra
        mach_speed = v_mag * 3600 / 1234.8 # Velocidad relativa en Mach
        
        # Matemáticas para Ascensión Recta y Declinación
        declination = math.degrees(math.asin(oz / dist_e))
        right_ascension = math.degrees(math.atan2(oy, ox)) % 360

        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": state_vector["source"],
            "moon": {"x": mx, "y": my, "z": mz},
            "sun_dir": {"x": sx, "y": sy, "z": sz},
            "ship": {
                "x": ox, "y": oy, "z": oz, 
                "v": v_mag, 
                "dist_e": dist_e, 
                "dist_m": dist_m,
                "light_time": light_time,
                "mach": mach_speed,
                "dec": declination,
                "ra": right_ascension
            }
        }
        
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.05) 

if __name__ == "__main__":
    asyncio.run(physics_loop())
