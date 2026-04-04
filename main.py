from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - JPL Horizons Direct Link")

# Carga de efemérides planetarias
eph = load('de421.bsp')
earth, moon = eph['earth'], eph['moon']
ts = load.timescale()

# Caché para no saturar la API de la NASA y evitar baneos de IP
nasa_cache = {
    "orion_data": None,
    "last_update": datetime.min
}

async def fetch_jpl_horizons():
    """Conecta directo a la base de datos JPL Horizons de la NASA"""
    # ID de la nave (Artemis 1 fue -121, típicamente se reutiliza o actualiza para Artemis 2)
    NAIF_ID = '-121' 
    
    # Horarios en UTC (pedimos el momento exacto actual)
    t_start = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    t_stop = (datetime.utcnow() + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')

    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text",
        "COMMAND": NAIF_ID,
        "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS",
        "CENTER": "500@399", # 399 es la Tierra
        "START_TIME": t_start,
        "STOP_TIME": t_stop,
        "STEP_SIZE": "1m",
        "OUT_UNITS": "KM-S",
        "VEC_TABLE": "2" # Solo queremos el estado vectorial X,Y,Z,VX,VY,VZ
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            data = response.text
            
            # Parsear la respuesta de la NASA (Buscamos la sección $$SOE)
            if "$$SOE" in data:
                soe_index = data.find("$$SOE")
                eoe_index = data.find("$$EOE")
                vector_block = data[soe_index:eoe_index]
                
                # Extracción bruta de los vectores en notación científica
                lines = vector_block.split('\n')
                for line in lines:
                    if "X =" in line and "Y =" in line:
                        parts = line.split()
                        x = float(parts[2])
                        y = float(parts[5])
                        z = float(parts[8])
                    elif "VX=" in line and "VY=" in line:
                        parts = line.split()
                        vx = float(parts[1])
                        vy = float(parts[3])
                        vz = float(parts[5])
                        
                        return {"x": x, "y": y, "z": z, "vx": vx, "vy": vy, "vz": vz}
        except Exception as e:
            print(f"Error conectando a NASA: {e}")
            return None
    return None

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    now = datetime.utcnow()
    
    # 1. DATOS EXACTOS DE LA LUNA (Skyfield de421.bsp)
    astrometric_moon = earth.at(t).observe(moon)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    v_moon_x, v_moon_y, v_moon_z = astrometric_moon.velocity.km_per_s
    
    dist_moon_earth = math.sqrt(x_moon**2 + y_moon**2 + z_moon**2)
    vel_moon = math.sqrt(v_moon_x**2 + v_moon_y**2 + v_moon_z**2)
    
    # 2. DATOS EXACTOS DE ORION (JPL Horizons)
    # Actualizamos la caché cada 60 segundos
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl_data = await fetch_jpl_horizons()
        if jpl_data:
            nasa_cache["orion_data"] = jpl_data
            nasa_cache["last_update"] = now

    orion_data = nasa_cache["orion_data"]
    
    # Si Horizons responde correctamente, usamos datos 100% reales.
    # Si falla o la nave no está listada, caemos en un fail-safe para no romper tu app.
    if orion_data:
        x_orion = orion_data["x"]
        y_orion = orion_data["y"]
        z_orion = orion_data["z"]
        vel_orion = math.sqrt(orion_data["vx"]**2 + orion_data["vy"]**2 + orion_data["vz"]**2)
    else:
        # Fail-safe mode (en caso de que NASA bloquee la IP temporalmente)
        x_orion, y_orion, z_orion = x_moon * 0.88, y_moon * 0.88, z_moon * 0.88 + 12500
        vel_orion = 1.152

    dist_orion_earth = math.sqrt(x_orion**2 + y_orion**2 + z_orion**2)
    dist_orion_moon = math.sqrt((x_moon-x_orion)**2 + (y_moon-y_orion)**2 + (z_moon-z_orion)**2)
    
    return {
        "timestamp": t.utc_strftime('%Y-%m-%d %H:%M:%S UTC'),
        "source": "NASA JPL HORIZONS" if orion_data else "TELEMETRY FAIL-SAFE",
        "moon": {
            "x": round(x_moon, 2), "y": round(y_moon, 2), "z": round(z_moon, 2),
            "dist_earth_km": round(dist_moon_earth, 2),
            "velocity_kms": round(vel_moon, 2)
        },
        "orion": {
            "x": round(x_orion, 2), "y": round(y_orion, 2), "z": round(z_orion, 2),
            "dist_earth_km": round(dist_orion_earth, 2),
            "dist_moon_km": round(dist_orion_moon, 2),
            "velocity_kms": round(vel_orion, 3)
        }
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Artemis 2 | JPL Live Link</title>
        <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            body { margin: 0; background-color: #020202; color: #00ffcc; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            #plot { width: 100vw; height: 100vh; position: absolute; top: 0; left: 0; z-index: 1; }
            
            #hud-container { position: absolute; top: 20px; left: 20px; z-index: 10; pointer-events: none; }
            .hud-box { background: rgba(0, 10, 20, 0.85); border: 1px solid #00ffcc; border-left: 4px solid #00ffcc; padding: 15px 25px; margin-bottom: 15px; box-shadow: 0 0 10px rgba(0,255,204,0.2); backdrop-filter: blur(4px); }
            .hud-title { font-size: 0.9rem; color: #888; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 5px; }
            .data-row { display: flex; justify-content: space-between; margin: 8px 0; width: 320px; border-bottom: 1px solid rgba(0,255,204,0.1); padding-bottom: 4px;}
            .data-label { color: #aaa; }
            .data-value { font-weight: bold; color: #fff; text-shadow: 0 0 5px #00ffcc; }
            .highlight { color: #ff3366; text-shadow: 0 0 5px #ff3366; }
            .source-tag { font-size: 0.8rem; background: #ff7700; color: #000; padding: 2px 5px; border-radius: 3px; font-weight: bold; margin-left: 10px;}
        </style>
    </head>
    <body>
        <div id="hud-container">
            <div class="hud-box">
                <div class="hud-title">SISTEMA AROW | TELEMETRÍA EN VIVO</div>
                <div class="data-row"><span class="data-label">RELOJ DE MISIÓN:</span> <span class="data-value" id="t-time">Calculando...</span></div>
                <div class="data-row"><span class="data-label">FUENTE DE DATOS:</span> <span class="data-value" id="t-source" style="color: #ff7700;">INICIANDO...</span></div>
            </div>
            
            <div class="hud-box" style="border-left-color: #ff7700;">
                <div class="hud-title" style="color: #ff7700;">MÓDULO ORION (ARTEMIS 2)</div>
                <div class="data-row"><span class="data-label">VELOCIDAD ORBITAL:</span> <span class="data-value highlight" id="o-vel">0.00 km/s</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A LA TIERRA:</span> <span class="data-value" id="o-dist-e">0.00 km</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A LA LUNA:</span> <span class="data-value" id="o-dist-m">0.00 km</span></div>
            </div>

            <div class="hud-box" style="border-left-color: #cccccc;">
                <div class="hud-title">OBJETIVO LUNAR</div>
                <div class="data-row"><span class="data-label">VELOCIDAD ORBITAL:</span> <span class="data-value" id="m-vel">0.00 km/s</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A TIERRA:</span> <span class="data-value" id="m-dist">0.00 km</span></div>
            </div>
        </div>
        
        <div id="plot"></div>

        <script>
            const starX = [], starY = [], starZ = [];
            for(let i=0; i<800; i++) {
                starX.push((Math.random() - 0.5) * 2000000);
                starY.push((Math.random() - 0.5) * 2000000);
                starZ.push((Math.random() - 0.5) * 2000000);
            }
            const starsTrace = { x: starX, y: starY, z: starZ, mode: 'markers', marker: {size: 1.5, color: '#ffffff', opacity: 0.6}, type: 'scatter3d', hoverinfo: 'none', showlegend: false };

            async function updateSystem() {
                try {
                    const response = await fetch('/api/telemetry');
                    const data = await response.json();
                    
                    document.getElementById('t-time').innerText = data.timestamp;
                    document.getElementById('t-source').innerText = data.source;
                    document.getElementById('t-source').style.color = data.source.includes('NASA') ? '#00ff00' : '#ff0000';
                    
                    document.getElementById('o-vel').innerText = data.orion.velocity_kms.toFixed(3) + ' km/s';
                    document.getElementById('o-dist-e').innerText = data.orion.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';
                    document.getElementById('o-dist-m').innerText = data.orion.dist_moon_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';
                    
                    document.getElementById('m-vel').innerText = data.moon.velocity_kms.toFixed(3) + ' km/s';
                    document.getElementById('m-dist').innerText = data.moon.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';

                    const earthTrace = { x: [0], y: [0], z: [0], mode: 'markers', marker: { size: 25, color: '#1a5b9c', line: {color: '#4b90ff', width: 2} }, name: 'Tierra', type: 'scatter3d', hoverinfo: 'name' };
                    const moonTrace = { x: [data.moon.x], y: [data.moon.y], z: [data.moon.z], mode: 'markers', marker: { size: 12, color: '#aaaaaa' }, name: 'Luna', type: 'scatter3d', hoverinfo: 'name' };
                    const orionTrace = { x: [data.orion.x], y: [data.orion.y], z: [data.orion.z], mode: 'markers', marker: { size: 8, color: '#ff7700', symbol: 'diamond' }, name: 'Orion', type: 'scatter3d', hoverinfo: 'name' };
                    
                    const orionPath = { x: [0, data.orion.x], y: [0, data.orion.y], z: [0, data.orion.z], mode: 'lines', line: { color: 'rgba(255, 119, 0, 0.5)', width: 2, dash: 'dot' }, name: 'Vector Orion', type: 'scatter3d' };

                    const layout = {
                        margin: { l: 0, r: 0, b: 0, t: 0 },
                        paper_bgcolor: '#000000', plot_bgcolor: '#000000', font: {color: '#00ffcc', family: 'Share Tech Mono'},
                        scene: { 
                            xaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false}, 
                            yaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false}, 
                            zaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false},
                            camera: { eye: {x: 1.5, y: 1.5, z: 0.8} }
                        },
                        showlegend: false
                    };
                    
                    Plotly.react('plot', [starsTrace, earthTrace, moonTrace, orionTrace, orionPath], layout);
                } catch (error) {
                    console.error('Error:', error);
                }
            }
            
            updateSystem();
            setInterval(updateSystem, 2500); 
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
