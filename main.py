import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="Artemis II Gateway")
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
    print("INICIANDO GATEWAY DE COMUNICACIONES...")
    try:
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)
        print("ESCUCHANDO EL CANAL TELEMETRY_STREAM OK")
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
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>Artemis II | FIDO Radar (True Scale)</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --green: #00ff88; }
            body, html { margin:0; padding:0; height:100dvh; background:#000; color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; }
            #layout { display:flex; flex-direction:column; height:100%; }
            #viewport { height:55%; position:relative; border-bottom:1px solid var(--cian); }
            #hud { height:45%; padding:10px; background:#010a0c; overflow-y:auto; border-top:1px solid var(--cian); }
            .header-box { position:absolute; top:10px; left:10px; z-index:10; pointer-events:none; }
            .time-val { font-size:1.5rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }
            .card { border-left:4px solid var(--cian); background:rgba(255,255,255,0.02); padding:10px; margin-bottom:10px; }
            .card.red { border-color: var(--orange); }
            .row { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:6px; font-size:0.8rem; border-bottom:1px solid rgba(255,255,255,0.05); padding-bottom:2px;}
            .lbl { color:#888; }
            .val { font-weight:bold; font-size:1rem; font-variant-numeric:tabular-nums; }
            #three-canvas { width:100%; height:100%; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-box">
                    <div style="font-size:0.7rem; font-weight:bold; background:var(--cian); color:#000; display:inline-block; padding:2px 5px;">MISSION CONTROL LIVE</div>
                    <div id="clock" class="time-val">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>
            <div id="hud">
                <div class="card red">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--orange)">ORION SPACECRAFT (ARTEMIS II)</h2>
                    <div class="row"><span class="lbl">VEL. INERCIAL</span> <span class="val" id="v-vel" style="color:var(--orange)">0.000 km/s</span></div>
                    <div class="row"><span class="lbl">VEL. MACH</span> <span class="val" id="v-mach">0.00 M</span></div>
                    <div class="row"><span class="lbl">ALTITUD TIERRA</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="row"><span class="lbl">DISTANCIA LUNA</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>
                <div class="card">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--cian)">FLIGHT DYNAMICS</h2>
                    <div class="row"><span class="lbl">LATENCIA LUZ</span> <span class="val" id="v-light">0.000 s</span></div>
                    <div class="row"><span class="lbl">A. RECTA / DEC.</span> <span class="val" id="v-coords">0 / 0</span></div>
                </div>
                <div class="card" style="border-color:var(--green)">
                    <div class="row"><span class="lbl">UPLINK STATUS</span> <span class="val" id="v-source" style="color:var(--green)">--</span></div>
                </div>
            </div>
        </div>

        <script>
            // NUEVA ESCALA DE LA REALIDAD: 1 unidad 3D = 100 KM
            const SCALE = 100;
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
                const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, depthTest: false }));
                sprite.scale.set(300, 75, 1); // Etiquetas más grandes para la nueva escala
                return sprite;
            }

            function init3D() {
                const container = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                
                // Cámara configurada para ver enormes distancias (Tierra-Luna son 384,400 km = 3844 unidades)
                camera = new THREE.PerspectiveCamera(50, container.clientWidth/container.clientHeight, 1, 5000000);
                camera.position.set(0, 2000, 4000);
                
                renderer = new THREE.WebGLRenderer({ antialias:true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;
                controls.maxDistance = 10000; // Permitir zoom out extremo

                scene.add(new THREE.AmbientLight(0x050510)); 
                sunLight = new THREE.DirectionalLight(0xffffff, 2.0);
                scene.add(sunLight);

                const tl = new THREE.TextureLoader();
                
                // ESCALA REAL DE LA TIERRA: Radio = 6371 km / 100 = 63.7 unidades
                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(63.7, 64, 64), 
                    new THREE.MeshPhongMaterial({ map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg') })
                );
                earth.add(eMesh); 
                const eTag = createTag("EARTH", "#00f2ff"); eTag.position.y = 120; earth.add(eTag);
                scene.add(earth);

                // ESCALA REAL DE LA LUNA: Radio = 1737 km / 100 = 17.3 unidades
                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(17.3, 32, 32), 
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh); 
                const mTag = createTag("LUNAR TARGET", "#ffffff"); mTag.position.y = 80; moon.add(mTag);
                scene.add(moon);

                // ORION: Para que se vea en esta escala inmensa, hay que hacerla más grande "simbólicamente"
                orion = new THREE.Group();
                const body = new THREE.Mesh(new THREE.CylinderGeometry(10,10,25,16), new THREE.MeshStandardMaterial({color:0xcccccc}));
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(80,12), new THREE.MeshBasicMaterial({color:0x0044aa, side:2}));
                p1.rotation.x = Math.PI/2; 
                orion.add(body, p1);
                const oTag = createTag("ORION II", "#ff4800"); oTag.position.y = 60; orion.add(oTag);
                scene.add(orion);

                // Estrellas ajustadas a la nueva escala masiva
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<3000; i++){ starsCoords.push((Math.random()-0.5)*20000, (Math.random()-0.5)*20000, (Math.random()-0.5)*20000); }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color:0xffffff, size:3.0})));
            }

            function connect() {
                const ws = new WebSocket((window.location.protocol==='https:'?'wss:':'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-source').style.color = d.source.includes("LIVE") ? "#0f0" : "#ffaa00";
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(4) + " km/s";
                    document.getElementById('v-mach').innerText = d.ship.mach.toFixed(2) + " M";
                    document.getElementById('v-dist-e').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('v-dist-m').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";
                    document.getElementById('v-light').innerText = d.ship.light_time.toFixed(4) + " s";
                    document.getElementById('v-coords').innerText = d.ship.ra.toFixed(2) + "° RA / " + d.ship.dec.toFixed(2) + "° DEC";

                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;
                    
                    orion.position.set(ox, oz, oy); 
                    moon.position.set(mx, mz, my);
                    
                    sunLight.position.set(d.sun_dir.x/1e7, d.sun_dir.z/1e7, -d.sun_dir.y/1e7).normalize();
                    
                    // La cámara ahora "sigue" a Orion pero desde un poco más lejos
                    controls.target.set(ox/2, oz/2, oy/2);
                };
                ws.onclose = () => setTimeout(connect, 1000);
            }

            init3D(); connect();
            function animate() { requestAnimationFrame(animate); controls.update(); renderer.render(scene, camera); }
            animate();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
