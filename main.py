from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - NASA Grade MOC")

# Motor Astronómico Core
eph = load('de421.bsp')
earth, moon = eph['earth'], eph['moon']
ts = load.timescale()

# Memoria Caché para Base de Datos JPL
nasa_cache = {
    "orion_data": None,
    "last_update": datetime.min
}

async def fetch_jpl_horizons():
    """Conexión Directa a la Red de Espacio Profundo (DSN / JPL)"""
    NAIF_ID = '-121' 
    t_start = datetime.utcnow().strftime('%Y-%m-%d %H:%M')
    t_stop = (datetime.utcnow() + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')

    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text", "COMMAND": NAIF_ID, "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "500@399",
        "START_TIME": t_start, "STOP_TIME": t_stop, "STEP_SIZE": "1m",
        "OUT_UNITS": "KM-S", "VEC_TABLE": "2"
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=8.0)
            data = response.text
            if "$$SOE" in data:
                soe_index = data.find("$$SOE")
                eoe_index = data.find("$$EOE")
                block = data[soe_index:eoe_index]
                lines = block.split('\n')
                for line in lines:
                    if "X =" in line and "Y =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    elif "VX=" in line and "VY=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                        return {"x": x, "y": y, "z": z, "vx": vx, "vy": vy, "vz": vz}
        except Exception:
            return None
    return None

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    now = datetime.utcnow()
    
    # ASTROMETRÍA PRECISA
    astrometric_moon = earth.at(t).observe(moon)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    v_moon_x, v_moon_y, v_moon_z = astrometric_moon.velocity.km_per_s
    
    dist_moon_earth = math.sqrt(x_moon**2 + y_moon**2 + z_moon**2)
    vel_moon = math.sqrt(v_moon_x**2 + v_moon_y**2 + v_moon_z**2)
    
    # ENLACE JPL HORIZONS
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl_data = await fetch_jpl_horizons()
        if jpl_data:
            nasa_cache["orion_data"] = jpl_data
            nasa_cache["last_update"] = now

    orion = nasa_cache["orion_data"]
    
    if orion:
        x_orion, y_orion, z_orion = orion["x"], orion["y"], orion["z"]
        vel_orion = math.sqrt(orion["vx"]**2 + orion["vy"]**2 + orion["vz"]**2)
        source = "DSN/JPL HORIZONS LOCK"
        status = "NOMINAL"
    else:
        # Interpolación hiperbólica simulada (Fallback)
        x_orion, y_orion, z_orion = x_moon * 0.88, y_moon * 0.88, z_moon * 0.88 + 12500
        vel_orion = 1.152 + (math.sin(now.second / 10) * 0.005) # Microfluctuación realista
        source = "INTERNAL TELEMETRY CALC"
        status = "DEGRADED (API TIMEOUT)"

    dist_orion_earth = math.sqrt(x_orion**2 + y_orion**2 + z_orion**2)
    dist_orion_moon = math.sqrt((x_moon-x_orion)**2 + (y_moon-y_orion)**2 + (z_moon-z_orion)**2)
    
    return {
        "sys_time": t.utc_strftime('%Y-%jT%H:%M:%S.000Z'), # Formato NASA (Día del año)
        "signal": {"source": source, "status": status},
        "moon": {"x": x_moon, "y": y_moon, "z": z_moon, "dist_km": dist_moon_earth, "v_kms": vel_moon},
        "orion": {"x": x_orion, "y": y_orion, "z": z_orion, "dist_earth_km": dist_orion_earth, "dist_moon_km": dist_orion_moon, "v_kms": vel_orion}
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>NASA MOC | Artemis Flight Dynamics</title>
        <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Roboto+Mono:wght@300;500;700&display=swap');
            
            :root { --bg: #050505; --panel: #0a0a0a; --neon-blue: #00e5ff; --neon-orange: #ff3d00; --neon-green: #00e676; --grid-color: rgba(0, 229, 255, 0.1); }
            
            body, html { margin: 0; padding: 0; height: 100%; background-color: var(--bg); color: #fff; font-family: 'Roboto Mono', monospace; overflow: hidden; }
            
            /* Scanlines overlay para efecto monitor viejo */
            body::after { content: " "; display: block; position: absolute; top: 0; left: 0; bottom: 0; right: 0; background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%), linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06)); z-index: 2; background-size: 100% 2px, 3px 100%; pointer-events: none; }
            
            #dashboard { display: grid; grid-template-columns: 350px 1fr; grid-template-rows: 60px 1fr 250px; height: 100vh; gap: 2px; background-color: #333; padding: 2px; box-sizing: border-box; position: relative; z-index: 1;}
            
            .panel { background-color: var(--panel); position: relative; overflow: hidden; }
            .header { grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; padding: 0 20px; border-bottom: 2px solid var(--neon-blue); background: #00111a;}
            
            h1 { font-size: 1.2rem; color: var(--neon-blue); text-transform: uppercase; letter-spacing: 2px; margin: 0; text-shadow: 0 0 10px rgba(0, 229, 255, 0.5); }
            .blinking-dot { display: inline-block; width: 10px; height: 10px; background-color: var(--neon-green); border-radius: 50%; margin-right: 10px; animation: blink 1s infinite; box-shadow: 0 0 8px var(--neon-green); }
            @keyframes blink { 0% {opacity: 1;} 50% {opacity: 0.2;} 100% {opacity: 1;} }

            #sidebar { grid-column: 1; grid-row: 2 / 4; border-right: 1px solid var(--neon-blue); padding: 15px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto;}
            #main-3d { grid-column: 2; grid-row: 2; border-bottom: 1px solid var(--neon-blue); }
            #telemetry-chart { grid-column: 2; grid-row: 3; }

            .data-group { border: 1px solid rgba(255,255,255,0.1); padding: 10px; background: rgba(255,255,255,0.02); }
            .data-group h3 { margin: 0 0 10px 0; font-size: 0.85rem; color: #888; border-bottom: 1px dotted #555; padding-bottom: 5px; }
            .metric { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px; }
            .metric .label { color: #aaa; }
            .metric .val { font-weight: 700; color: var(--neon-orange); text-shadow: 0 0 5px rgba(255, 61, 0, 0.4); }
            .metric .val.green { color: var(--neon-green); text-shadow: 0 0 5px rgba(0, 230, 118, 0.4); }

            #raw-terminal { font-size: 0.7rem; color: #555; height: 150px; overflow-y: hidden; margin-top: auto; border-top: 1px solid #333; padding-top: 10px;}
            #raw-terminal div { margin-bottom: 2px; }
        </style>
    </head>
    <body>
        <div id="dashboard">
            <div class="panel header">
                <div><span class="blinking-dot"></span><h1>Artemis II | FIDO Flight Dynamics Console</h1></div>
                <div id="sys-time" style="color: var(--neon-blue); font-weight: bold;">T-00:00:00.000Z</div>
            </div>

            <div class="panel" id="sidebar">
                <div class="data-group">
                    <h3>UPLINK STATUS</h3>
                    <div class="metric"><span class="label">SOURCE:</span> <span class="val green" id="v-source">--</span></div>
                    <div class="metric"><span class="label">INTEGRITY:</span> <span class="val green" id="v-status">--</span></div>
                </div>

                <div class="data-group">
                    <h3 style="color: var(--neon-orange);">ORION CAPSULE</h3>
                    <div class="metric"><span class="label">INERTIAL VEL:</span> <span class="val" id="o-vel">0.000 km/s</span></div>
                    <div class="metric"><span class="label">ALT (EARTH):</span> <span class="val" id="o-dist-e">0.00 km</span></div>
                    <div class="metric"><span class="label">DIST (MOON):</span> <span class="val" id="o-dist-m">0.00 km</span></div>
                    <div class="metric"><span class="label">X-VECTOR:</span> <span class="val" id="o-x" style="color:#fff;">0.0</span></div>
                    <div class="metric"><span class="label">Y-VECTOR:</span> <span class="val" id="o-y" style="color:#fff;">0.0</span></div>
                    <div class="metric"><span class="label">Z-VECTOR:</span> <span class="val" id="o-z" style="color:#fff;">0.0</span></div>
                </div>

                <div class="data-group">
                    <h3 style="color: #aaa;">LUNAR TARGET</h3>
                    <div class="metric"><span class="label">ORBITAL VEL:</span> <span class="val" style="color:#fff;" id="m-vel">0.000 km/s</span></div>
                    <div class="metric"><span class="label">EARTH DIST:</span> <span class="val" style="color:#fff;" id="m-dist">0.00 km</span></div>
                </div>

                <div id="raw-terminal"></div>
            </div>

            <div class="panel" id="main-3d"></div>
            <div class="panel" id="telemetry-chart"></div>
        </div>

        <script>
            // Arrays para historial de vuelo
            const timeHistory = [];
            const velocityHistory = [];
            const orionTrailX = [], orionTrailY = [], orionTrailZ = [];
            
            // Estrellas de fondo
            const stX = [], stY = [], stZ = [];
            for(let i=0; i<500; i++) { stX.push((Math.random() - 0.5) * 2e6); stY.push((Math.random() - 0.5) * 2e6); stZ.push((Math.random() - 0.5) * 2e6); }

            async function updateMOC() {
                try {
                    const res = await fetch('/api/telemetry');
                    const d = await res.json();
                    
                    // 1. Actualizar Textos
                    document.getElementById('sys-time').innerText = d.sys_time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('v-status').innerText = d.signal.status;
                    document.getElementById('v-status').style.color = d.signal.status === 'NOMINAL' ? '#00e676' : '#ffea00';
                    
                    document.getElementById('o-vel').innerText = d.orion.v_kms.toFixed(4) + ' km/s';
                    document.getElementById('o-dist-e').innerText = d.orion.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';
                    document.getElementById('o-dist-m').innerText = d.orion.dist_moon_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';
                    document.getElementById('o-x').innerText = d.orion.x.toFixed(1);
                    document.getElementById('o-y').innerText = d.orion.y.toFixed(1);
                    document.getElementById('o-z').innerText = d.orion.z.toFixed(1);
                    
                    document.getElementById('m-vel').innerText = d.moon.v_kms.toFixed(4) + ' km/s';
                    document.getElementById('m-dist').innerText = d.moon.dist_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';

                    // Terminal simulada
                    const term = document.getElementById('raw-terminal');
                    term.innerHTML = `<div>> RECV PKT: ${d.sys_time}</div>` + term.innerHTML;
                    if(term.childElementCount > 8) term.removeChild(term.lastChild);

                    // 2. Lógica de Memoria (Trail y Gráficos)
                    const nowStr = d.sys_time.split('T')[1].substring(0,8);
                    timeHistory.push(nowStr);
                    velocityHistory.push(d.orion.v_kms);
                    
                    orionTrailX.push(d.orion.x);
                    orionTrailY.push(d.orion.y);
                    orionTrailZ.push(d.orion.z);

                    // Mantener arrays con límite
                    if(timeHistory.length > 50) { timeHistory.shift(); velocityHistory.shift(); }
                    if(orionTrailX.length > 100) { orionTrailX.shift(); orionTrailY.shift(); orionTrailZ.shift(); }

                    // 3. Render 3D (Main Panel)
                    const layout3D = {
                        margin: { l: 0, r: 0, b: 0, t: 0 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
                        scene: { 
                            xaxis: {visible: false}, yaxis: {visible: false}, zaxis: {visible: false},
                            camera: { eye: {x: 1.2, y: 1.2, z: 0.6} }
                        }, showlegend: false
                    };
                    
                    const traces3D = [
                        { x: stX, y: stY, z: stZ, mode: 'markers', marker: {size: 1, color: '#444'}, type: 'scatter3d', hoverinfo: 'none' }, // Stars
                        { x: [0], y: [0], z: [0], mode: 'markers', marker: { size: 20, color: '#00e5ff' }, type: 'scatter3d', name: 'Earth' },
                        { x: [d.moon.x], y: [d.moon.y], z: [d.moon.z], mode: 'markers', marker: { size: 10, color: '#aaa' }, type: 'scatter3d', name: 'Moon' },
                        { x: [d.orion.x], y: [d.orion.y], z: [d.orion.z], mode: 'markers', marker: { size: 8, color: '#ff3d00', symbol: 'diamond' }, type: 'scatter3d', name: 'Orion' },
                        { x: orionTrailX, y: orionTrailY, z: orionTrailZ, mode: 'lines', line: { color: '#ff3d00', width: 2 }, type: 'scatter3d', name: 'Trajectory' } // El Trail!
                    ];
                    Plotly.react('main-3d', traces3D, layout3D, {displayModeBar: false});

                    // 4. Render 2D Chart (Telemetry Panel)
                    const layout2D = {
                        margin: { l: 40, r: 20, b: 30, t: 30 }, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: {color: '#888', family: 'Roboto Mono'},
                        title: {text: 'ORION INERTIAL VELOCITY (km/s)', font: {size: 12, color: '#00e5ff'}},
                        xaxis: {showgrid: true, gridcolor: '#222', tickfont: {size: 10}}, 
                        yaxis: {showgrid: true, gridcolor: '#222', tickfont: {size: 10}}
                    };
                    const trace2D = [{ x: timeHistory, y: velocityHistory, type: 'scatter', mode: 'lines+markers', line: {color: '#ff3d00', shape: 'spline'}, marker: {size: 4, color: '#00e5ff'} }];
                    Plotly.react('telemetry-chart', trace2D, layout2D, {displayModeBar: false});

                } catch (err) {
                    console.error("FIDO Console Error:", err);
                    document.getElementById('v-status').innerText = 'LOS (LOSS OF SIGNAL)';
                    document.getElementById('v-status').style.color = 'red';
                }
            }
            
            updateMOC();
            setInterval(updateMOC, 2500); 
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
