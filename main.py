from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
import json
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 | Deep Space Hologram")

eph = load('de421.bsp')
earth, moon = eph['earth'], eph['moon']
ts = load.timescale()

# Constante gravitacional terrestre (km^3/s^2)
MU_EARTH = 398600.4418 

nasa_cache = {"data": None, "last_update": datetime.min}

async def fetch_jpl_horizons():
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
            response = await client.get(url, params=params, timeout=5.0)
            data = response.text
            if "$$SOE" in data:
                soe = data.find("$$SOE")
                eoe = data.find("$$EOE")
                lines = data[soe:eoe].split('\n')
                x, y, z, vx, vy, vz = 0,0,0,0,0,0
                for line in lines:
                    if "X =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    elif "VX=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                        return {"x": x, "y": y, "z": z, "vx": vx, "vy": vy, "vz": vz}
        except: return None
    return None

async def generate_telemetry_frame():
    t = ts.now()
    now = datetime.utcnow()
    
    astrometric_moon = earth.at(t).observe(moon)
    mx, my, mz = astrometric_moon.position.km
    
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl = await fetch_jpl_horizons()
        if jpl:
            nasa_cache["data"] = jpl
            nasa_cache["last_update"] = now

    orion = nasa_cache["data"]
    
    if orion:
        ox, oy, oz = orion["x"], orion["y"], orion["z"]
        ovx, ovy, ovz = orion["vx"], orion["vy"], orion["vz"]
        status = "DSN LOCK"
    else:
        # Interpolación avanzada si NASA corta la API
        ox, oy, oz = mx * 0.88, my * 0.88, mz * 0.88 + 12500
        ovx, ovy, ovz = 0.5, 0.5, 0.5
        status = "INTERNAL SIM"

    r = math.sqrt(ox**2 + oy**2 + oz**2)
    v = math.sqrt(ovx**2 + ovy**2 + ovz**2)
    
    # Cálculo Kepleriano de la Energía Orbital Específica y Semieje Mayor
    try:
        epsilon = (v**2 / 2) - (MU_EARTH / r)
        semi_major_axis = -MU_EARTH / (2 * epsilon) if epsilon != 0 else 0
    except:
        epsilon, semi_major_axis = 0, 0

    return {
        "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + ' UTC',
        "status": status,
        "moon": {"x": mx, "y": my, "z": mz},
        "orion": {"x": ox, "y": oy, "z": oz, "v": v, "r": r},
        "kepler": {"epsilon": epsilon, "sma": semi_major_axis}
    }

# WEBSOCKET: Transmisión en tiempo real sin latencia HTTP
@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            frame = await generate_telemetry_frame()
            await websocket.send_text(json.dumps(frame))
            await asyncio.sleep(0.5) # Empuja datos 2 veces por segundo
    except:
        pass # Maneja la desconexión limpia del cliente

@app.get("/")
async def get_frontend():
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>NASA | 3D Tactical Hologram</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap');
            body { margin: 0; overflow: hidden; background: #000; color: #0f0; font-family: 'Space Mono', monospace; }
            #hud { position: absolute; top: 20px; left: 20px; z-index: 10; pointer-events: none; text-shadow: 0 0 5px #0f0; }
            .panel { border: 1px solid rgba(0, 255, 0, 0.3); background: rgba(0, 20, 0, 0.7); padding: 15px; margin-bottom: 10px; box-shadow: inset 0 0 10px rgba(0, 255, 0, 0.2); }
            h1 { font-size: 14px; margin: 0 0 10px 0; border-bottom: 1px solid #0f0; padding-bottom: 5px; }
            .d-row { display: flex; justify-content: space-between; width: 300px; font-size: 12px; margin-bottom: 4px; }
            .v { font-weight: bold; color: #fff; }
            #gl-container { position: absolute; top: 0; left: 0; width: 100vw; height: 100vh; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="hud">
            <div class="panel">
                <h1>ARTEMIS TACTICAL LINK</h1>
                <div class="d-row"><span>SYSTEM TIME:</span> <span class="v" id="t-time">SYNCING...</span></div>
                <div class="d-row"><span>DATA LINK:</span> <span class="v" id="t-status" style="color:cyan">WAITING</span></div>
            </div>
            <div class="panel">
                <h1>FLIGHT DYNAMICS (FIDO)</h1>
                <div class="d-row"><span>INERTIAL VEL:</span> <span class="v" id="o-v">0.00 km/s</span></div>
                <div class="d-row"><span>EARTH DIST:</span> <span class="v" id="o-r">0.00 km</span></div>
            </div>
            <div class="panel">
                <h1>KEPLERIAN ORBITAL ELEMENTS</h1>
                <div class="d-row"><span>SPECIFIC ENERGY (ε):</span> <span class="v" id="k-e">0.00 km²/s²</span></div>
                <div class="d-row"><span>SEMI-MAJOR AXIS (a):</span> <span class="v" id="k-a">0.00 km</span></div>
            </div>
        </div>

        <div id="gl-container"></div>

        <script>
            // INICIALIZACIÓN THREE.JS (Escala 1:1000 para renderizado)
            const SCALE = 1000; 
            const scene = new THREE.Scene();
            scene.fog = new THREE.FogExp2(0x000000, 0.000002);

            const camera = new THREE.PerspectiveCamera(45, window.innerWidth / window.innerHeight, 1, 5000000);
            camera.position.set(0, 150000, 400000);

            const renderer = new THREE.WebGLRenderer({ antialias: true });
            renderer.setSize(window.innerWidth, window.innerHeight);
            document.getElementById('gl-container').appendChild(renderer.domElement);

            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;
            controls.dampingFactor = 0.05;

            // ESTÉTICA TÁCTICA: Tierra (Wireframe Cyan), Luna (Gris), Orion (Punto de Luz Rojo)
            const earthGeo = new THREE.SphereGeometry(6371 / SCALE, 32, 32);
            const earthMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, wireframe: true, transparent: true, opacity: 0.3 });
            const earth = new THREE.Mesh(earthGeo, earthMat);
            scene.add(earth);

            const moonGeo = new THREE.SphereGeometry(1737 / SCALE, 16, 16);
            const moonMat = new THREE.MeshBasicMaterial({ color: 0x888888, wireframe: true });
            const moon = new THREE.Mesh(moonGeo, moonMat);
            scene.add(moon);

            const orionGeo = new THREE.SphereGeometry(500 / SCALE, 8, 8); // Exagerado visualmente
            const orionMat = new THREE.MeshBasicMaterial({ color: 0xff0000 });
            const orion = new THREE.Mesh(orionGeo, orionMat);
            
            // Glow alrededor de Orion
            const glow = new THREE.PointLight(0xff0000, 2, 50000);
            orion.add(glow);
            scene.add(orion);

            // Trayectoria Dinámica
            const maxTrail = 150;
            const trailPositions = new Float32Array(maxTrail * 3);
            const trailGeo = new THREE.BufferGeometry();
            trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3));
            const trailMat = new THREE.LineBasicMaterial({ color: 0xff0000, transparent: true, opacity: 0.5 });
            const trailLine = new THREE.Line(trailGeo, trailMat);
            scene.add(trailLine);
            let trailCount = 0;

            // Cuadrícula Espacial (Grid Helper)
            const gridHelper = new THREE.GridHelper(1000000 / SCALE, 100, 0x004400, 0x001100);
            scene.add(gridHelper);

            // CONEXIÓN WEBSOCKET AL BACKEND
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const ws = new WebSocket(protocol + '//' + window.location.host + '/ws/telemetry');

            ws.onmessage = function(event) {
                const d = JSON.parse(event.data);
                
                // Actualizar HUD
                document.getElementById('t-time').innerText = d.time;
                document.getElementById('t-status').innerText = d.status;
                document.getElementById('o-v').innerText = d.orion.v.toFixed(5) + ' km/s';
                document.getElementById('o-r').innerText = d.orion.r.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';
                document.getElementById('k-e').innerText = d.kepler.epsilon.toFixed(4);
                document.getElementById('k-a').innerText = d.kepler.sma.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' km';

                // Actualizar Físicas 3D (Escaladas)
                moon.position.set(d.moon.x / SCALE, d.moon.z / SCALE, -d.moon.y / SCALE); // Mapeo XYZ a XZY en Three.js
                orion.position.set(d.orion.x / SCALE, d.orion.z / SCALE, -d.orion.y / SCALE);

                // Actualizar Trayectoria
                const positions = trailLine.geometry.attributes.position.array;
                for(let i = maxTrail - 1; i > 0; i--) {
                    positions[i * 3] = positions[(i - 1) * 3];
                    positions[i * 3 + 1] = positions[(i - 1) * 3 + 1];
                    positions[i * 3 + 2] = positions[(i - 1) * 3 + 2];
                }
                positions[0] = orion.position.x;
                positions[1] = orion.position.y;
                positions[2] = orion.position.z;
                
                trailLine.geometry.attributes.position.needsUpdate = true;
            };

            // Loop de Renderizado a 60 FPS
            function animate() {
                requestAnimationFrame(animate);
                earth.rotation.y += 0.001; // Rotación terrestre simulada
                controls.update();
                renderer.render(scene, camera);
            }
            animate();

            // Auto-ajuste de ventana
            window.addEventListener('resize', onWindowResize, false);
            function onWindowResize() {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)
