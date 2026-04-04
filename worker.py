import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("--- INICIANDO MASTER PHYSICS ENGINE (ARTEMIS II) ---")

DATABASE_URL = os.getenv("DATABASE_URL")
eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

state_vector = {"pos": None, "vel": None, "timestamp": datetime.utcnow(), "source": "INIT"}

async def fetch_nasa_jpl():
    """Perforadora de Firewall de la NASA JPL"""
    now = datetime.utcnow()
    t_start = now.strftime('%Y-%m-%d %H:%M')
    t_stop = (now + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
    
    params = {
        "format": "text", "COMMAND": "'-121'", "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'VECTORS'", "CENTER": "'500@399'",
        "START_TIME": f"'{t_start}'", "STOP_TIME": f"'{t_stop}'",
        "STEP_SIZE": "'1m'", "OUT_UNITS": "'KM-S'", "VEC_TABLE": "'2'"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "*/*"
    }

    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            r = await client.get("https://ssd.jpl.nasa.gov/api/horizons.api", params=params, headers=headers, timeout=15.0)
            if "$$SOE" in r.text:
                data = r.text.split("$$SOE")[1].split("$$EOE")[0].strip().split('\n')
                x, y, z, vx, vy, vz = 0, 0, 0, 0, 0, 0
                for line in data:
                    if "X =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    if "VX=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                
                state_vector.update({"pos": [x, y, z], "vel": [vx, vy, vz], "timestamp": now, "source": "NASA JPL LIVE (ARTEMIS II)"})
                return True
        except: pass
    return False

async def physics_loop():
    conn = await asyncpg.connect(DATABASE_URL)
    asyncio.create_task((lambda: (asyncio.sleep(45) or fetch_nasa_jpl()))()) # Loop NASA

    while True:
        t = ts.now()
        now = datetime.utcnow()
        ast_moon = earth_eph.at(t).observe(moon_eph).position.km
        mx, my, mz = [float(c) for c in ast_moon]
        
        if state_vector["pos"] is None:
            # Fallback cinemático (Día 4 de misión aprox)
            state_vector.update({"pos": [mx * 0.7, my * 0.7, mz * 0.7], "vel": [1.1, 0.1, -0.05], "source": "BUSCANDO SEÑAL DSN...", "timestamp": now})

        dt = (now - state_vector["timestamp"]).total_seconds()
        ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
        oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
        oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
        
        v_mag = math.sqrt(sum(v**2 for v in state_vector["vel"]))
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)
        
        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": state_vector["source"],
            "moon": {"x": mx, "y": my, "z": mz},
            "ship": {
                "x": ox, "y": oy, "z": oz, "v": v_mag, "dist_e": dist_e, "dist_m": dist_m,
                "light": dist_e / 299792.458, "mach": v_mag * 3600 / 1234.8,
                "dec": math.degrees(math.asin(oz / dist_e)) if dist_e > 0 else 0,
                "ra": math.degrees(math.atan2(oy, ox)) % 360
            }
        }
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(physics_loop())
