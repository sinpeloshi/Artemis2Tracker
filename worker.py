import asyncio
import json
import math
import os
import httpx
from datetime import datetime, timedelta
from skyfield.api import load
import asyncpg

print("--- [SISTEMA CRÍTICO] INICIANDO CAZADOR DE TELEMETRÍA ARTEMIS II ---")

DATABASE_URL = os.getenv("DATABASE_URL")
eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

# Estado global del vector de la nave
state_vector = {"pos": None, "vel": None, "timestamp": datetime.utcnow(), "source": "INIT"}

async def fetch_nasa_jpl():
    """Intenta perforar el acceso a JPL Horizons usando headers de alta fidelidad"""
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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://ssd.jpl.nasa.gov",
        "Referer": "https://ssd.jpl.nasa.gov/horizons/app.html"
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=20.0) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200 and "$$SOE" in r.text:
                data = r.text.split("$$SOE")[1].split("$$EOE")[0].strip().split('\n')
                x, y, z, vx, vy, vz = 0, 0, 0, 0, 0, 0
                for line in data:
                    if "X =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    if "VX=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                
                state_vector.update({
                    "pos": [x, y, z], "vel": [vx, vy, vz], 
                    "timestamp": now, "source": "NASA DSN LIVE (ARTEMIS II)"
                })
                print(">>> ENLACE DSN ESTABLECIDO: Recibiendo datos reales.")
                return True
            else:
                print(f">>> NASA LINK: Sin datos (Status {r.status_code}). Usando paracaídas inercial.")
        except Exception as e:
            print(f">>> ERROR DE RED: {e}")
    return False

async def nasa_update_loop():
    """Bucle de fondo que intenta reconectar a la NASA cada 45 segundos"""
    while True:
        await fetch_nasa_jpl()
        await asyncio.sleep(45)

async def physics_loop():
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurada.")
        return

    conn = await asyncpg.connect(DATABASE_URL)
    print("CONECTADO AL NÚCLEO POSTGRES")

    # Arrancamos el cazador en segundo plano
    asyncio.create_task(nasa_update_loop())

    while True:
        t = ts.now()
        now = datetime.utcnow()
        
        # Posición de la Luna real (calculada localmente)
        ast_moon = earth_eph.at(t).observe(moon_eph).position.km
        mx, my, mz = [float(c) for c in ast_moon]
        
        # Si no tenemos datos de la NASA aún, activamos el simulador inercial corregido
        if state_vector["pos"] is None:
            # 1. Calculamos la distancia total a la Luna
            dist_luna_total = math.sqrt(mx**2 + my**2 + mz**2)
            
            # 2. Calculamos el VECTOR UNITARIO (la flecha matemática que apunta exactamente a la Luna)
            dir_x = mx / dist_luna_total
            dir_y = my / dist_luna_total
            dir_z = mz / dist_luna_total
            
            # 3. Le aplicamos la velocidad de 1.105 km/s en esa dirección exacta
            velocidad_simulada = 1.105
            vel_x = dir_x * velocidad_simulada
            vel_y = dir_y * velocidad_simulada
            vel_z = dir_z * velocidad_simulada

            # Ubicamos la nave al 72% del camino con la velocidad correcta apuntando a la Luna
            state_vector.update({
                "pos": [mx * 0.72, my * 0.72, mz * 0.72], 
                "vel": [vel_x, vel_y, vel_z], 
                "source": "BUSCANDO SEÑAL DSN (SIM)", 
                "timestamp": now
            })

        # Extrapolación de movimiento (Dead Reckoning)
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
        
        # Inyectamos el paquete a la base de datos para que el main.py lo vea
        await conn.execute("SELECT pg_notify('telemetry_stream', $1)", json.dumps(packet))
        await asyncio.sleep(0.05) # 20 FPS

if __name__ == "__main__":
    asyncio.run(physics_loop())
