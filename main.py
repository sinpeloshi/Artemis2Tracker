import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="NASA FIDO | Consola Maestra")
DATABASE_URL = os.getenv("DATABASE_ARTEMIS")
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
        <title>NASA FIDO | Artemis Mission Control</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --green: #00ff88; --yellow: #ffcc00; }
            * { box-sizing: border-box; }
            body, html { margin:0; padding:0; height:100dvh; background:#000; color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; touch-action: none; font-size: 13px;}
            #layout { display:flex; flex-direction:column; height:100%; }
            #viewport { height:45%; position:relative; border-bottom:1px solid rgba(0,242,255,0.5); }
            #hud { height:55%; padding:10px; background:rgba(0,10,15,1); display:grid; grid-template-columns: 1fr 1fr; gap:8px; overflow-y: auto;}
            .header-info { position:absolute; top:8px; left:8px; z-index:10; pointer-events:none; }
            #clock { font-size:1.4rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }
            #met-clock { font-size:1.1rem; color:var(--yellow); }
            .card { border:1px solid rgba(0,242,255,0.2); background:rgba(0,242,255,0.03); padding:6px; border-radius: 4px; }
            .card h2 { margin:0 0 5px 0; font-size:0.7rem; color:var(--cian); border-bottom: 1px solid rgba(0,242,255,0.15); padding-bottom: 2px;}
            .data-row { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:1px; }
            .lbl { color:#999; font-size:0.7rem; }
            .val { font-weight:bold; color:#fff; font-variant-numeric:tabular-nums; }
            .val.orange { color:var(--orange); }
            .val.green { color:var(--green); }
            .full-w { grid-column: 1 / 3; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-info">
                    <div id="clock">00:00:00.000</div>
                    <div id="met-clock">MET T+ 00:00:00:00</div>
                </div>
                <div id="three-canvas" style="width:100%; height:100%;"></div>
            </div>
            <div id="hud">
                <div class="card full-w" style="border-color:var(--orange)">
                    <h2 style="color:var(--orange)">ORION ARTEMIS II | ESTADO GENERAL</h2>
                    <div class="data-row"><span class="lbl">VELOCIDAD INERCIAL</span> <span class="val orange" id="v-vel">0.000 km/s</span></div>
                    <div class="data-row"><span class="lbl">ALTITUD TIERRA</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="data-row"><span class="lbl">DISTANCIA LUNA</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>
                <div class="card">
                    <h2>VECTORES ECI (X/Y/Z)</h2>
                    <div class="data-row"><span class="lbl">X</span> <span class="val" id="v-x">0</span></div>
                    <div class="data-row"><span class="lbl">Y</span> <span class="val" id="v-y">0</span></div>
                    <div class="data-row"><span class="lbl">Z</span> <span class="val" id="v-z">0</span></div>
                </div>
                <div class="card">
                    <h2>MÉTRICAS LUNARES</h2>
                    <div class="data-row"><span class="lbl">V. RELATIVA</span> <span class="val" id="v-vrel-m">0 km/s</span></div>
                    <div class="data-row"><span class="lbl">LAT. SEL.</span> <span class="val" id="v-lat-m">0°</span></div>
                    <div class="data-row"><span class="lbl">LON. SEL.</span> <span class="val" id="v-lon-m">0°</span></div>
                </div>
                <div class="card full-w" style="border-color:var(--green)">
                    <h2>SISTEMA Y RED</h2>
                    <div class="data-row"><span class="lbl">LATENCIA LUZ</span> <span class="val" id="v-light">0.000 s</span></div>
                    <div class="data-row"><span class="lbl">UPLINK STATUS</span> <span class="val green" id="v-source">CONNECTING...</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls, earth, moon, orion, trailGeometry;
            const trailPoints = [];

            function init3D() {
                const c = document.getElementById('three-canvas');
                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(50, c.clientWidth/c.clientHeight, 1, 1000000);
                camera.position.set(0, 300, 600);
                renderer = new THREE.WebGLRenderer({ antialias:true, alpha:true });
                renderer.setSize(c.clientWidth, c.clientHeight);
                c.appendChild(renderer.domElement);
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;
                scene.add(new THREE.AmbientLight(0x444444));
                const sun = new THREE.DirectionalLight(0xffffff, 1.2); sun.position.set(-10, 5, 10); scene.add(sun);
                
                const tl = new THREE.TextureLoader();
                earth = new THREE.Mesh(new THREE.SphereGeometry(35,32,32), new THREE.MeshPhongMaterial({map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')}));
                scene.add(earth);
                moon = new THREE.Mesh(new THREE.SphereGeometry(15,32,32), new THREE.MeshStandardMaterial({map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg')}));
                scene.add(moon);
                orion = new THREE.Group();
                const body = new THREE.Mesh(new THREE.CylinderGeometry(3,3,8,16), new THREE.MeshStandardMaterial({color:0xcccccc}));
                const p = new THREE.Mesh(new THREE.PlaneGeometry(25,4), new THREE.MeshBasicMaterial({color:0x0044aa, side:2})); p.rotation.x=Math.PI/2;
                orion.add(body, p); scene.add(orion);

                trailGeometry = new THREE.BufferGeometry();
                scene.add(new THREE.Line(trailGeometry, new THREE.LineBasicMaterial({color:0xff0000, opacity:0.6, transparent:true})));
                scene.add(new THREE.GridHelper(3000,50,0x002222,0x001111));
            }

            function connect() {
                const ws = new WebSocket((window.location.protocol==='https:'?'wss:':'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('met-clock').innerText = "MET " + d.met;
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-source').style.color = d.source.includes("LIVE") ? "#0f0" : "#ffaa00";
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(5) + " km/s";
                    document.getElementById('v-dist-e').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('v-dist-m').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";
                    document.getElementById('v-x').innerText = Math.round(d.ship.x);
                    document.getElementById('v-y').innerText = Math.round(d.ship.y);
                    document.getElementById('v-z').innerText = Math.round(d.ship.z);
                    document.getElementById('v-vrel-m').innerText = d.ship.v_rel_m.toFixed(4) + " km/s";
                    document.getElementById('v-lat-m').innerText = d.ship.lat_m.toFixed(2) + "°";
                    document.getElementById('v-lon-m').innerText = d.ship.lon_m.toFixed(2) + "°";
                    document.getElementById('v-light').innerText = d.ship.light_e.toFixed(4) + " s";

                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    orion.position.set(ox, oz, oy);
                    moon.position.set(d.moon.x/SCALE, d.moon.z/SCALE, -d.moon.y/SCALE);
                    
                    trailPoints.push(new THREE.Vector3(ox, oz, oy));
                    if(trailPoints.length > 500) trailPoints.shift();
                    trailGeometry.setFromPoints(trailPoints);
                    controls.target.lerp(orion.position, 0.1);
                };
                ws.onclose = () => setTimeout(connect, 2000);
            }

            init3D(); connect();
            function animate() { requestAnimationFrame(animate); earth.rotation.y+=0.001; controls.update(); renderer.render(scene, camera); }
            animate();
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
