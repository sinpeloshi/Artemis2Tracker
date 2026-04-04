import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="Artemis II FIDO System")

# Variable inyectada automáticamente por Railway si enlazas Postgres
DATABASE_URL = os.getenv("DATABASE_URL")

# Lista de conexiones WebSocket activas (celulares viendo la web)
active_connections = set()

async def broadcast_telemetry(conn, pid, channel, payload):
    """
    Esta función se ejecuta CADA VEZ que el worker.py grita datos en Postgres.
    Se conecta con todos los celulares abiertos y les manda el paquete de datos raw.
    """
    dead_connections = set()
    for websocket in active_connections:
        try:
            # Reenviamos el JSON tal cual nos llegó de Postgres
            await websocket.send_text(payload)
        except:
            # Si un celular se desconectó, lo anotamos para borrarlo
            dead_connections.add(websocket)
    
    # Limpiamos los WebSockets muertos
    active_connections.difference_update(dead_connections)

@app.on_event("startup")
async def startup_event():
    print("INICIANDO GATEWAY DE COMUNICACIONES...")
    try:
        # Nos conectamos a PostgreSQL Nucleus
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        # Nos ponemos en escucha (LISTEN) de lo que el worker grite
        await app.state.db_conn.add_listener('telemetry_stream', broadcast_telemetry)
        print("CONECTADO A POSTGRESQL NUCLEUS OK")
    except Exception as e:
        print(f"Error crítico conectando a la base de datos: {e}")

@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            # Mantenemos la conexión viva
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.discard(websocket)

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
        <title>NASA FIDO | Artemis Deep Space Link</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --cian: #00f2ff; --orange: #ff4800; --bg: #000; }
            * { box-sizing: border-box; }
            body, html { margin:0; padding:0; height:100dvh; background:var(--bg); color:#fff; font-family:'Share Tech Mono',monospace; overflow:hidden; touch-action: none;}
            
            #layout { display:flex; flex-direction:column; height:100%; width: 100%;}
            
            /* Viewport 3D (Sección Superior) */
            #viewport { height:60%; position:relative; border-bottom:2px solid var(--cian); background:#000; }
            
            /* HUD Táctico (Sección Inferior) */
            #hud { height:40%; padding:15px; background:rgba(0,10,15,1); display:flex; flex-direction:column; gap:10px; overflow-y: auto;}
            
            .header-info { position:absolute; top:10px; left:10px; z-index:10; pointer-events:none; }
            .tag { display:inline-block; padding:2px 8px; font-size:0.7rem; font-weight:bold; background:var(--cian); color:#000; border-radius: 2px; margin-bottom:2px;}
            #clock { font-size:1.8rem; color:var(--cian); text-shadow:0 0 10px var(--cian); }

            .card { border:1px solid rgba(0,242,255,0.3); background:rgba(0,242,255,0.05); padding:10px; border-radius: 4px; box-shadow: inset 0 0 10px rgba(0,0,0,0.5);}
            .card h2 { margin:0 0 8px 0; font-size:0.8rem; color:var(--cian); letter-spacing:1px;}
            
            .data-row { display:flex; justify-content:space-between; align-items:flex-end; margin-bottom:4px; font-size:0.9rem;}
            .lbl { color:#888; font-size:0.8rem;}
            .val { font-weight:bold; font-size:1.1rem; font-variant-numeric:tabular-nums; }
            .val.orange { color:var(--orange); text-shadow:0 0 5px rgba(255,72,0,0.5); }
            .val.green { color:#0f0; }

            #three-canvas { width:100%; height:100%; display:block; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="layout">
            <div id="viewport">
                <div class="header-info">
                    <div class="tag">● TELEMETRY LINK ACTIVE</div>
                    <div id="clock">00:00:00.000</div>
                </div>
                <div id="three-canvas"></div>
            </div>

            <div id="hud">
                <div class="card" style="border-color: var(--orange);">
                    <h2 style="color: var(--orange);">CÁPSULA ORION (ESTADO VECTORIAL)</h2>
                    <div class="data-row"><span class="lbl">VELOCIDAD INERCIAL</span> <span class="val orange" id="v-vel">0.00000 km/s</span></div>
                    <div class="data-row"><span class="lbl">ALTITUD TIERRA</span> <span class="val" id="v-dist-e">0 km</span></div>
                    <div class="data-row"><span class="lbl">PROXIMIDAD LUNAR</span> <span class="val" id="v-dist-m">0 km</span></div>
                </div>

                <div class="card">
                    <h2>MÉTRICAS DE RED / SISTEMA</h2>
                    <div class="data-row"><span class="lbl">FUENTE DE DATOS</span> <span class="val green" id="v-source">CONNECTING...</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000;
            let scene, camera, renderer, controls;
            let earth, moon, orion;

            // Función para crear carteles de texto 3D que miran a la cámara
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
                camera = new THREE.PerspectiveCamera(50, container.clientWidth / container.clientHeight, 1, 5000000);
                camera.position.set(0, 300, 700);

                renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
                renderer.setSize(container.clientWidth, container.clientHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                container.appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true;

                // --- ILUMINACIÓN REALISTA ESPACIAL ---
                scene.add(new THREE.AmbientLight(0x222222)); // Luz ambiente baja para el espacio profundo
                const sun = new THREE.DirectionalLight(0xffffff, 1.2); // El Sol, luz blanca potente
                sun.position.set(-10, 2, 10);
                scene.add(sun);

                const tl = new THREE.TextureLoader();

                // --- TIERRA FOTOREALISTA ---
                earth = new THREE.Group();
                const eMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(35, 64, 64),
                    new THREE.MeshPhongMaterial({ 
                        map: tl.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg'),
                        specular: 0x333333,
                        shininess: 10
                    })
                );
                earth.add(eMesh);
                const eLbl = createLabel("TIERRA", "#00f2ff");
                eLbl.position.y = 50;
                earth.add(eLbl);
                scene.add(earth);

                // --- LUNA FOTOREALISTA ---
                moon = new THREE.Group();
                const mMesh = new THREE.Mesh(
                    new THREE.SphereGeometry(15, 32, 32),
                    new THREE.MeshStandardMaterial({ map: tl.load('https://raw.githubusercontent.com/mrdoob/three.js/master/examples/textures/planets/moon_1024.jpg') })
                );
                moon.add(mMesh);
                const mLbl = createLabel("OBJETIVO LUNA", "#ffffff");
                mLbl.position.y = 25;
                moon.add(mLbl);
                scene.add(moon);

                // --- MÓDULO ORION TÁCTICO DETALLADO ---
                orion = new THREE.Group();
                const sm = new THREE.Mesh(new THREE.CylinderGeometry(3, 3, 8, 16), new THREE.MeshStandardMaterial({color: 0xcccccc}));
                const cm = new THREE.Mesh(new THREE.ConeGeometry(3, 4, 16), new THREE.MeshStandardMaterial({color: 0x222222}));
                cm.position.y = 6;
                const panelMat = new THREE.MeshBasicMaterial({color: 0x0044aa, side: THREE.DoubleSide});
                const p1 = new THREE.Mesh(new THREE.PlaneGeometry(22, 3), panelMat);
                const p2 = new THREE.Mesh(new THREE.PlaneGeometry(3, 22), panelMat);
                p1.rotation.x = Math.PI/2; p2.rotation.x = Math.PI/2;
                orion.add(sm, cm, p1, p2);
                
                const oLbl = createLabel("ORION", "#ff4800");
                oLbl.position.y = 15;
                orion.add(oLbl);
                scene.add(orion);

                // Fondo de estrellas
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1500; i++){ starsCoords.push((Math.random()-0.5)*4000, (Math.random()-0.5)*4000, (Math.random()-0.5)*4000); }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                scene.add(new THREE.Points(starsGeo, new THREE.PointsMaterial({color: 0xffffff, size: 1.5})));
                
                // Grilla de orientación espacial
                scene.add(new THREE.GridHelper(3000, 50, 0x002222, 0x001111));
            }

            function animate() {
                requestAnimationFrame(animate);
                // --- ROTACIÓN DE LA TIERRA MÁGICA ---
                earth.children[0].rotation.y += 0.001; // Gira lentamente
                orion.rotation.z += 0.01;
                controls.update();
                renderer.render(scene, camera);
            }

            // Conexión WebSocket para datos en vivo
            function connect() {
                const ws = new WebSocket((window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/ws/telemetry');
                ws.onmessage = (e) => {
                    const d = JSON.parse(e.data);
                    document.getElementById('clock').innerText = d.time;
                    document.getElementById('v-source').innerText = d.source;
                    document.getElementById('v-vel').innerText = d.ship.v.toFixed(5) + " km/s";
                    document.getElementById('v-dist-e').innerText = Math.round(d.ship.dist_e).toLocaleString() + " km";
                    document.getElementById('v-dist-m').innerText = Math.round(d.ship.dist_m).toLocaleString() + " km";

                    // Actualizar posiciones 3D (dividiendo por SCALE)
                    const ox = d.ship.x/SCALE, oz = d.ship.z/SCALE, oy = -d.ship.y/SCALE;
                    const mx = d.moon.x/SCALE, mz = d.moon.z/SCALE, my = -d.moon.y/SCALE;
                    
                    orion.position.set(ox, oz, oy); 
                    moon.position.set(mx, mz, my);
                    
                    // La cámara sigue el punto medio táctico
                    controls.target.set(ox/2, oz/2, oy/2);
                };
                ws.onclose = () => setTimeout(connect, 1000); // Reintentar si se corta
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
