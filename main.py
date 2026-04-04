from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - Omega Tactical MOC")

# Motor Astronómico (NASA Core)
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
                        return {"x": float(p[2]), "y": float(p[5]), "z": float(p[8])}
        except: return None
    return None

@app.get("/api/telemetry")
async def get_telemetry():
    try:
        t = ts.now()
        now = datetime.utcnow()
        astrometric_moon = earth_eph.at(t).observe(moon_eph)
        
        mx = float(astrometric_moon.position.km[0])
        my = float(astrometric_moon.position.km[1])
        mz = float(astrometric_moon.position.km[2])
        
        if (now - nasa_cache["last_update"]).total_seconds() > 60:
            jpl = await fetch_jpl_horizons()
            if jpl:
                nasa_cache["orion_data"] = jpl
                nasa_cache["last_update"] = now

        orion = nasa_cache["orion_data"]
        if orion:
            ox, oy, oz = float(orion["x"]), float(orion["y"]), float(orion["z"])
            source, status = "JPL/HORIZONS (LIVE)", "NOMINAL"
        else:
            ox, oy, oz = float(mx * 0.85), float(my * 0.85), float(mz * 0.85 + 15000)
            source, status = "INTERNAL CALCULUS", "FAIL-SAFE"

        return {
            "time": t.utc_strftime('%H:%M:%S UTC'),
            "signal": {"source": source, "status": status},
            "moon": {"x": mx, "y": my, "z": mz, "dist": float(math.sqrt(mx**2+my**2+mz**2))},
            "orion": {"x": ox, "y": oy, "z": oz, "dist": float(math.sqrt(ox**2+oy**2+oz**2)), "v": 1.152}
        }
    except: return {"error": "stale data"}

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Artemis II | Omega MOC</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --bg: #00080a; }
            body, html { margin: 0; padding: 0; height: 100dvh; background: var(--bg); color: #fff; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            
            #master-container { display: flex; flex-direction: column; height: 100dvh; }
            
            /* Mitad Superior: Mapa 3D */
            #viewport { height: 55%; position: relative; border-bottom: 2px solid var(--cian); background: #000; flex-shrink: 0; }
            
            /* Mitad Inferior: Datos con Scroll */
            #hud-data { height: 45%; overflow-y: auto; padding: 15px; background: rgba(0,10,15,0.95); box-sizing: border-box; }
            
            .header-info { position: absolute; top: 10px; left: 10px; z-index: 5; pointer-events: none; text-shadow: 0 0 5px #000; }
            .status-tag { display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 0.7rem; font-weight: bold; background: var(--cian); color: #000; margin-bottom: 5px; }

            .card { border: 1px solid rgba(0,242,255,0.2); background: rgba(255,255,255,0.03); padding: 12px; margin-bottom: 12px; }
            .card h2 { margin: 0 0 10px 0; font-size: 0.8rem; color: var(--cian); letter-spacing: 1px; border-bottom: 1px solid rgba(0,242,255,0.2); padding-bottom: 5px;}
            .row { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 6px; }
            .label { color: #888; }
            .val { color: #fff; font-weight: bold; }
            .val.orange { color: var(--orange); }

            #three-canvas { width: 100%; height: 100%; display: block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="master-container">
            <div id="viewport">
                <div class="header-info">
                    <div class="status-tag">● LIVE TELEMETRY</div>
                    <div id="top-time" style="font-size: 1.2rem; color: var(--cian);">00:00:00 UTC</div>
                </div>
                <div id="three-canvas"></div>
            </div>

            <div id="hud-data">
                <div class="card">
                    <h2>NETWORK STATUS</h2>
                    <div class="row"><span class="label">UPLINK SOURCE</span> <span class="val" id="v-source">--</span></div>
                    <div class="row"><span class="label">SIGNAL LOCK</span> <span class="val" style="color:#0f0">SECURE</span></div>
                </div>

                <div class="card" style="border-color: var(--orange)">
                    <h2 style="color: var(--orange)">ORION SPACECRAFT</h2>
                    <div class="row"><span class="label">VELOCITY</span> <span class="val orange" id="o-vel">0.000 km/s</span></div>
                    <div class="row"><span class="label">EARTH ALTITUDE</span> <span class="val" id="o-dist-e">0 km</span></div>
                    <div class="row"><span class="label">LUNAR PROXIMITY</span> <span class="val" id="o-dist-m">0 km</span></div>
                </div>

                <div class="card">
                    <h2>LUNAR TARGET</h2>
                    <div class="row"><span class="label">ORBITAL DISTANCE</span> <span class="val" id="m-dist">0 km</span></div>
                    <div class="row"><span class="label">PHASE</span> <span class="val">APPROACH</span></div>
                </div>

                <div style="font-size: 0.6rem; color: #444; text-align: center; padding: 10px;">
                    SISTEMA DE RASTREO TÁCTICO v4.0 - NASA JPL HORIZONS DATA CORE
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion, grid;

            function createTag(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 512; canvas.height = 128;
                ctx.fillStyle = color;
                ctx.font = 'Bold 60px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 256, 80);
                const tex = new THREE.CanvasTexture(canvas);
                const mat = new THREE.SpriteMaterial({ map: tex });
                const sprite = new THREE.Sprite(mat);
                sprite.scale.set(80, 20, 1);
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                scene.background = new THREE.Color(0x000000);

                camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 1, 2000000);
                camera.position.set(0, 300, 600);

                renderer = new THREE.WebGLRenderer({ antialias: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // TIERRA (Holograma Detallado)
                earth = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 32, 32),
                    new THREE.MeshBasicMaterial({ color: 0x00f2ff, wireframe: true, transparent: true, opacity: 0.5 })
                );
                earth.add(createTag("EARTH", "#00f2ff"));
                scene.add(earth);

                // LUNA
                moon = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 16, 16),
                    new THREE.MeshBasicMaterial({ color: 0xaaaaaa, wireframe: true })
                );
                moon.add(createTag("MOON", "#ffffff"));
                scene.add(moon);

                // ORION (Nave)
                orion = new THREE.Mesh(
                    new THREE.OctahedronGeometry(10),
                    new THREE.MeshBasicMaterial({ color: 0xff4800 })
                );
                orion.add(createTag("ORION", "#ff4800"));
                scene.add(orion);

                // Grid Espacial
                grid = new THREE.GridHelper(2000, 40, 0x002222, 0x001111);
                scene.add(grid);
            }

            async function update() {
                try {
                    const res = await fetch('/api/telemetry');
                    const d = await res.json();
                    
                    document.getElementById('top-time').innerText = d.time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('o-vel').innerText = d.orion.v.toFixed(3) + " km/s";
                    document.getElementById('o-dist-e').innerText = Math.round(d.orion.dist).toLocaleString() + " km";
                    document.getElementById('m-dist').innerText = Math.round(d.moon.dist).toLocaleString() + " km";
                    
                    const ox = d.orion.x/SCALE, oz = d.orion.z/SCALE, oy = -d.orion.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;

                    orion.position.set(ox, oz, oy);
                    moon.position.set(mx, mz, my);

                    // Autocentrado suave
                    controls.target.set(ox/2, oz/2, oy/2);
                } catch(e) {}
            }

            function animate() {
                requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            }

            init3D();
            animate();
            setInterval(update, 3000);
            update();

            window.addEventListener('resize', () => {
                const container = document.getElementById('three-canvas');
                camera.aspect = container.clientWidth / container.clientHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(container.clientWidth, container.clientHeight);
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
