import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("--- [SISTEMA CRÍTICO] INICIANDO MASTER PHYSICS ENGINE (V4) ---")

DATABASE_URL = os.getenv("DATABASE_URL")
eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

# Fecha de despegue de Artemis II (Real: 1 de Abril 2026, 00:00 UTC)
LAUNCH_DATE = datetime(2026, 4, 1, 0, 0, 0)

state_vector = {"pos": None, "vel": None, "timestamp": datetime.utcnow(), "source": "INIT"}

async def fetch_nasa_jpl():
    """Perforadora de Firewall de JPL con disfraz de alta fidelidad"""
    now = datetime.utcnow()
    t_start = now.strftime('%Y-%m-%d %H:%M')
    t_stop = (now + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
    
    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text", "COMMAND": "'-121'", "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'VECTORS'", "CENTER": "'500@399'",
        "START_TIME": f"'{t_start}'", "STOP_TIME": f"'{t_stop}'",
        "STEP_SIZE": "'1m'", "OUT_UNITS": "'KM-S'", "VEC_TABLE": "'2'"
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "*/*", "Connection": "keep-alive"
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200 and "$$SOE" in r.text:
                data = r.text.split("$$SOE")[1].split("$$EOE")[0].strip().split('\n')
                x, y, z, vx, vy, vz = 0, 0, 0, 0, 0, 0
                for line in data:
                    if "X =" in line:
                        p = line.split(); x, y, z = float(p[2]), float(p[5]), float(p[8])
                    if "VX=" in line:
                        p = line.split(); vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                
                state_vector.update({
                    "pos": [x, y, z], "vel": [vx, vy, vz], 
                    "timestamp": now, "source": "NASA JPL LIVE"
                })
                return True
        except: pass
    return False

async def nasa_update_loop():
    while True:
        await fetch_nasa_jpl()
        await asyncio.sleep(45)

async def physics_loop():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurada.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    asyncio.create_task(nasa_update_loop())

    while True:
        t = ts.now()
        now = datetime.utcnow()
        
        # Posiciones astronómicas reales
        ast_moon = earth_eph.at(t).observe(moon_eph).position.km
        mx, my, mz = [float(c) for c in ast_moon]
        ast_sun = earth_eph.at(t).observe(sun_eph).position.km
        sx, sy, sz = [float(c) for c in ast_sun]

        if state_vector["pos"] is None:
            # Fallback cinemático (Día 4-5 de misión)
            dist_luna_total = math.sqrt(mx**2 + my**2 + mz**2)
            dir_x, dir_y, dir_z = mx / dist_luna_total, my / dist_luna_total, mz / dist_luna_total
            state_vector.update({
                "pos": [mx * 0.72, my * 0.72, mz * 0.72], 
                "vel": [dir_x * 1.105, dir_y * 1.105, dir_z * 1.105], 
                "source": "SIMULACIÓN INERCIAL", "timestamp": now
            })

        dt = (now - state_vector["timestamp"]).total_seconds()
        
        # Dead Reckoning inercial
        ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
        oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
        oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
        ovx, ovy, ovz = state_vector["vel"][0], state_vector["vel"][1], state_vector["vel"][2]
        
        # Métrica Geocéntrica Básica
        dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
        dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)
        v_mag = math.sqrt(ovx**2 + ovy**2 + ovz**2)
        
        # --- NUEVA MATEMÁTICA SELENOCÉNTRICA (Luna) ---
        # 1. Vector Posición Relativo a la Luna (L-J2000)
        lx, ly, lz = ox - mx, oy - my, oz - mz
        
        # 2. Vector Velocidad Relativo a la Luna
        # Necesitamos la velocidad de la Luna (vM) para calcular vRel = vShip - vM.
        # Skyfield lo da en AU/día, convertimos a km/s.
        v_moon = earth_eph.at(t).observe(moon_eph).velocity.km_per_s
        vmx, vmy, vmz = [float(c) for c in v_moon]
        lvx, lvy, lvz = ovx - vmx, ovy - vmy, ovz - vmz
        v_rel_luna = math.sqrt(lvx**2 + lvy**2 + lvz**2)

        # 3. Coordenadas Selenográficas (Lat/Lon) - Aproximación J2000
        lon_luna = math.degrees(math.atan2(ly, lx)) % 360
        lat_luna = math.degrees(math.asin(lz / dist_m))

        # --- FÍSICA AMBIENTAL AVANZADA ---
        # 1. Ángulo de Fase Lunar (visto por la nave)
        # Vector Sol-Luna y Vector Nave-Luna. Ángulo entre ellos.
        smx, smy, smz = mx - sx, my - sy, mz - sz # Vector Sol->Luna
        dist_sm = math.sqrt(smx**2 + smy**2 + smz**2)
        v_sol_luna_u = [smx/dist_sm, smy/dist_sm, smz/dist_sm]
        v_nave_luna_u = [lx/dist_m, ly/dist_m, lz/dist_m]
        
        # Producto punto para el ángulo
        dot_phase = sum(s*n for s,n in zip(v_sol_luna_u, v_nave_luna_u))
        phase_angle = math.degrees(math.acos(max(-1, min(1, dot_phase))))

        # CÁLCULO MET
        delta = now - LAUNCH_DATE
        met_str = f"T+ {delta.days:02d}:{delta.seconds // 3600:02d}:{(delta.seconds // 60) % 60:02d}:{delta.seconds % 60:02d}"

        # FASE DE VUELO LÓGICA
        flight_phase = "OUTBOUND COAST"
        if dist_e < 15000: flight_phase = "EARTH ORBIT"
        elif dist_m < 80000: flight_phase = "LUNAR APPROACH"
        elif dist_m < 3500: flight_phase = "PERILUNE INSERT."

        packet = {
            "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
            "source": state_vector["source"],
            "met": met_str,
            "phase": flight_phase,
            "moon": {"x": mx, "y": my, "z": mz},
            "ship": {
                # Datos Inerciales J2000
                "x": ox, "y": oy, "z": oz, 
                "vx": ovx, "vy": ovy, "vz": ovz, "v": v_mag,
                # Datos Relativos a la Tierra
                "dist_e": dist_e, "light_e": dist_e / 299792.458,
                # Datos Relativos a la Luna (Selocéntricos)
                "dist_m": dist_m, "v_rel_m": v_rel_luna,
                "lat_m": lat_luna, "lon_m": lon_luna,
                # Datos Ambientales
                "phase_angle": phase_angle,
                "mach": v_mag * 3600 / 1234.8,
                "dec": math.degrees(math.asin(oz / dist_e)) if dist_e > 0 else 0,
                "ra": math.degrees(math.atan2(oy, ox)) % 360
            }
        }
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.05)

if __name__ == "__main__":
    asyncio.run(physics_loop())
