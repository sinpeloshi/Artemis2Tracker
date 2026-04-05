import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI()
DATABASE_URL = os.getenv("DATABASE_ARTEMIS")
active_connections = set()

async def broadcast_telemetry(conn, pid, channel, payload):
    for ws in list(active_connections):
        try: await ws.send_text(payload)
        except: active_connections.discard(ws)

@app.on_event("startup")
async def startup():
    app.state.db_conn = await asyncpg.connect(DATABASE_URL)
    await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect: active_connections.discard(websocket)

@app.get("/")
async def get():
    return HTMLResponse(content="""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>NASA FIDO | Artemis II Master Console</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            body { margin:0; background:#000; color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; font-size:12px; }
            #viewport { height:40%; position:relative; border-bottom:1px solid #00f2ff; }
            #hud { height:60%; padding:10px; display:grid; grid-template-columns: 1fr 1fr; gap:5px; background:#010a0c; overflow-y:auto; }
            .card { border:1px solid rgba(0,242,255,0.3); padding:8px; background:rgba(0,242,255,0.02); }
            .val { font-weight:bold; color:#00f2ff; float:right; }
            .orange { color:#ff4800; }
            .header { font-size:1.4rem; color:#00f2ff; margin-bottom:5px; }
            #three-canvas { width:100%; height:100%; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="viewport">
            <div style="position:absolute; top:10px; left:10px; z-index:10">
                <div id="met" style="font-size:1.2rem; color:#ffcc00">T+ 00:00:00:00</div>
                <div id="clock">00:00:00 UTC</div>
            </div>
            <div id="three-canvas"></div>
        </div>
        <div id="hud">
            <div class="card" style="grid-column: 1/3; border-color:#ff4800">
                <div class="header orange">ARTEMIS II | TELEMETRÍA DE TRÁNSITO</div>
                <div>DISTANCIA TIERRA <span class="val" id="d-earth">0 km</span></div>
                <div>DISTANCIA LUNA <span class="val" id="d-moon">0 km</span></div>
                <div>VELOCIDAD INERCIAL <span class="val orange" id="v-inertial">0 km/s</span></div>
            </div>
            <div class="card">
                <div style="color:#888">VECTORES J2000</div>
                <div>X <span class="val" id="v-x">0</span></div>
                <div>Y <span class="val" id="v-y">0</span></div>
                <div>Z <span class="val" id="v-z">0</span></div>
            </div>
            <div class="card">
                <div style="color:#888">SISTEMA</div>
                <div>LATENCIA LUZ <span class="val" id="v-light">0s</span></div>
                <div>STATUS <span class="val" style="color:#0f0" id="v-src">SINCRO</span></div>
            </div>
        </div>
        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls, earth, moon, orion;
            function init3D() {
                scene = new THREE.Scene();
                camera = new THREE.PerspectiveCamera(50, window.innerWidth/(window.innerHeight*0.4), 1, 1000000);
                camera.position.set(0, 400, 600);
                renderer = new THREE.WebGLRenderer({antialias:true});
                renderer.setSize(window.innerWidth, window.innerHeight*0.4);
                document.getElementById('three-canvas').appendChild(renderer.domElement);
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                scene.add(new THREE.AmbientLight(0x444444));
                const sun = new THREE.DirectionalLight(0xffffff, 1); sun.position.set(5,3,5); scene.add(sun);
                earth = new THREE.Mesh(new THREE.SphereGeometry(35,32,32), new THREE.MeshPhongMaterial({map: new THREE.TextureLoader().load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg')}));
                scene.add(earth);
                moon = new THREE.Mesh(new THREE.SphereGeometry(15,32,32), new THREE.MeshStandardMaterial({color:0x888888}));
                scene.add(moon);
                orion = new THREE.Mesh(new THREE.CylinderGeometry(2,2,5,8), new THREE.MeshStandardMaterial({color:0xff4800}));
                scene.add(orion);
                scene.add(new THREE.GridHelper(2000, 20, 0x002222, 0x001111));
            }
            function connect() {
                const ws = new WebSocket((location.protocol==='https:'?'wss:':'ws:') + '//' + location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('met').innerText = d.met;
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('d-earth').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('d-moon').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";
                    document.getElementById('v-inertial').innerText = d.ship.v.toFixed(3) + " km/s";
                    document.getElementById('v-x').innerText = Math.round(d.ship.x);
                    document.getElementById('v-y').innerText = Math.round(d.ship.y);
                    document.getElementById('v-z').innerText = Math.round(d.ship.z);
                    document.getElementById('v-light').innerText = d.ship.light_e.toFixed(4) + " s";
                    orion.position.set(d.ship.x/SCALE, d.ship.z/SCALE, -d.ship.y/SCALE);
                    moon.position.set(d.moon.x/SCALE, d.moon.z/SCALE, -d.moon.y/SCALE);
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
    """)
