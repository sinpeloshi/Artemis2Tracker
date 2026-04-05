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
            #viewport { height:45%; position:relative; border-bottom:1px solid #00f2ff; background: radial-gradient(circle at center, #000810 0%, #000 100%); }
            #hud { height:55%; padding:10px; display:grid; grid-template-columns: 1fr 1fr; gap:8px; background:#010a0c; overflow-y:auto; }
            .card { border:1px solid rgba(0,242,255,0.25); padding:10px; background:rgba(0,242,255,0.03); border-radius: 4px; box-shadow: inset 0 0 15px rgba(0,0,0,0.5); }
            .val { font-weight:bold; color:#00f2ff; float:right; font-variant-numeric: tabular-nums; font-size: 1.1rem;}
            .orange { color:#ff4800; }
            .header { font-size:1.1rem; color:#00f2ff; margin-bottom:8px; letter-spacing: 1px; border-bottom: 1px solid rgba(0,242,255,0.1); padding-bottom: 4px;}
            #three-canvas { width:100%; height:100%; }
            .label-3d { font-size: 0.7rem; color: #00f2ff; background: rgba(0,0,0,0.7); padding: 2px 4px; border: 1px solid #00f2ff; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="viewport">
            <div style="position:absolute; top:12px; left:12px; z-index:10; pointer-events: none;">
                <div id="met" style="font-size:1.6rem; color:#ffcc00; text-shadow: 0 0 10px rgba(255,204,0,0.5)">T+ 00:00:00:00</div>
                <div id="clock" style="color: #00f2ff; opacity: 0.8;">00:00:00 UTC</div>
            </div>
            <div id="three-canvas"></div>
        </div>
        <div id="hud">
            <div class="card" style="grid-column: 1/3; border-color:#ff4800">
                <div class="header orange">ARTEMIS II | MISSION DYNAMICS</div>
                <div style="margin-bottom:6px;">DISTANCIA TIERRA <span class="val" id="d-earth">0 km</span></div>
                <div style="margin-bottom:6px;">DISTANCIA LUNA <span class="val" id="d-moon">0 km</span></div>
                <div>VELOCIDAD INERCIAL <span class="val orange" id="v-inertial">0.000 km/s</span></div>
            </div>
            <div class="card">
                <div class="header" style="font-size:0.8rem; color:#888;">INERTIAL VECTORS (J2000)</div>
                <div>X-AXIS <span class="val" id="v-x">0</span></div>
                <div style="margin: 4px 0;">Y-AXIS <span class="val" id="v-y">0</span></div>
                <div>Z-AXIS <span class="val" id="v-z">0</span></div>
            </div>
            <div class="card">
                <div class="header" style="font-size:0.8rem; color:#888;">NETWORK STATUS</div>
                <div>LIGHT TIME <span class="val" id="v-light">0.000s</span></div>
                <div style="margin-top: 15px;">UPLINK <span class="val" style="color:#0f0" id="v-src">SINCRO</span></div>
            </div>
        </div>
        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls, earth, moon, orion;

            function init3D() {
                scene = new THREE.Scene();
                const container = document.getElementById('three-canvas');
                camera = new THREE.PerspectiveCamera(50, container.clientWidth/container.clientHeight, 1, 2000000);
                camera.position.set(0, 300, 800);
                
                renderer = new THREE.WebGLRenderer({antialias:true, alpha: true});
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);
                
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // --- ILUMINACIÓN PROFESIONAL ---
                scene.add(new THREE.AmbientLight(0x222222));
                const sun = new THREE.DirectionalLight(0xffffff, 1.5);
                sun.position.set(10, 5, 10);
                scene.add(sun);

                const loader = new THREE.TextureLoader();

                // --- TIERRA MEJORADA ---
                const earthGeo = new THREE.SphereGeometry(35, 64, 64);
                const earthMat = new THREE.MeshPhongMaterial({
                    map: loader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg'),
                    specular: new THREE.Color(0x333333),
                    shininess: 5
                });
                earth = new THREE.Mesh(earthGeo, earthMat);
                scene.add(earth);

                // --- LUNA MEJORADA ---
                const moonGeo = new THREE.SphereGeometry(15, 64, 64);
                const moonMat = new THREE.MeshStandardMaterial({
                    map: loader.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg'),
                    roughness: 1,
                    metalness: 0
                });
                moon = new THREE.Mesh(moonGeo, moonMat);
                scene.add(moon);

                // --- CÁPSULA ORION REALISTA ---
                orion = new THREE.Group();
                
                // Módulo de Servicio (Cilindro)
                const serviceBody = new THREE.Mesh(
                    new THREE.CylinderGeometry(2.5, 2.5, 6, 16),
                    new THREE.MeshStandardMaterial({color: 0xcccccc, metalness: 0.5, roughness: 0.3})
                );
                
                // Cápsula de Tripulación (Cono truncado)
                const capsule = new THREE.Mesh(
                    new THREE.CylinderGeometry(1, 2.5, 3, 16),
                    new THREE.MeshStandardMaterial({color: 0x333333, metalness: 0.8})
                );
                capsule.position.y = 4.5;
                
                // Paneles Solares (4 en forma de X)
                const panelGeo = new THREE.PlaneGeometry(12, 2.5);
                const panelMat = new THREE.MeshStandardMaterial({color: 0x0044aa, side: THREE.DoubleSide, emissive: 0x001133});
                
                for(let i=0; i<4; i++) {
                    const panel = new THREE.Mesh(panelGeo, panelMat);
                    panel.position.y = 0;
                    panel.rotation.y = (Math.PI / 2) * i + (Math.PI / 4);
                    panel.position.x = Math.cos(panel.rotation.y) * 8;
                    panel.position.z = -Math.sin(panel.rotation.y) * 8;
                    panel.rotation.x = Math.PI / 2;
                    orion.add(panel);
                }
                
                orion.add(serviceBody, capsule);
                scene.add(orion);

                // Fondo de Estrellas y Grilla
                const starGeo = new THREE.BufferGeometry();
                const starCoords = [];
                for(let i=0; i<2000; i++) {
                    starCoords.push((Math.random()-0.5)*10000, (Math.random()-0.5)*10000, (Math.random()-0.5)*10000);
                }
                starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starCoords, 3));
                const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({color: 0xffffff, size: 1.5}));
                scene.add(stars);
                
                scene.add(new THREE.GridHelper(3000, 40, 0x002222, 0x001111));
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
                    document.getElementById('v-x').innerText = Math.round(d.ship.x).toLocaleString();
                    document.getElementById('v-y').innerText = Math.round(d.ship.y).toLocaleString();
                    document.getElementById('v-z').innerText = Math.round(d.ship.z).toLocaleString();
                    document.getElementById('v-light').innerText = d.ship.light_e.toFixed(4) + " s";
                    
                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    orion.position.set(ox, oz, oy);
                    moon.position.set(d.moon.x/SCALE, d.moon.z/SCALE, -d.moon.y/SCALE);
                    
                    // Apuntar la cápsula hacia la dirección de movimiento (Luna)
                    orion.lookAt(moon.position);
                    orion.rotateX(Math.PI/2);
                    
                    controls.target.lerp(orion.position, 0.1);
                };
                ws.onclose = () => setTimeout(connect, 2000);
            }

            init3D(); connect();
            function animate() { 
                requestAnimationFrame(animate); 
                if(earth) earth.rotation.y += 0.0005; 
                controls.update(); 
                renderer.render(scene, camera); 
            }
            animate();
            
            window.addEventListener('resize', () => {
                const c = document.getElementById('three-canvas');
                camera.aspect = c.clientWidth/c.clientHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(c.clientWidth, c.clientHeight);
            });
        </script>
    </body>
    </html>
    """)
