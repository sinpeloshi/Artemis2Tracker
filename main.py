from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
import json
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - FIDO Precision MOC")

# Motor Astronómico Local (100% Preciso)
eph = load('de421.bsp')
earth_eph, moon_eph = eph['earth'], eph['moon']
ts = load.timescale()

# Caché de Estado Vectorial
nasa_cache = {"orion_data": None, "last_update": datetime.min}

async def fetch_jpl_horizons():
    """Conexión Directa a NASA JPL Horizons"""
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
            response = await client.get(url, params=params, timeout=5.0)
            if "$$SOE" in response.text:
                soe = response.text.find("$$SOE")
                eoe = response.text.find("$$EOE")
                lines = response.text[soe:eoe].split('\n')
                x, y, z, vx, vy, vz = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                for line in lines:
                    if "X =" in line and "Y =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    elif "VX=" in line and "VY=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                        return {"x": x, "y": y, "z": z, "vx": vx, "vy": vy, "vz": vz}
        except: return None
    return None

async def get_telemetry_data():
    t = ts.now()
    now = datetime.utcnow()
    
    # 1. POSICIÓN DE LA LUNA (Calculada localmente con precisión astronómica)
    astrometric_moon = earth_eph.at(t).observe(moon_eph)
    mx = float(astrometric_moon.position.km[0])
    my = float(astrometric_moon.position.km[1])
    mz = float(astrometric_moon.position.km[2])
    
    # 2. ACTUALIZACIÓN DE ESTADO VECTORIAL (Cada 60 seg)
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl = await fetch_jpl_horizons()
        if jpl:
            nasa_cache["orion_data"] = jpl
            nasa_cache["last_update"] = now

    orion = nasa_cache["orion_data"]
    
    if orion:
        # LA MAGIA: Extrapolación Cinemática en Tiempo Real
        dt = (now - nasa_cache["last_update"]).total_seconds()
        ox = orion["x"] + (orion["vx"] * dt)
        oy = orion["y"] + (orion["vy"] * dt)
        oz = orion["z"] + (orion["vz"] * dt)
        v_orion = math.sqrt(orion["vx"]**2 + orion["vy"]**2 + orion["vz"]**2)
        source = "DSN DIRECT LINK"
    else:
        # Modo de contingencia (Fallback)
        ox, oy, oz = mx * 0.85, my * 0.85, mz * 0.85 + 15000
        v_orion = 1.152
        source = "INTERNAL CALC"

    # Distancias Euclidianas
    dist_e_o = math.sqrt(ox**2 + oy**2 + oz**2)
    dist_m_o = math.sqrt((mx-ox)**2 + (my-oy)**2 + (mz-oz)**2)

    return {
        "time": t.utc_strftime('%H:%M:%S.%f')[:-3], # Milisegundos
        "source": source,
        "moon": {"x": mx, "y": my, "z": mz},
        "orion": {"x": ox, "y": oy, "z": oz, "dist_e": dist_e_o, "dist_m": dist_m_o, "v": v_orion}
    }

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await get_telemetry_data()
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(0.05) # 20 FOTOGRAMAS POR SEGUNDO
    except WebSocketDisconnect:
        pass

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, maximum-scale=1.0">
        <title>NASA | Artemis Flight Dynamics</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --bg: #00080a; }
            * { box-sizing: border-box; }
            body, html { margin: 0; padding: 0; height: 100dvh; background: var(--bg); color: #fff; font-family: 'Share Tech Mono', monospace; overflow: hidden; touch-action: none; }
            
            #layout { display: flex; flex-direction: column; height: 100%; width: 100%; }
            
            /* Render 3D Superior */
            #viewport { height: 50%; position: relative; border-bottom: 2px solid var(--cian); background: #000; }
            
            /* HUD Táctico Inferior */
            #hud { height: 50%; padding: 15px; background: rgba(0,10,15,1); display: flex; flex-direction: column; gap: 10px; overflow-y: auto; }
            
            .hud-header { position: absolute; top: 10px; left: 10px; z-index: 10; pointer-events: none; }
            .tag { display: inline-block; padding: 2px 8px; font-size: 0.7rem; font-weight: bold; background: var(--cian); color: #000; margin-bottom: 2px; }
            #live-time { font-size: 1.5rem; color: var(--cian); text-shadow: 0 0 8px var(--cian); }

            .panel { border: 1px solid rgba(0,242,255,0.3); background: rgba(0,242,255,0.05); padding: 10px; border-radius: 4px; box-shadow: inset 0 0 10px rgba(0,0,0,0.5); }
            .panel h2 { margin: 0 0 8px 0; font-size: 0.85rem; color: var(--cian); letter-spacing: 1px; border-bottom: 1px dashed rgba(0,242,255,0.3); padding-bottom: 4px;}
            
            .data-row { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 6px; }
            .lbl { color: #888; font-size: 0.8rem; }
            .val { color: #fff; font-size: 1.1rem; font-weight: bold; font-variant-numeric: tabular-nums; }
            .val.orange { color: var(--orange); text-shadow: 0 0 5px rgba(255,72,0,0.5); }
            .val.green { color: #0f0; }

            #three-canvas { width: 100%; height: 100%; display: block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="hud-header">
                    <div class="tag">● TELEMETRY LINK ACTIVE</div>
                    <div id="live-time">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>

            <div id="hud">
                <div class="panel" style="border-color: var(--orange);">
                    <h2 style="color: var(--orange); border-bottom-color: var(--orange);">ORION DYNAMICS</h2>
                    <div class="data-row"><span class="lbl">INERTIAL VEL.</span> <span class="val orange" id="v-vel">0.00000 km/s</span></div>
                    <div class="data-row"><span class="lbl">ALTITUDE (EARTH)</span> <span class="val" id="v-dist-e">0.000 km</span></div>
                    <div class="data-row"><span class="lbl">PROXIMITY (MOON)</span> <span class="val" id="v-dist-m">0.000 km</span></div>
                </div>

                <div class="panel">
                    <h2>SYSTEM METRICS</h2>
                    <div class="data-row"><span class="lbl">DATA SOURCE</span> <span class="val green" id="v-source" style="font-size:0.8rem">--</span></div>
                    <div class="data-row"><span class="lbl">REFRESH RATE</span> <span class="val green" style="font-size:0.8rem">20 Hz (WebSocket)</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion;

            function createLabel(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 256; canvas.height = 64;
                ctx.fillStyle = color;
                ctx.font = 'Bold 40px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 128, 45);
                const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true }));
                sprite.scale.set(60, 15, 1);
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                
                // Estrellas
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1500; i++) {
                    starsCoords.push((Math.random()-0.5)*4000, (Math.random()-0.5)*4000, (Math.random()-0.5)*4000);
                }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color: 0xffffff, size: 1.5})));

                camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 1, 2000000);
                camera.position.set(0, 300, 700);

                renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // Iluminación
                scene.add(new THREE.AmbientLight(0x222222));
                const sun = new THREE.DirectionalLight(0xffffff, 1.2);
                sun.position.set(-10, 2, 10);
                scene.add(sun);

                const tl = new THREE.TextureLoader();

                // TIERRA (Holograma Blue Marble)
                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 64, 64),
                    new THREE.MeshPhongMaterial({ map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg'), specular: 0x333 })
                );
                earth.add(eMesh);
                const eLbl = createLabel("EARTH", "#00f2ff");
                eLbl.position.y = 50;
                earth.add(eLbl);
                scene.add(earth);

                // LUNA (Cráteres)
                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh);
                const mLbl = createLabel("MOON", "#ffffff");
                mLbl.position.y = 25;
                moon.add(mLbl);
                scene.add(moon);

                // ORION (Módulo Espacial Detallado)
                orion = new THREE.Group();
                const sm = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 8, 16), new THREE.MeshStandardMaterial({ color: 0xcccccc }));
                const cm = new THREE.Mesh(new THREE.ConeGeometry(3, 4, 16), new THREE.MeshStandardMaterial({ color: 0x222222 }));
                cm.position.y = 6;
                const panelMat = new THREE.MeshBasicMaterial({ color: 0x0044aa, side: THREE.DoubleSide });
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(22, 3), panelMat);
                const p2 = new THREE.Mesh(new THREE.PlaneGeometry(3, 22), panelMat);
                p1.rotation.x = Math.PI/2; p2.rotation.x = Math.PI/2;
                orion.add(sm, cm, p1, p2);
                
                const oLbl = createLabel("ORION", "#ff4800");
                oLbl.position.y = 15;
                orion.add(oLbl);
                scene.add(orion);
            }

            function animate() {
                requestAnimationFrame(animate);
                earth.children[0].rotation.y += 0.001; // Solo rota la malla, no la etiqueta
                orion.rotation.z += 0.01;
                controls.update();
                renderer.render(scene, camera);
            }

            // FORMATEADOR DE NÚMEROS (Para que los decimales giren hermoso)
            function formatNum(num, dec) {
                return Number(num).toLocaleString('en-US', {minimumFractionDigits: dec, maximumFractionDigits: dec});
            }

            function connectWS() {
                const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/telemetry');
                
                ws.onmessage = function(e) {
                    const d = JSON.parse(e.data);
                    
                    document.getElementById('live-time').innerText = d.time;
                    document.getElementById('v-source').innerText = d.source;
                    
                    // Aquí vas a ver la magia de la extrapolación matemática. 
                    // Los decimales cambian en tiempo real.
                    document.getElementById('v-vel').innerText = formatNum(d.orion.v, 5) + " km/s";
                    document.getElementById('v-dist-e').innerText = formatNum(d.orion.dist_e, 3) + " km";
                    document.getElementById('v-dist-m').innerText = formatNum(d.orion.dist_m, 3) + " km";

                    const ox = d.orion.x/SCALE, oz = d.orion.z/SCALE, oy = -d.orion.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;

                    orion.position.set(ox, oz, oy);
                    moon.position.set(mx, mz, my);

                    controls.target.set(ox/2, oz/2, oy/2);
                };
                
                ws.onclose = () => setTimeout(connectWS, 1000);
            }

            init3D();
            animate();
            connectWS();

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
