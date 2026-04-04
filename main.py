import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="Artemis II Tactical Gateway")
DATABASE_URL = os.getenv("DATABASE_URL")
active_connections = set()

async def broadcast_telemetry(conn, pid, channel, payload):
    dead = set()
    for ws in active_connections:
        try: await ws.send_text(payload)
        except: dead.add(ws)
    active_connections.difference_update(dead)

@app.on_event("startup")
async def startup_event():
    print("INICIANDO GATEWAY TÁCTICO...")
    try:
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)
        print("ESCUCHANDO EL CANAL DE TELEMETRÍA OK")
    except Exception as e: print(f"DB Error: {e}")

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
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, maximum-scale=1.0">
        <title>Artemis II | FIDO Radar (Táctico)</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --green: #00ff88; }
            body, html { margin:0; padding:0; height:100dvh; background:#000; color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; touch-action: none; }
            #layout { display:flex; flex-direction:column; height:100%; }
            
            /* Render 3D Superior */
            #viewport { height:55%; position:relative; border-bottom:1px solid var(--cian); background: #000; overflow: hidden; }
            
            /* HUD Táctico Inferior */
            #hud { height:45%; padding:15px; background:#010a0c; overflow-y:auto; border-top:1px solid var(--cian); }
            
            .header-box { position:absolute; top:10px; left:10px; z-index:10; pointer-events:none; }
            .time-val { font-size:1.5rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }
            
            .card { border-left:4px solid var(--cian); background:rgba(255,255,255,0.02); padding:10px; margin-bottom:10px; border-radius: 4px; }
            .card.red { border-color: var(--orange); }
            .card.status { border-color: var(--green); }
            
            .row { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:6px; font-size:0.8rem; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:2px;}
            .lbl { color:#888; }
            .val { font-weight:bold; font-size:1rem; font-variant-numeric:tabular-nums; }
            #three-canvas { width:100%; height:100%; display: block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-box">
                    <div style="font-size:0.7rem; font-weight:bold; background:var(--cian); color:#000; display:inline-block; padding:2px 8px; margin-bottom:2px; border-radius: 2px;">● MISSION CONTROL LIVE</div>
                    <div id="clock" class="time-val">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>
            <div id="hud">
                <div class="card red">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--orange)">ORION SPACECRAFT (ARTEMIS II)</h2>
                    <div class="row"><span class="lbl">VELOCIDAD INERCIAL</span> <span class="val" id="v-vel" style="color:var(--orange)">0.000 km/s</span></div>
                    <div class="row"><span class="lbl">VELOCIDAD (MACH)</span> <span class="val" id="v-mach">0.00 M</span></div>
                    <div class="row"><span class="lbl">ALTITUD (TIERRA)</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="row"><span class="lbl">DISTANCIA (LUNA)</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>
                <div class="card">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--cian)">DEEP SPACE DYNAMICS</h2>
                    <div class="row"><span class="lbl">LATENCIA LUZ (IDA)</span> <span class="val" id="v-light">0.000 s</span></div>
                    <div class="row"><span class="lbl">COORD. ECUATORIALES (RA/Dec)</span> <span class="val" id="v-coords">0 / 0</span></div>
                </div>
                <div class="card status">
                    <div class="row" style="border-bottom:none; margin-bottom:0; padding-bottom:0;"><span class="lbl">DSN UPLINK SOURCE</span> <span class="val green" id="v-source">CONNECTING...</span></div>
                </div>
            </div>
        </div>

        <script>
            // ESCALA DE RADAR TÁCTICO: 1 unidad 3D = 1000 KM (Safe scale, prevent black screen)
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
                // Etiquetas con depthTest: false para que siempre se vean encima
                ctx.fillText(text, 256, 80);
                const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
                sprite.scale.set(100, 25, 1); 
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                
                // Cámara estable y segura (no reventar render mobile)
                camera = new THREE.PerspectiveCamera(50, container.clientWidth/container.clientHeight, 1, 2000000);
                camera.position.set(0, 300, 700);
                
                renderer = new THREE.WebGLRenderer({ antialias:true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // ILUMINACIÓN ESTABLE Y FIJA (Prevent blackness si el cálculo del sol falla)
                scene.add(new THREE.AmbientLight(0x222222)); // Mayor luz ambiente
                const tl = new THREE.TextureLoader();
                
                // TIERRA TÁCTICA GIGANTE (Radio simulado 35 unidades)
                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(new THREE.SphereGeometry(35, 64, 64), new THREE.MeshPhongMaterial({ map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg') }));
                earth.add(eMesh); 
                const eTag = createTag("EARTH", "#00f2ff"); eTag.position.y = 50; earth.add(eTag);
                scene.add(earth);

                // LUNA TÁCTICA GIGANTE (Radio simulado 15 unidades)
                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(new THREE.SphereGeometry(15, 32, 32), new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') }));
                moon.add(mMesh); 
                const mTag = createTag("LUNAR TARGET", "#ffffff"); mTag.position.y = 30; moon.add(mTag);
                scene.add(moon);

                // ORION TÁCTICA (Simbolicamente más grande)
                orion = new THREE.Group();
                const sm = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 8, 16), new THREE.MeshStandardMaterial({color:0xcccccc, metalness: 0.8}));
                const cm = new THREE.Mesh(new THREE.ConeGeometry(3, 4, 16), new THREE.MeshStandardMaterial({color:0x222222})); cm.position.y = 6;
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(25, 4), new THREE.MeshBasicMaterial({color:0x0044aa, side: THREE.DoubleSide})); p1.rotation.x = Math.PI/2;
                orion.add(sm, cm, p1);
                const oTag = createTag("ORION II", "#ff4800"); oTag.position.y = 20; orion.add(oTag);
                scene.add(orion);

                // Estrellas
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<2000; i++){ starsCoords.push((Math.random()-0.5)*4000, (Math.random()-0.5)*4000, (Math.random()-0.5)*4000); }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color:0xffffff, size:2.0})));
                
                // LA GRILLA TÁCTICA (Critical contextual fix for "arreglarlo")
                scene.add(new THREE.GridHelper(3000, 50, 0x002222, 0x001111));
                scene.add(new THREE.AxesHelper(100));
            }

            function connect() {
                const ws = new WebSocket((window.location.protocol==='https:'?'wss:':'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-source').style.color = d.source.includes("LIVE") ? "#0f0" : "#ffaa00";
                    
                    // Actualización de datos HIPEREXACTOS en el HUD
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(5) + " km/s";
                    document.getElementById('v-mach').innerText = d.ship.mach.toLocaleString(undefined,{maximumFractionDigits:2}) + " M";
                    document.getElementById('v-dist-e').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('v-dist-m').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";
                    document.getElementById('v-light').innerText = d.ship.light_time.toFixed(4) + " s";
                    document.getElementById('v-coords').innerText = d.ship.ra.toFixed(2) + "° RA / " + d.ship.dec.toFixed(2) + "° DEC";

                    // Actualización visual SIMULADA pero matemáticamente referenciada
                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;
                    
                    orion.position.set(ox, oz, oy); 
                    moon.position.set(mx, mz, my);
                    
                    // La cámara sigue el punto medio táctico
                    controls.target.set(ox/2, oz/2, oy/2);
                };
                ws.onclose = () => setTimeout(connect, 1000);
            }

            init3D(); connect();
            function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
            animate();
            
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
