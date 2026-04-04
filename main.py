from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - NASA Tactical Labels")

# Motor Astronómico
eph = load('de421.bsp')
earth_eph, moon_eph = eph['earth'], eph['moon']
ts = load.timescale()

nasa_cache = {"orion_data": None, "last_update": datetime.min}

async def fetch_jpl_horizons():
    NAIF_ID = '-121' 
    now_utc = datetime.utcnow()
    t_start = now_utc.strftime('%Y-%m-%d %H:%M')
    t_stop = (now_utc + timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M')
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
            if "$$SOE" in response.text:
                soe = response.text.find("$$SOE")
                eoe = response.text.find("$$EOE")
                lines = response.text[soe:eoe].split('\n')
                for line in lines:
                    if "X =" in line:
                        p = line.split()
                        return {"x": float(p[2]), "y": float(p[5]), "z": float(p[8]), "vx": 0, "vy": 0, "vz": 0}
        except: return None
    return None

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    now = datetime.utcnow()
    astrometric_moon = earth_eph.at(t).observe(moon_eph)
    mx, my, mz = astrometric_moon.position.km
    dist_moon_earth = math.sqrt(mx**2 + my**2 + mz**2)
    
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl = await fetch_jpl_horizons()
        if jpl:
            nasa_cache["orion_data"] = jpl
            nasa_cache["last_update"] = now

    orion = nasa_cache["orion_data"]
    if orion:
        ox, oy, oz = orion["x"], orion["y"], orion["z"]
        source, status = "DSN/JPL HORIZONS", "NOMINAL"
    else:
        ox, oy, oz = mx * 0.88, my * 0.88, mz * 0.88 + 12000
        source, status = "INTERNAL SIM", "DEGRADED"

    return {
        "sys_time": t.utc_strftime('%H:%M:%S UTC'),
        "signal": {"source": source, "status": status},
        "moon": {"x": mx, "y": my, "z": mz, "dist": dist_moon_earth},
        "orion": {"x": ox, "y": oy, "z": oz, "dist": math.sqrt(ox**2+oy**2+oz**2), "v": 1.152}
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>NASA Artemis 2 | Tactical Radar</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            body, html { margin: 0; padding: 0; height: 100%; background: #000; color: #0ff; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            #dashboard { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 10; display: flex; flex-direction: column; }
            .header { background: rgba(0,20,30,0.8); border-bottom: 1px solid #0ff; padding: 10px 15px; display: flex; justify-content: space-between; pointer-events: auto; }
            .hud-panel { margin-top: auto; background: rgba(0,20,30,0.8); border-top: 1px solid #0ff; padding: 15px; pointer-events: auto; font-size: 0.8rem; }
            .metric { display: flex; justify-content: space-between; margin-bottom: 5px; border-bottom: 1px solid rgba(0,255,255,0.1); }
            .val { color: #fff; font-weight: bold; }
            #three-container { position: fixed; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="three-container"></div>
        <div id="dashboard">
            <div class="header">
                <div style="color:#0ff; text-shadow:0 0 5px #0ff;">● ARTEMIS 2 TACTICAL</div>
                <div id="sys-time">00:00:00</div>
            </div>
            <div class="hud-panel">
                <div class="metric"><span>SIGNAL SOURCE</span> <span class="val" id="v-source">--</span></div>
                <div class="metric"><span>ORION VELOCITY</span> <span class="val" id="o-vel">0.00 km/s</span></div>
                <div class="metric"><span>EARTH ALTITUDE</span> <span class="val" id="o-dist">0 km</span></div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion;

            // FUNCIÓN PARA CREAR ETIQUETAS DE TEXTO 3D (Sprites)
            function createTextLabel(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 256; canvas.height = 64;
                ctx.fillStyle = color;
                ctx.font = 'Bold 40px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 128, 45);
                
                const texture = new THREE.CanvasTexture(canvas);
                const spriteMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true });
                const sprite = new THREE.Sprite(spriteMaterial);
                sprite.scale.set(60, 15, 1); // Tamaño de la etiqueta
                return sprite;
            }

            function initThree() {
                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 1, 5000000);
                camera.position.set(0, 500, 800);

                renderer = new THREE.WebGLRenderer({ antialias: true });
                renderer.setSize(window.innerWidth, window.innerHeight);
                document.getElementById('three-container').appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // TIERRA + ETIQUETA
                const earthGeo = new THREE.SphereGeometry(30, 32, 32);
                earth = new THREE.Mesh(earthGeo, new THREE.MeshBasicMaterial({ color: 0x00ffff, wireframe: true }));
                scene.add(earth);
                const earthLabel = createTextLabel("PLANET EARTH", "#00ffff");
                earthLabel.position.set(0, 45, 0);
                earth.add(earthLabel);

                // LUNA + ETIQUETA
                const moonGeo = new THREE.SphereGeometry(15, 16, 16);
                moon = new THREE.Mesh(moonGeo, new THREE.MeshBasicMaterial({ color: 0xaaaaaa, wireframe: true }));
                scene.add(moon);
                const moonLabel = createTextLabel("LUNAR TARGET", "#ffffff");
                moonLabel.position.set(0, 25, 0);
                moon.add(moonLabel);

                // ORION + ETIQUETA
                const orionGeo = new THREE.BoxGeometry(10, 10, 10);
                orion = new THREE.Mesh(orionGeo, new THREE.MeshBasicMaterial({ color: 0xff3300 }));
                scene.add(orion);
                const orionLabel = createTextLabel("ORION MODULE", "#ff3300");
                orionLabel.position.set(0, 20, 0);
                orion.add(orionLabel);

                // ÓRBITA LUNAR (Guía visual)
                const orbit = new THREE.Mesh(new THREE.RingGeometry(384, 386, 64), new THREE.MeshBasicMaterial({ color: 0x333333, side: THREE.DoubleSide }));
                orbit.rotation.x = Math.PI / 2;
                scene.add(orbit);

                scene.add(new THREE.GridHelper(2000, 40, 0x002222, 0x001111));
            }

            async function update() {
                try {
                    const res = await fetch('/api/telemetry');
                    const d = await res.json();
                    
                    document.getElementById('sys-time').innerText = d.sys_time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('o-vel').innerText = d.orion.v + " km/s";
                    document.getElementById('o-dist').innerText = d.orion.dist.toLocaleString() + " km";

                    const mx = d.moon.x / SCALE, mz = d.moon.z / SCALE, my = -d.moon.y / SCALE;
                    const ox = d.orion.x / SCALE, oz = d.orion.z / SCALE, oy = -d.orion.y / SCALE;

                    moon.position.set(mx, mz, my);
                    orion.position.set(ox, oz, oy);

                    // CENTRADO DINÁMICO: La cámara enfoca el punto medio entre la Tierra y Orion
                    controls.target.set(ox / 2, oz / 2, oy / 2);

                } catch (e) {}
            }

            function animate() {
                requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            }

            initThree();
            animate();
            setInterval(update, 3000);
            update();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
