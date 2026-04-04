from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
import json
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - RealTime Omega MOC")

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
            response = await client.get(url, params=params, timeout=5.0)
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

async def get_telemetry_data():
    try:
        t = ts.now()
        now = datetime.utcnow()
        astrometric_moon = earth_eph.at(t).observe(moon_eph)
        
        mx = float(astrometric_moon.position.km[0])
        my = float(astrometric_moon.position.km[1])
        mz = float(astrometric_moon.position.km[2])
        
        # Consultamos la API oficial solo cada 60s para no saturarla
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
            "time": t.utc_strftime('%H:%M:%S.%f')[:-4] + ' UTC', # Mostramos décimas de segundo!
            "signal": {"source": source, "status": status},
            "moon": {"x": mx, "y": my, "z": mz, "dist": float(math.sqrt(mx**2+my**2+mz**2))},
            "orion": {"x": ox, "y": oy, "z": oz, "dist": float(math.sqrt(ox**2+oy**2+oz**2)), "v": 1.152}
        }
    except: 
        return {"error": True}

# === WEBSOCKET: EL CANAL DE TIEMPO REAL ===
@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await get_telemetry_data()
            await websocket.send_text(json.dumps(data))
            await asyncio.sleep(0.1) # Empuja datos al celular 10 veces por segundo
    except WebSocketDisconnect:
        print("Cliente desconectado")

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Artemis II | RealTime Textures</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --bg: #020202; }
            body, html { margin: 0; padding: 0; height: 100dvh; background: var(--bg); color: #fff; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            
            #master-container { display: flex; flex-direction: column; height: 100dvh; }
            #viewport { height: 55%; position: relative; border-bottom: 2px solid var(--cian); background: #000; flex-shrink: 0; }
            #hud-data { height: 45%; overflow-y: auto; padding: 15px; background: rgba(5,15,20,0.95); box-sizing: border-box; }
            
            .header-info { position: absolute; top: 10px; left: 10px; z-index: 5; pointer-events: none; text-shadow: 0 0 5px #000; }
            .status-tag { display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 0.7rem; font-weight: bold; background: var(--cian); color: #000; margin-bottom: 5px; box-shadow: 0 0 10px var(--cian);}
            
            .card { border: 1px solid rgba(0,242,255,0.3); background: rgba(0,242,255,0.05); padding: 12px; margin-bottom: 12px; border-radius: 4px; box-shadow: inset 0 0 10px rgba(0,242,255,0.05);}
            .card h2 { margin: 0 0 10px 0; font-size: 0.85rem; color: var(--cian); letter-spacing: 1px; border-bottom: 1px solid rgba(0,242,255,0.3); padding-bottom: 5px;}
            .row { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 8px; }
            .label { color: #aaa; }
            .val { color: #fff; font-weight: bold; font-size: 0.95rem; }
            .val.orange { color: var(--orange); text-shadow: 0 0 5px rgba(255,72,0,0.5); }

            #three-canvas { width: 100%; height: 100%; display: block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="master-container">
            <div id="viewport">
                <div class="header-info">
                    <div class="status-tag">WEBSOCKET: LIVE LINK</div>
                    <div id="top-time" style="font-size: 1.3rem; color: var(--cian); font-weight:bold;">00:00:00.0 UTC</div>
                </div>
                <div id="three-canvas"></div>
            </div>

            <div id="hud-data">
                <div class="card">
                    <h2>NETWORK STATUS</h2>
                    <div class="row"><span class="label">UPLINK SOURCE</span> <span class="val" id="v-source">CONNECTING...</span></div>
                </div>

                <div class="card" style="border-color: var(--orange)">
                    <h2 style="color: var(--orange); border-bottom-color: var(--orange)">ORION SPACECRAFT</h2>
                    <div class="row"><span class="label">VELOCITY</span> <span class="val orange" id="o-vel">0.000 km/s</span></div>
                    <div class="row"><span class="label">EARTH ALTITUDE</span> <span class="val" id="o-dist-e">0 km</span></div>
                    <div class="row"><span class="label">LUNAR PROXIMITY</span> <span class="val" id="o-dist-m">0 km</span></div>
                </div>

                <div class="card">
                    <h2>LUNAR TARGET</h2>
                    <div class="row"><span class="label">ORBITAL DISTANCE</span> <span class="val" id="m-dist">0 km</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion;

            function createTag(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 512; canvas.height = 128;
                ctx.fillStyle = color;
                ctx.font = 'Bold 60px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 256, 80);
                const tex = new THREE.CanvasTexture(canvas);
                const mat = new THREE.SpriteMaterial({ map: tex, transparent: true });
                const sprite = new THREE.Sprite(mat);
                sprite.scale.set(80, 20, 1);
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                
                // Fondo de estrellas
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1000; i++) {
                    starsCoords.push((Math.random()-0.5)*3000, (Math.random()-0.5)*3000, (Math.random()-0.5)*3000);
                }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                const starsMat = new THREE.PointsMaterial({color: 0xffffff, size: 1.5});
                scene.add(new THREE.Points(starsGeo, starsMat));

                camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 1, 2000000);
                camera.position.set(0, 300, 600);

                renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // ILUMINACIÓN REALISTA
                scene.add(new THREE.AmbientLight(0x111111)); // Luz tenue para las sombras
                const sunLight = new THREE.DirectionalLight(0xffffff, 1.5);
                sunLight.position.set(-10, 5, 10);
                scene.add(sunLight);

                const textureLoader = new THREE.TextureLoader();

                // TIERRA: Textura real Blue Marble con reflejos
                const earthTex = textureLoader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg');
                earth = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 64, 64),
                    new THREE.MeshPhongMaterial({ map: earthTex, specular: 0x333333, shininess: 15 })
                );
                earth.add(createTag("EARTH", "#00f2ff"));
                scene.add(earth);

                // LUNA: Textura real de cráteres
                const moonTex = textureLoader.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg');
                moon = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: moonTex, roughness: 1, metalness: 0 })
                );
                moon.add(createTag("MOON", "#ffffff"));
                scene.add(moon);

                // ORION: Ensamblaje 3D (Módulo de Mando + Servicio + Paneles)
                orion = new THREE.Group();
                
                // Módulo de Servicio (Cilindro blanco metálico)
                const sm = new THREE.Mesh(
                    new THREE.CylinderGeometry(4, 4, 10, 16),
                    new THREE.MeshStandardMaterial({ color: 0xdddddd, metalness: 0.5, roughness: 0.5 })
                );
                orion.add(sm);
                
                // Módulo de Mando (Cono oscuro metálico)
                const cm = new THREE.Mesh(
                    new THREE.ConeGeometry(4, 5, 16),
                    new THREE.MeshStandardMaterial({ color: 0x333333, metalness: 0.8, roughness: 0.2 })
                );
                cm.position.y = 7.5;
                orion.add(cm);
                
                // Paneles Solares (Cruces azules)
                const panelMat = new THREE.MeshBasicMaterial({ color: 0x0044aa, side: THREE.DoubleSide });
                const panel1 = new THREE.Mesh(new THREE.PlaneGeometry(25, 4), panelMat);
                const panel2 = new THREE.Mesh(new THREE.PlaneGeometry(4, 25), panelMat);
                panel1.rotation.x = Math.PI / 2; panel2.rotation.x = Math.PI / 2;
                orion.add(panel1); orion.add(panel2);

                const orionTag = createTag("ORION", "#ff4800");
                orionTag.position.y = 15;
                orion.add(orionTag);

                scene.add(orion);
            }

            function animate() {
                requestAnimationFrame(animate);
                earth.rotation.y += 0.001; // La Tierra rota de forma realista
                orion.rotation.z += 0.01;  // La nave rota sobre su eje para estabilización
                controls.update();
                renderer.render(scene, camera);
            }

            // === CONEXIÓN WEBSOCKET ===
            function connectWebSocket() {
                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const ws = new WebSocket(protocol + '//' + window.location.host + '/ws/telemetry');

                ws.onmessage = function(event) {
                    const d = JSON.parse(event.data);
                    if(d.error) return;

                    // El reloj ahora avanza en décimas de segundo!
                    document.getElementById('top-time').innerText = d.time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('o-vel').innerText = d.orion.v.toFixed(4) + " km/s";
                    document.getElementById('o-dist-e').innerText = Math.round(d.orion.dist).toLocaleString('en-US') + " km";
                    document.getElementById('o-dist-m').innerText = Math.round(Math.abs(d.moon.dist - d.orion.dist)).toLocaleString('en-US') + " km";
                    document.getElementById('m-dist').innerText = Math.round(d.moon.dist).toLocaleString('en-US') + " km";
                    
                    const ox = d.orion.x/SCALE, oz = d.orion.z/SCALE, oy = -d.orion.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;

                    // Transición súper suave gracias al WebSocket
                    orion.position.set(ox, oz, oy);
                    moon.position.set(mx, mz, my);

                    controls.target.set(ox/2, oz/2, oy/2);
                };

                ws.onclose = function(e) {
                    document.getElementById('v-source').innerText = "LINK LOST... RECONNECTING";
                    setTimeout(connectWebSocket, 2000);
                };
            }

            init3D();
            animate();
            connectWebSocket();

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
