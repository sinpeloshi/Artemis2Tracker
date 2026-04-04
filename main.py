import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="Deep Space Gateway")
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
    try:
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)
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
        <title>NASA FIDO | Real Data</title>
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
            .val.orange { color:var(--orange); text-shadow:0 0 5px rgba(255,72,0,0.5); }
            .val.green { color:var(--green); text-shadow:0 0 5px rgba(0,255,136,0.5); }
            #three-canvas { width:100%; height:100%; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-box">
                    <div style="font-size:0.7rem; font-weight:bold; background:var(--cian); color:#000; display:inline-block; padding:2px 5px;">DSN TELEMETRY LOCK</div>
                    <div id="clock" class="time-val">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>
            <div id="hud">
                <div class="card red">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--orange)">LUNAR RECONNAISSANCE ORBITER (LRO)</h2>
                    <div class="row"><span class="lbl">VELOCIDAD INERCIAL</span> <span class="val orange" id="v-vel">0.000 km/s</span></div>
                    <div class="row"><span class="lbl">VELOCIDAD (MACH)</span> <span class="val" id="v-mach">0.00 M</span></div>
                    <div class="row"><span class="lbl">ALTITUD TIERRA</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="row"><span class="lbl">PROXIMIDAD LUNAR</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>
                <div class="card">
                    <h2 style="margin:0 0 8px 0; font-size:0.8rem; color:var(--cian)">MÉTRICAS ESPACIALES</h2>
                    <div class="row"><span class="lbl">LATENCIA DE LUZ (IDA)</span> <span class="val" id="v-light">0.000 s</span></div>
                    <div class="row"><span class="lbl">ASCENSIÓN RECTA</span> <span class="val" id="v-ra">0.00°</span></div>
                    <div class="row"><span class="lbl">DECLINACIÓN</span> <span class="val" id="v-dec">0.00°</span></div>
                </div>
                <div class="card" style="border-color:var(--green)">
                    <div class="row"><span class="lbl">FUENTE DE DATOS</span> <span class="val green" id="v-source">CONNECTING...</span></div>
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
                const eTag = createTag("EARTH", "#00f2ff"); eTag.position.y = 50; earth.add(eTag);
                scene.add(earth);

                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh);
                const mTag = createTag("MOON", "#ffffff"); mTag.position.y = 30; moon.add(mTag);
                scene.add(moon);

                orion = new THREE.Group();
                const body = new THREE.Mesh(new THREE.CylinderGeometry(3,3,8,16), new THREE.MeshStandardMaterial({color:0xcccccc, metalness:0.6}));
                const head = new THREE.Mesh(new THREE.ConeGeometry(3,4,16), new THREE.MeshStandardMaterial({color:0x222222, metalness:0.8}));
                head.position.y = 6;
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(25,4), new THREE.MeshBasicMaterial({color:0x0044aa, side:THREE.DoubleSide}));
                p1.rotation.x = Math.PI/2;
                orion.add(body, head, p1);
                const oTag = createTag("LRO SATELLITE", "#ff4800"); oTag.position.y = 20; orion.add(oTag);
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
                    
                    const srcElem = document.getElementById('v-source');
                    srcElem.innerText = d.source;
                    srcElem.style.color = d.source.includes("LIVE") ? "#0f0" : "#ffaa00";
                    
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(5) + " km/s";
                    document.getElementById('v-mach').innerText = d.ship.mach.toLocaleString(undefined,{maximumFractionDigits:2}) + " M";
                    document.getElementById('v-dist-e').innerText = d.ship.dist_e.toLocaleString(undefined,{maximumFractionDigits:3}) + " km";
                    document.getElementById('v-dist-m').innerText = d.ship.dist_m.toLocaleString(undefined,{maximumFractionDigits:3}) + " km";
                    
                    document.getElementById('v-light').innerText = d.ship.light_time.toFixed(4) + " s";
                    document.getElementById('v-ra').innerText = d.ship.ra.toFixed(4) + "°";
                    document.getElementById('v-dec').innerText = d.ship.dec.toFixed(4) + "°";

                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
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
