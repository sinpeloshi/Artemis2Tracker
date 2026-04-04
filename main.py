from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - MOC Tactical View")

# Motor Astronómico
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
            response = await client.get(url, params=params, timeout=8.0)
            data = response.text
            if "$$SOE" in data:
                soe = data.find("$$SOE")
                eoe = data.find("$$EOE")
                lines = data[soe:eoe].split('\n')
                for line in lines:
                    if "X =" in line and "Y =" in line:
                        p = line.split()
                        x, y, z = float(p[2]), float(p[5]), float(p[8])
                    elif "VX=" in line and "VY=" in line:
                        p = line.split()
                        vx, vy, vz = float(p[1]), float(p[3]), float(p[5])
                        return {"x": x, "y": y, "z": z, "vx": vx, "vy": vy, "vz": vz}
        except Exception:
            return None
    return None

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    now = datetime.utcnow()
    
    astrometric_moon = earth_eph.at(t).observe(moon_eph)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    v_moon_x, v_moon_y, v_moon_z = astrometric_moon.velocity.km_per_s
    
    dist_moon_earth = math.sqrt(x_moon**2 + y_moon**2 + z_moon**2)
    vel_moon = math.sqrt(v_moon_x**2 + v_moon_y**2 + v_moon_z**2)
    
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl = await fetch_jpl_horizons()
        if jpl:
            nasa_cache["orion_data"] = jpl
            nasa_cache["last_update"] = now

    orion = nasa_cache["orion_data"]
    
    if orion:
        x_orion, y_orion, z_orion = orion["x"], orion["y"], orion["z"]
        vel_orion = math.sqrt(orion["vx"]**2 + orion["vy"]**2 + orion["vz"]**2)
        source, status = "DSN/JPL HORIZONS LOCK", "NOMINAL"
    else:
        x_orion, y_orion, z_orion = x_moon * 0.88, y_moon * 0.88, z_moon * 0.88 + 12500
        vel_orion = 1.152
        source, status = "INTERNAL SIM (FAIL-SAFE)", "DEGRADED"

    dist_orion_earth = math.sqrt(x_orion**2 + y_orion**2 + z_orion**2)
    dist_orion_moon = math.sqrt((x_moon-x_orion)**2 + (y_moon-y_orion)**2 + (z_moon-z_orion)**2)
    
    return {
        "sys_time": t.utc_strftime('%H:%M:%S UTC'),
        "signal": {"source": source, "status": status},
        "moon": {"x": x_moon, "y": y_moon, "z": z_moon, "dist_km": dist_moon_earth, "v_kms": vel_moon},
        "orion": {"x": x_orion, "y": y_orion, "z": z_orion, "dist_earth_km": dist_orion_earth, "dist_moon_km": dist_orion_moon, "v_kms": vel_orion}
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Artemis II | MOC Tactical</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            :root { --bg: #020508; --panel-bg: rgba(0, 15, 25, 0.85); --neon-cian: #00ffff; --neon-orange: #ff5500; --neon-green: #00ff88; }
            body, html { margin: 0; padding: 0; height: 100%; background-color: var(--bg); color: #fff; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            body::after { content: " "; display: block; position: fixed; top: 0; left: 0; bottom: 0; right: 0; background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.2) 50%); z-index: 999; background-size: 100% 3px; pointer-events: none;}
            #dashboard { display: flex; flex-direction: column; height: 100dvh; width: 100vw; position: relative; z-index: 10; pointer-events: none;}
            
            .header { height: 50px; display: flex; justify-content: space-between; align-items: center; padding: 0 15px; border-bottom: 1px solid rgba(0,255,255,0.3); background: var(--panel-bg); flex-shrink: 0; pointer-events: auto;}
            h1 { font-size: 1.1rem; color: var(--neon-cian); margin: 0; text-shadow: 0 0 8px var(--neon-cian); }
            .dot { display: inline-block; width: 8px; height: 8px; background-color: var(--neon-green); border-radius: 50%; margin-right: 8px; animation: blink 1.2s infinite; }
            @keyframes blink { 0%, 100% {opacity: 1;} 50% {opacity: 0.2;} }
            #sys-time { font-weight: bold; font-size: 0.9rem; }

            #telemetry-fido { margin-top: auto; background: var(--panel-bg); border-top: 1px solid rgba(0,255,255,0.3); padding: 15px; pointer-events: auto; max-height: 40dvh; overflow-y: auto;}
            .data-group { border: 1px solid rgba(0,255,255,0.1); padding: 8px; margin-bottom: 8px; }
            .data-group h3 { margin: 0 0 5px 0; font-size: 0.8rem; color: #888; border-bottom: 1px dotted #444; padding-bottom: 4px; }
            .metric { display: flex; justify-content: space-between; font-size: 0.8rem; margin-bottom: 4px; }
            .metric .label { color: #aaa; }
            .metric .val { font-weight: 700; color: var(--neon-orange); }
            .metric .val.green { color: var(--neon-green); }

            #three-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh; z-index: 1; }
        </style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <div id="three-container"></div>
        <div id="dashboard">
            <div class="header">
                <div style="display: flex; align-items: center;"><span class="dot"></span><h1>RADAR ESPACIAL</h1></div>
                <div id="sys-time">00:00:00 UTC</div>
            </div>
            <div id="telemetry-fido">
                <div class="data-group">
                    <h3>ESTADO DEL ENLACE</h3>
                    <div class="metric"><span class="label">FUENTE:</span> <span class="val green" id="v-source">--</span></div>
                </div>
                <div class="data-group" style="border-color: rgba(255,85,0,0.3)">
                    <h3 style="color: var(--neon-orange);">CÁPSULA ORION</h3>
                    <div class="metric"><span class="label">VELOCIDAD:</span> <span class="val" id="o-vel">0.000 km/s</span></div>
                    <div class="metric"><span class="label">DIST (TIERRA):</span> <span class="val" id="o-dist-e">0.00 km</span></div>
                    <div class="metric"><span class="label">DIST (LUNA):</span> <span class="val" id="o-dist-m">0.00 km</span></div>
                </div>
                <div class="data-group">
                    <h3>OBJETIVO LUNAR</h3>
                    <div class="metric"><span class="label">DIST (TIERRA):</span> <span class="val" style="color:#fff;" id="m-dist">0.00 km</span></div>
                </div>
            </div>
        </div>

        <script>
            const SCALE = 1000; 
            let scene, camera, renderer, controls;
            let earth, moon, orion;
            let orbitLine;

            function initThree() {
                scene = new THREE.Scene();
                
                // CÁMARA: Vista isométrica bien lejana (arriba y atrás) para ver todo el tablero
                camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 1, 2000000);
                camera.position.set(0, 450, 600); 

                renderer = new THREE.WebGLRenderer({ antialias: true });
                renderer.setSize(window.innerWidth, window.innerHeight);
                document.getElementById('three-container').appendChild(renderer.domElement);

                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true; 
                controls.dampingFactor = 0.05;

                scene.add(new THREE.AmbientLight(0x333344)); 
                const sunLight = new THREE.DirectionalLight(0xffffff, 1.5);
                sunLight.position.set(-1, 0.5, 1).normalize();
                scene.add(sunLight);

                // TIERRA: Tamaño exagerado (Radio de 25 en vez de 6)
                const earthGeo = new THREE.SphereGeometry(25, 32, 32);
                const earthMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, wireframe: true });
                earth = new THREE.Mesh(earthGeo, earthMat);
                scene.add(earth);

                // LUNA: Tamaño exagerado (Radio de 12 en vez de 1.7)
                const moonGeo = new THREE.SphereGeometry(12, 24, 24);
                const moonMat = new THREE.MeshPhongMaterial({ color: 0xcccccc, flatShading: true });
                moon = new THREE.Mesh(moonGeo, moonMat);
                scene.add(moon);

                // ORION: Tamaño exagerado para que sea visible (Cubo rojo brillante)
                const orionGeo = new THREE.BoxGeometry(8, 8, 8);
                const orionMat = new THREE.MeshBasicMaterial({ color: 0xff3300 });
                orion = new THREE.Mesh(orionGeo, orionMat);
                scene.add(orion);

                // LÍNEA DE ÓRBITA LUNAR (Para dar perspectiva del espacio)
                const orbitGeo = new THREE.RingGeometry(384, 385, 64);
                const orbitMat = new THREE.MeshBasicMaterial({ color: 0x444444, side: THREE.DoubleSide });
                orbitLine = new THREE.Mesh(orbitGeo, orbitMat);
                orbitLine.rotation.x = Math.PI / 2;
                scene.add(orbitLine);

                // ESTRELLAS
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1500; i++) {
                    starsCoords.push((Math.random()-0.5)*3000, (Math.random()-0.5)*3000, (Math.random()-0.5)*3000);
                }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                const starsMat = new THREE.PointsMaterial({color: 0xffffff, size: 2});
                scene.add(new THREE.Points(starsGeo, starsMat));

                // GRID (Rejilla táctica)
                const gridHelper = new THREE.GridHelper(1500, 30, 0x004444, 0x001111);
                scene.add(gridHelper);
            }

            function animate() {
                requestAnimationFrame(animate);
                earth.rotation.y += 0.002;
                controls.update();
                renderer.render(scene, camera);
            }

            async function updateTelemetry() {
                try {
                    const res = await fetch('/api/telemetry');
                    const d = await res.json();
                    
                    document.getElementById('sys-time').innerText = d.sys_time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('v-source').style.color = d.signal.status === 'NOMINAL' ? '#00ff88' : '#ffaa00';
                    
                    document.getElementById('o-vel').innerText = d.orion.v_kms.toFixed(3) + ' km/s';
                    document.getElementById('o-dist-e').innerText = d.orion.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' km';
                    document.getElementById('o-dist-m').innerText = d.orion.dist_moon_km.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' km';
                    document.getElementById('m-dist').innerText = d.moon.dist_km.toLocaleString('en-US', {maximumFractionDigits: 0}) + ' km';

                    const mx = d.moon.x / SCALE;
                    const mz = d.moon.z / SCALE;
                    const my = -d.moon.y / SCALE;

                    const ox = d.orion.x / SCALE;
                    const oz = d.orion.z / SCALE;
                    const oy = -d.orion.y / SCALE;

                    moon.position.set(mx, mz, my);
                    orion.position.set(ox, oz, oy);

                    // MAGIA DE CÁMARA: El centro de control ahora apunta al centro de la acción
                    // En lugar de mirar a la Tierra (0,0,0), miramos al punto medio entre la Tierra y la nave.
                    controls.target.set(ox / 2, oz / 2, oy / 2);

                } catch (err) { console.error(err); }
            }

            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            initThree();
            animate();
            updateTelemetry();
            setInterval(updateTelemetry, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
