import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="NASA FIDO | Artemis Master Control")
DATABASE_URL = os.getenv("DATABASE_URL")
active_connections = set()

async def broadcast_telemetry(conn, pid, channel, payload):
    dead_connections = set()
    for websocket in active_connections:
        try:
            await websocket.send_text(payload)
        except:
            dead_connections.add(websocket)
    active_connections.difference_update(dead_connections)

@app.on_event("startup")
async def startup_event():
    try:
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)
    except Exception as e: print(f"Error DB: {e}")

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: active_connections.discard(websocket)

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>NASA FIDO | Consola Maestra Artemis II</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --bg: #000; --green: #00ff88; --yellow: #ffcc00; --red: #ff3333; }
            * { box-sizing: border-box; }
            body, html { margin:0; padding:0; height:100dvh; background:var(--bg); color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; touch-action: none; font-size: 14px;}
            
            #layout { display:flex; flex-direction:column; height:100%; width: 100%;}
            
            /* Viewport 3D Reducido (45%) */
            #viewport { height:45%; position:relative; border-bottom:1px solid rgba(0,242,255,0.5); background:#000; }
            
            /* HUD Táctico Masivo (55%) */
            #hud { height:55%; padding:10px; background:rgba(0,10,15,1); display:grid; grid-template-columns: 1fr 1fr; grid-template-rows: auto auto auto; gap:8px; overflow-y: auto;}
            
            .header-info { position:absolute; top:8px; left:8px; z-index:10; pointer-events:none; }
            .tag { display:inline-block; padding:1px 6px; font-size:0.65rem; font-weight:bold; background:var(--cian); color:#000; border-radius: 2px;}
            #clock { font-size:1.4rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }
            #met-clock { font-size:1.1rem; color:var(--yellow); font-weight:bold;}

            .card { border:1px solid rgba(0,242,255,0.2); background:rgba(0,242,255,0.03); padding:6px; border-radius: 4px; box-shadow: inset 0 0 10px rgba(0,0,0,0.5);}
            .card h2 { margin:0 0 5px 0; font-size:0.7rem; color:var(--cian); letter-spacing:1px; border-bottom: 1px solid rgba(0,242,255,0.15); padding-bottom: 2px;}
            
            .data-row { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:1px; font-size:0.75rem;}
            .lbl { color:#999; }
            .val { font-weight:bold; font-size:0.9rem; font-variant-numeric:tabular-nums; color:#fff;}
            .val.orange { color:var(--orange); text-shadow:0 0 3px rgba(255,72,0,0.3); }
            .val.green { color:var(--green); }
            .val.yellow { color:var(--yellow); }
            .val.small { font-size: 0.8rem; }
            .val.red { color:var(--red); font-weight: bold;}

            /* Estilos de panel específicos */
            .p-estado { grid-column: 1 / 3; border-color: var(--orange); background:rgba(255,72,0,0.03); }
            .p-env { grid-column: 1 / 3; border-color: var(--green); }

            #three-canvas { width:100%; height:100%; display:block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-info">
                    <div class="tag">● FLIGHT DYNAMICS LINK (FIDO)</div>
                    <div id="clock">00:00:00.000</div>
                    <div id="met-clock">MET T+ 00:00:00:00</div>
                </div>
                <div id="three-canvas"></div>
            </div>

            <div id="hud">
                <div class="card p-estado">
                    <h2 style="color: var(--orange);">ARTEMIS II | ESTADO GENERAL DE LA MISIÓN</h2>
                    <div class="data-row"><span class="lbl">FASE DE VUELO</span> <span class="val orange" id="v-phase">CONNECTING...</span></div>
                    <div class="data-row"><span class="lbl">VELOCIDAD INERCIAL J2000</span> <span class="val orange" id="v-vel">0.00000 km/s</span></div>
                    <div class="data-row"><span class="lbl">ALTITUD TIERRA (Geocéntrica)</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="data-row"><span class="lbl">DISTANCIA LUNA (Selocéntrica)</span> <span class="val yellow" id="v-dist-m">0 km</span></div>
                </div>

                <div class="card">
                    <h2>VECTORES ESTADO J2000 ( km / km/s )</h2>
                    <div class="data-row"><span class="lbl">EJE X</span> <span class="val small" id="v-x">0</span></div>
                    <div class="data-row"><span class="lbl">EJE Y</span> <span class="val small" id="v-y">0</span></div>
                    <div class="data-row"><span class="lbl">EJE Z</span> <span class="val small" id="v-z">0</span></div>
                    <div class="data-row" style="margin-top:2px;"><span class="lbl">VEL. Vx</span> <span class="val small green" id="v-vx">0</span></div>
                    <div class="data-row"><span class="lbl">VEL. Vy</span> <span class="val small green" id="v-vy">0</span></div>
                    <div class="data-row"><span class="lbl">VEL. Vz</span> <span class="val small green" id="v-vz">0</span></div>
                </div>

                <div class="card" style="border-color: var(--yellow);">
                    <h2 style="color: var(--yellow);">MÉTRICAS RELATIVAS A LA LUNA</h2>
                    <div class="data-row"><span class="lbl">VEL. RELATIVA LUNA</span> <span class="val yellow" id="v-vrel-m">0.00000 km/s</span></div>
                    <div class="data-row" style="margin-top:3px;"><span class="lbl">LAT SELENOGRÁFICA</span> <span class="val" id="v-lat-m">0.00°</span></div>
                    <div class="data-row"><span class="lbl">LON SELENOGRÁFICA</span> <span class="val" id="v-lon-m">0.00°</span></div>
                    <div class="data-row" style="margin-top:3px;"><span class="lbl">ÁNGULO DE FASE LUNAR</span> <span class="val red" id="v-phase-angle">0.00°</span></div>
                </div>

                <div class="card p-env">
                    <h2 style="color: var(--green);">DINÁMICA ESPACIAL AVANZADA Y SISTEMA</h2>
                    <div class="data-row"><span class="lbl">VELOCIDAD RELATIVA (MACH)</span> <span class="val" id="v-mach">0.00 M</span></div>
                    <div class="data-row"><span class="lbl">LATENCIA LUZ IDA (Tierra)</span> <span class="val" id="v-light">0.0000 s</span></div>
                    <div class="data-row"><span class="lbl">COORD. ECUATORIALES (RA/Dec)</span> <span class="val small" id="v-coords">0 / 0</span></div>
                    <div class="data-row" style="border:none; margin-top:2px;"><span class="lbl">UPLINK STATUS</span> <span class="val green" id="v-source" style="font-size:0.75rem;">CONNECTING...</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion;
            
            // Variables para la Estela de Trayectoria
            let trailGeometry, trailLine;
            const trailPoints = [];
            const MAX_TRAIL_LENGTH = 1000; // Recuerda los últimos 1000 puntos en el espacio

            function createLabel(text, color) {
                const canvas = document.createElement('canvas');
                const ctx = canvas.getContext('2d');
                canvas.width = 256; canvas.height = 64;
                ctx.fillStyle = color;
                ctx.font = 'Bold 40px Share Tech Mono';
                ctx.textAlign = 'center';
                ctx.fillText(text, 128, 45);
                const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
                sprite.scale.set(60, 15, 1);
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 1, 5000000);
                camera.position.set(0, 300, 600);

                renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                scene.add(new THREE.AmbientLight(0x333333));
                const sun = new THREE.DirectionalLight(0xffffff, 1.2);
                sun.position.set(-10, 2, 10);
                scene.add(sun);

                const tl = new THREE.TextureLoader();

                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 32, 32),
                    new THREE.MeshPhongMaterial({ map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')})
                );
                earth.add(eMesh);
                const eLbl = createLabel("EARTH", "#00f2ff"); eLbl.position.y = 50; earth.add(eLbl);
                scene.add(earth);

                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh);
                const mLbl = createLabel("LUNA", "#ffffff"); mLbl.position.y = 25; moon.add(mLbl);
                scene.add(moon);

                orion = new THREE.Group();
                const sm = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 8, 16), new THREE.MeshStandardMaterial({color: 0xcccccc}));
                const cm = new THREE.Mesh(new THREE.ConeGeometry(3, 4, 16), new THREE.MeshStandardMaterial({color: 0x222222})); cm.position.y = 6;
                const pMat = new THREE.MeshBasicMaterial({color: 0x0044aa, side: 2});
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(22, 3), pMat); p1.rotation.x = Math.PI/2;
                const p2 = new THREE.Mesh(new THREE.PlaneGeometry(3, 22), pMat); p2.rotation.x = Math.PI/2;
                orion.add(sm, cm, p1, p2);
                const oLbl = createLabel("ORION", "#ff4800"); oLbl.position.y = 15; orion.add(oLbl);
                scene.add(orion);

                // Configuración de la Estela Roja (Trayectoria)
                trailGeometry = new THREE.BufferGeometry();
                const trailMaterial = new THREE.LineBasicMaterial({ 
                    color: 0xff0000, // Rojo intenso
                    linewidth: 2, 
                    transparent: true, 
                    opacity: 0.6 
                });
                trailLine = new THREE.Line(trailGeometry, trailMaterial);
                scene.add(trailLine);

                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1500; i++){ starsCoords.push((Math.random()-0.5)*5000, (Math.random()-0.5)*5000, (Math.random()-0.5)*5000); }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color: 0xffffff, size: 1.5})));
                scene.add(new THREE.GridHelper(3000, 50, 0x002222, 0x001111));
            }

            function animate() {
                requestAnimationFrame(animate);
                earth.children[0].rotation.y += 0.001;
                orion.rotation.z += 0.01;
                controls.update();
                renderer.render(scene, camera);
            }

            function connect() {
                const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('met-clock').innerText = "MET " + d.met;
                    document.getElementById('v-phase').innerText = d.phase;
                    
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-source').style.color = d.source.includes("LIVE") ? "#0f0" : "#ffaa00";
                    
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(5) + " km/s";
                    document.getElementById('v-dist-e').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('v-dist-m').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";
                    
                    document.getElementById('v-x').innerText = d.ship.x.toFixed(2);
                    document.getElementById('v-y').innerText = d.ship.y.toFixed(2);
                    document.getElementById('v-z').innerText = d.ship.z.toFixed(2);
                    document.getElementById('v-vx').innerText = d.ship.vx.toFixed(5);
                    document.getElementById('v-vy').innerText = d.ship.vy.toFixed(5);
                    document.getElementById('v-vz').innerText = d.ship.vz.toFixed(5);

                    document.getElementById('v-vrel-m').innerText = d.ship.v_rel_m.toFixed(5) + " km/s";
                    document.getElementById('v-lat-m').innerText = d.ship.lat_m.toFixed(2) + "°";
                    document.getElementById('v-lon-m').innerText = d.ship.lon_m.toFixed(2) + "°";
                    document.getElementById('v-phase-angle').innerText = d.ship.phase_angle.toFixed(2) + "°";

                    document.getElementById('v-mach').innerText = d.ship.mach.toLocaleString(undefined,{maximumFractionDigits:2}) + " M";
                    document.getElementById('v-light').innerText = d.ship.light_e.toFixed(4) + " s";
                    document.getElementById('v-coords').innerText = d.ship.ra.toFixed(2) + "° RA / " + d.ship.dec.toFixed(2) + "° DEC";

                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;
                    
                    orion.position.set(ox, oz, oy); 
                    moon.position.set(mx, mz, my);
                    
                    // --- ACTUALIZAR LA ESTELA ---
                    trailPoints.push(new THREE.Vector3(ox, oz, oy));
                    if (trailPoints.length > MAX_TRAIL_LENGTH) {
                        trailPoints.shift(); // Borra el punto más viejo para no saturar la memoria
                    }
                    trailGeometry.setFromPoints(trailPoints); // Dibuja la línea nueva

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
