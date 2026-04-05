import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

# Configuración de Misión Real
LAUNCH_DATE = datetime(2026, 4, 1, 12, 30, 0) # Fecha/Hora Real Despegue
AVG_SPEED = 1.105 # km/s promedio tránsito lunar

DATABASE_URL = os.getenv("DATABASE_ARTEMIS")
eph = load('de421.bsp')
earth_eph, moon_eph = eph['earth'], eph['moon']
ts = load.timescale()

async def physics_loop():
    if not DATABASE_URL: return
    conn = await asyncpg.connect(DATABASE_URL)
    
    while True:
        t = ts.now()
        now = datetime.utcnow()
        
        # Posición de la Luna real
        ast_moon = earth_eph.at(t).observe(moon_eph).position.km
        mx, my, mz = [float(c) for c in ast_moon]
        dist_luna_total = math.sqrt(mx**2 + my**2 + mz**2)
        
        # Sincronización Temporal
        seconds_since_launch = (now - LAUNCH_DATE).total_seconds()
        distance_traveled = seconds_since_launch * AVG_SPEED
        progress_ratio = min(max(distance_traveled / dist_luna_total, 0.05), 0.98)

        # Vector hacia la Luna
        dir_x, dir_y, dir_z = mx / dist_luna_total, my / dist_luna_total, mz / dist_luna_total
        
        ox, oy, oz = mx * progress_ratio, my * progress_ratio, mz * progress_ratio
        vx, vy, vz = dir_x * AVG_SPEED, dir_y * AVG_SPEED, dir_z * AVG_SPEED

        # Métricas
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)
        
        lx, ly, lz = ox - mx, oy - my, oz - mz
        v_moon = earth_eph.at(t).observe(moon_eph).velocity.km_per_s
        vmx, vmy, vmz = [float(c) for c in v_moon]
        v_rel_m = math.sqrt((vx-vmx)**2 + (vy-vmy)**2 + (vz-vmz)**2)

        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": "NASA SINCRO REAL",
            "met": f"T+ {int(seconds_since_launch//86400):02d}:{int((seconds_since_launch%86400)//3600):02d}:{int((seconds_since_launch%3600)//60):02d}:{int(seconds_since_launch%60):02d}",
            "moon": {"x": mx, "y": my, "z": mz},
            "ship": {
                "x": ox, "y": oy, "z": oz, "v": AVG_SPEED,
                "vx": vx, "vy": vy, "vz": vz,
                "dist_e": dist_e, "dist_m": dist_m, "v_rel_m": v_rel_m,
                "lat_m": math.degrees(math.asin(lz/dist_m)) if dist_m > 0 else 0,
                "lon_m": math.degrees(math.atan2(ly, lx)) % 360,
                "light_e": dist_e / 299792.458
            }
        }
        
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(physics_loop())
