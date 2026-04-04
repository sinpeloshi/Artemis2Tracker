from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
import json
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - Definitivo")

# --- CARGA DE MOTORES CRÍTICOS ---
eph = load('de421.bsp')
earth_eph, moon_eph, sun_eph = eph['earth'], eph['moon'], eph['sun']
ts = load.timescale()

# Memoria de estado vectorial
state_vector = {
    "pos": None, 
    "vel": None,
    "timestamp": datetime.utcnow(),
    "source": "INITIALIZING..."
}

async def fetch_nasa_jpl_live():
    """Conexión Directa a la API de NASA Horizons (Modo Texto Seguro)"""
    NAIF_ID = '-121' 
    now = datetime.utcnow()
    t_start = now.strftime('%Y-%m-%d %H:%M')
    t_stop = (now + timedelta(minutes=2)).strftime('%Y-%m-%d %H:%M')

    url = "https://ssd.jpl.nasa.gov/api/horizons.api"
    params = {
        "format": "text", "COMMAND": NAIF_ID, "OBJ_DATA": "NO",
        "MAKE_EPHEM": "YES", "EPHEM_TYPE": "VECTORS", "CENTER": "500@399",
        "START_TIME": t_start, "STOP_TIME": t_stop, "STEP_SIZE": "1m",
        "OUT_UNITS": "KM-S", "VEC_TABLE": "2"
    }

    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, params=params, timeout=8.0)
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
                        state_vector["source"] = "NASA JPL HORIZONS (LIVE)"
                        return True
        except Exception as e:
            print(f"NASA Link Error: {e}")
    return False

async def get_telemetry_packet():
    t = ts.now()
    now = datetime.utcnow()
    
    ast_moon = earth_eph.at(t).observe(moon_eph)
    mx, my, mz = [float(c) for c in ast_moon.position.km]
    
    ast_sun = earth_eph.at(t).observe(sun_eph)
    sx, sy, sz = [float(c) for c in ast_sun.position.km]

    # PROTECCIÓN ANTI-CRASH: Si no hay datos, iniciamos la nave al 85% del trayecto
    if state_vector["pos"] is None:
        state_vector["pos"] = [mx * 0.85, my * 0.85, mz * 0.85 + 15000]
        state_vector["vel"] = [0.5, 0.5, 0.5] # Velocidad simulada
        state_vector["source"] = "INTERNAL SIM (FAIL-SAFE)"
        state_vector["timestamp"] = now

    # Extrapolación de movimiento fluido
    dt = (now - state_vector["timestamp"]).total_seconds()
    
    ox = state_vector["pos"][0] + (state_vector["vel"][0] * dt)
    oy = state_vector["pos"][1] + (state_vector["vel"][1] * dt)
    oz = state_vector["pos"][2] + (state_vector["vel"][2] * dt)
    
    v_mag = math.sqrt(sum(v**2 for v in state_vector["vel"]))
    if v_mag < 0.1: v_mag = 1.152 # Fallback estético
    
    dist_e = math.sqrt(ox**2 + oy**2 + oz**2)
    dist_m = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)

    return {
        "time": t.utc_strftime('%H:%M:%S.%f')[:-3] + " UTC",
        "source": state_vector["source"],
        "moon": {"x": mx, "y": my, "z": mz},
        "sun_dir": {"x": sx, "y": sy, "z": sz},
        "orion": {"x": ox, "y": oy, "z": oz, "v": v_mag, "dist_e": dist_e, "dist_m": dist_m}
    }

@app.on_event("startup")
async def startup_event():
    await fetch_nasa_jpl_live()
    async def refresh_loop():
        while True:
            await fetch_nasa_jpl_live()
            await asyncio.sleep(45)
    asyncio.create_task(refresh_loop())

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await get_telemetry_packet()
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(0.05) 
    except WebSocketDisconnect: pass

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>NASA FIDO | Tracker</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; }
            body, html { margin:0; padding:0; height:100dvh; background:#000; color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; }
            #layout { display:flex; flex-direction:column; height:100%; }
            #viewport { height:60%; position:relative; border-bottom:1px solid var(--cian); }
            #hud { height:40%; padding:15px; background:#010a0c; overflow-y:auto; border-top:1px solid var(--cian); }
            .header-box { position:absolute; top:10px; left:10px; z-index:10; pointer-events:none; }
            .time-val { font-size:1.8rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }
            .card { border-left:4px solid var(--cian); background:rgba(255,255,255,0.02); padding:10px; margin-bottom:10px; }
            .row { display:flex; justify-content:space-between; margin-bottom:4px; font-size:0.9rem; }
            .val { font-weight:bold; font-variant-numeric:tabular-nums; }
            #three-canvas { width:100%; height:100%; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-box">
                    <div style="font-size:0.7rem; font-weight:bold; background:var(--cian); color:#000; display:inline-block; padding:0 5px;">TELEMETRY LINK</div>
                    <div id="clock" class="time-val">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>
            <div id="hud">
                <div class="card" style="border-color:var(--orange)">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--orange)">CÁPSULA ORION</h2>
                    <div class="row"><span>VELOCIDAD INERCIAL</span> <span class="val" id="v-vel" style="color:var(--orange)">0.000 km/s</span></div>
                    <div class="row"><span>ALTITUD TIERRA</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="row"><span>PROXIMIDAD LUNAR</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>
                <div class="card">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--cian)">SISTEMA</h2>
                    <div class="row"><span>FUENTE DE DATOS</span> <span class="val" id="v-source" style="color:#0f0">--</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls, sunLight;
            let earth, moon, orion;

            function createTag(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 512; canvas.height = 128;
                ctx.fillStyle = color;
                ctx.font = 'Bold 60px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 256, 80);
                const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }));
                sprite.scale.set(80, 20, 1);
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(50, container.clientWidth/container.clientHeight, 1, 5000000);
                camera.position.set(0, 400, 800);

                renderer = new THREE.WebGLRenderer({ antialias:true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                scene.add(new THREE.AmbientLight(0x050510)); 
                sunLight = new THREE.DirectionalLight(0xffffff, 1.5);
                scene.add(sunLight);

                const tl = new THREE.TextureLoader();
                
                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 64, 64),
                    new THREE.MeshPhongMaterial({ map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg') })
                );
                earth.add(eMesh);
                const eTag = createTag("EARTH", "#00f2ff");
                eTag.position.y = 50;
                earth.add(eTag);
                scene.add(earth);

                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh);
                const mTag = createTag("MOON", "#ffffff");
                mTag.position.y = 30;
                moon.add(mTag);
                scene.add(moon);

                orion = new THREE.Group();
                const body = new THREE.Mesh(new THREE.CylinderGeometry(3,3,8,16), new THREE.MeshStandardMaterial({color:0xcccccc, metalness:0.6}));
                const head = new THREE.Mesh(new THREE.ConeGeometry(3,4,16), new THREE.MeshStandardMaterial({color:0x222222, metalness:0.8}));
                head.position.y = 6;
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(25,4), new THREE.MeshBasicMaterial({color:0x0044aa, side:THREE.DoubleSide}));
                p1.rotation.x = Math.PI/2;
                orion.add(body, head, p1);
                const oTag = createTag("ORION", "#ff4800");
                oTag.position.y = 20;
                orion.add(oTag);
                scene.add(orion);

                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<2000; i++){ starsCoords.push((Math.random()-0.5)*5000, (Math.random()-0.5)*5000, (Math.random()-0.5)*5000); }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color:0xffffff, size:1.5})));
                
                scene.add(new THREE.GridHelper(3000, 50, 0x002222, 0x001111));
            }

            function animate() {
                requestAnimationFrame(animate);
                if(earth) earth.children[0].rotation.y += 0.0005;
                if(orion) orion.rotation.z += 0.01;
                controls.update();
                renderer.render(scene, camera);
            }

            function connect() {
                const ws = new WebSocket((window.location.protocol==='https:'?'wss:':'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-source').style.color = d.source.includes("LIVE") ? "#0f0" : "#ff0";
                    document.getElementById('v-vel').innerText = d.orion.v.toFixed(5) + " km/s";
                    document.getElementById('v-dist-e').innerText = d.orion.dist_e.toLocaleString(undefined,{maximumFractionDigits:3}) + " km";
                    document.getElementById('v-dist-m').innerText = d.orion.dist_m.toLocaleString(undefined,{maximumFractionDigits:3}) + " km";

                    const ox = d.orion.x/SCALE, oz = d.orion.z/SCALE, oy = -d.orion.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;
                    
                    orion.position.set(ox, oz, oy);
                    moon.position.set(mx, mz, my);
                    
                    sunLight.position.set(d.sun_dir.x/1e7, d.sun_dir.z/1e7, -d.sun_dir.y/1e7).normalize();
                    controls.target.set(ox/2, oz/2, oy/2);
                };
                ws.onclose = () => setTimeout(connect, 1000);
            }

            init3D(); animate(); connect();
            window.addEventListener('resize', () => {
                const c = document.getElementById('three-canvas');
                camera.aspect = c.clientWidth/c.clientHeight; camera.updateProjectionMatrix();
                renderer.setSize(c.clientWidth, c.clientHeight);
            });
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
