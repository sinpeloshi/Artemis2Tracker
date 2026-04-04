from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math
import httpx
import asyncio
from datetime import datetime, timedelta

app = FastAPI(title="Artemis 2 - NextGen MOC (Three.js)")

# Motor Astronómico Core (Datos NASA Reales)
eph = load('de421.bsp')
earth_eph, moon_eph = eph['earth'], eph['moon']
ts = load.timescale()

# Memoria Caché para Base de Datos JPL Horizons
nasa_cache = {
    "orion_data": None,
    "last_update": datetime.min
}

async def fetch_jpl_horizons():
    """Conexión Directa a NASA JPL para Telemetría Cruda"""
    NAIF_ID = '-121' # Típico ID de Artemis
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
                soe_index = data.find("$$SOE")
                eoe_index = data.find("$$EOE")
                lines = data[soe_index:eoe_index].split('\n')
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
    
    # ASTROMETRÍA PRECISA (Luna)
    astrometric_moon = earth_eph.at(t).observe(moon_eph)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    v_moon_x, v_moon_y, v_moon_z = astrometric_moon.velocity.km_per_s
    
    dist_moon_earth = math.sqrt(x_moon**2 + y_moon**2 + z_moon**2)
    vel_moon = math.sqrt(v_moon_x**2 + v_moon_y**2 + v_moon_z**2)
    
    # ENLACE JPL HORIZONS (Orion)
    if (now - nasa_cache["last_update"]).total_seconds() > 60:
        jpl_data = await fetch_jpl_horizons()
        if jpl_data:
            nasa_cache["orion_data"] = jpl_data
            nasa_cache["last_update"] = now

    orion = nasa_cache["orion_data"]
    
    if orion:
        x_orion, y_orion, z_orion = orion["x"], orion["y"], orion["z"]
        vel_orion = math.sqrt(orion["vx"]**2 + orion["vy"]**2 + orion["vz"]**2)
        source, status = "DSN/JPL HORIZONS LOCK", "NOMINAL"
    else:
        # Fallback simulation
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
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>Artemis II | NextGen Tactical MOC</title>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            
            :root { --bg: #000000; --panel-bg: rgba(0, 15, 25, 0.8); --neon-cian: #00ffff; --neon-orange: #ff5500; --neon-green: #00ff88; }
            
            body, html { margin: 0; padding: 0; height: 100%; background-color: var(--bg); color: #fff; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            
            /* Scanlines overlay */
            body::after { content: " "; display: block; position: fixed; top: 0; left: 0; bottom: 0; right: 0; background: linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.1) 50%); z-index: 999; background-size: 100% 4px; pointer-events: none; opacity: 0.5;}
            
            #dashboard { display: flex; flex-direction: column; height: 100dvh; width: 100vw; position: relative; z-index: 10; pointer-events: none;}
            
            /* HUD Top */
            .header { height: 50px; display: flex; justify-content: space-between; align-items: center; padding: 0 15px; border-bottom: 1px solid rgba(0,255,255,0.3); background: var(--panel-bg); backdrop-filter: blur(5px); flex-shrink: 0; pointer-events: auto;}
            h1 { font-size: 1.1rem; color: var(--neon-cian); text-transform: uppercase; margin: 0; text-shadow: 0 0 10px var(--neon-cian); letter-spacing: 1px;}
            .blinking-dot { display: inline-block; width: 8px; height: 8px; background-color: var(--neon-green); border-radius: 50%; margin-right: 8px; animation: blink 1.2s infinite; box-shadow: 0 0 10px var(--neon-green); }
            @keyframes blink { 0% {opacity: 1;} 50% {opacity: 0.1;} 100% {opacity: 1;} }
            #sys-time { color: #fff; font-weight: bold; font-size: 0.9rem; }

            /* HUD Bottom Telemetry */
            #telemetry-fido { margin-top: auto; background: var(--panel-bg); border-top: 1px solid rgba(0,255,255,0.3); padding: 15px; backdrop-filter: blur(5px); pointer-events: auto; max-height: 40dvh; overflow-y: auto;}
            .data-group { border: 1px solid rgba(0,255,255,0.1); padding: 10px; background: rgba(0,255,255,0.02); margin-bottom: 10px; }
            .data-group h3 { margin: 0 0 8px 0; font-size: 0.8rem; color: #888; border-bottom: 1px dotted #444; padding-bottom: 4px; text-transform: uppercase; letter-spacing: 1px;}
            .metric { display: flex; justify-content: space-between; font-size: 0.85rem; margin-bottom: 6px; }
            .metric .label { color: #aaa; }
            .metric .val { font-weight: 700; color: var(--neon-orange); text-shadow: 0 0 5px rgba(255,85,0,0.5); }
            .metric .val.green { color: var(--neon-green); text-shadow: 0 0 5px rgba(0,255,136,0.5); }
            .metric .val.white { color: #fff; text-shadow: none; }

            /* Three.js Container */
            #three-container { position: fixed; top: 0; left: 0; width: 100vw; height: 100dvh; z-index: 1; }
        </style>
        
        # MOTOR 3D: Three.js y Controles
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        # El Contenedor WebGL puro
        <div id="three-container"></div>

        # El HUD Táctico (Overlay)
        <div id="dashboard">
            <div class="header">
                <div style="display: flex; align-items: center;"><span class="blinking-dot"></span><h1>Artemis FIDO</h1></div>
                <div id="sys-time">00:00:00 UTC</div>
            </div>

            <div id="telemetry-fido">
                <div class="data-group">
                    <h3>UPLINK STATUS</h3>
                    <div class="metric"><span class="label">SOURCE:</span> <span class="val green" id="v-source">--</span></div>
                    <div class="metric"><span class="label">INTEGRITY:</span> <span class="val green" id="v-status">--</span></div>
                </div>

                <div class="data-group" style="border-color: rgba(255,85,0,0.3)">
                    <h3 style="color: var(--neon-orange);">ORION CAPSULE</h3>
                    <div class="metric"><span class="label">INERTIAL VEL:</span> <span class="val" id="o-vel">0.000 km/s</span></div>
                    <div class="metric"><span class="label">ALT (EARTH):</span> <span class="val" id="o-dist-e">0.00 km</span></div>
                    <div class="metric"><span class="label">DIST (MOON):</span> <span class="val" id="o-dist-m">0.00 km</span></div>
                </div>

                <div class="data-group">
                    <h3>LUNAR TARGET</h3>
                    <div class="metric"><span class="label">ORBITAL VEL:</span> <span class="val white" id="m-vel">0.000 km/s</span></div>
                    <div class="metric"><span class="label">EARTH DIST:</span> <span class="val white" id="m-dist">0.00 km</span></div>
                </div>
            </div>
        </div>

        <script>
            // === CONFIGURACIÓN GLOBAL THREE.JS ===
            // Escala 1:1000 para renderizado estable en móvil
            const SCALE = 1000; 
            let scene, camera, renderer, controls;
            let earth, moon, orion, sunLight;
            let orionTrail, trailPositions = [];
            const MAX_TRAIL_POINTS = 500;

            function initThree() {
                // 1. Escena y Niebla espacial
                scene = new THREE.Scene();
                scene.fog = new THREE.FogExp2(0x000000, 0.000005);

                // 2. Cámara Perspective optimizada para profundidad
                camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 1, 2000000);
                camera.position.set(100, 100, 300); // Posición inicial táctica

                // 3. Renderer WebGL con Antialias (suavizado)
                renderer = new THREE.WebGLRenderer({ antialias: true });
                renderer.setSize(window.innerWidth, window.innerHeight);
                renderer.setPixelRatio(window.devicePixelRatio);
                document.getElementById('three-container').appendChild(renderer.domElement);

                // 4. Controles Táctiles (OrbitControls)
                controls = new THREE.OrbitControls(camera, renderer.domElement);
                controls.enableDamping = true; controls.dampingFactor = 0.05;
                controls.minDistance = 10; controls.maxDistance = 1000000 / SCALE;

                // 5. ILUMINACIÓN ESPACIAL (Luz del Sol)
                // Luz ambiental suave para ver el lado oscuro
                scene.add(new THREE.AmbientLight(0x111122)); 
                // Luz direccional potente (simula el Sol desde el ángulo estándar)
                sunLight = new THREE.DirectionalLight(0xffffff, 1.2);
                sunLight.position.set(-1, 0.5, 1).normalize();
                scene.add(sunLight);

                // 6. CREACIÓN DE OBJETOS CELSTES (Con Texturas Reales)
                const textureLoader = new THREE.TextureLoader();

                // TIERRA (Radio ~6371km -> 6.37 unidades Three.js)
                // Usamos BasicMaterial con wireframe cian para estética táctica y performance
                // (Cambiar a MeshPhongMaterial + map para textura real si Railway lo aguanta)
                const earthGeo = new THREE.SphereGeometry(6371 / SCALE, 32, 32);
                const earthMat = new THREE.MeshBasicMaterial({ 
                    color: 0x00ddee, wireframe: true, transparent: true, opacity: 0.4 
                });
                earth = new THREE.Mesh(earthGeo, earthMat);
                scene.add(earth);
                
                // Resplandor atmosférico táctico
                const atmoGeo = new THREE.SphereGeometry((6371+200) / SCALE, 32, 32);
                const atmoMat = new THREE.MeshBasicMaterial({ color: 0x00ffff, side: THREE.BackSide, transparent: true, opacity: 0.1 });
                scene.add(new THREE.Mesh(atmoGeo, atmoMat));

                // LUNA (Radio ~1737km -> 1.73 unidades)
                // Textura procedural de cráteres simple para performance
                const moonGeo = new THREE.SphereGeometry(1737 / SCALE, 24, 24);
                const moonMat = new THREE.MeshPhongMaterial({ color: 0xaaaaaa, shininess: 0 });
                moon = new THREE.Mesh(moonGeo, moonMat);
                scene.add(moon);

                // ORION (Modelo esquemático texturizado)
                // Creamos un grupo para el Módulo de Mando (Cono) y Servicio (Cilindro)
                orion = new THREE.Group();
                
                // Módulo de Mando (Cono metálico)
                const cmGeo = new THREE.ConeGeometry(2 / SCALE, 3 / SCALE, 8);
                const cmMat = new THREE.MeshPhongMaterial({color: 0xcccccc, specular: 0xffffff});
                const commandModule = new THREE.Mesh(cmGeo, cmMat);
                commandModule.rotation.x = Math.PI; // Apunta hacia adelante
                orion.add(commandModule);

                // Módulo de Servicio (Cilindro blanco)
                const smGeo = new THREE.CylinderGeometry(2 / SCALE, 2 / SCALE, 4 / SCALE, 8);
                const smMat = new THREE.MeshPhongMaterial({color: 0xffffff});
                const serviceModule = new THREE.Mesh(smGeo, smMat);
                serviceModule.position.y = 3.5 / SCALE;
                orion.add(serviceModule);
                
                // Glow táctico rojo alrededor de la nave
                const orionGlow = new THREE.PointLight(0xff3300, 1.5, 50 / SCALE);
                orion.add(orionGlow);
                
                scene.add(orion);

                // 7. TRAYECTORIA (Trail Line)
                const trailMat = new THREE.LineBasicMaterial({ color: 0xff3300, transparent: true, opacity: 0.6 });
                const trailGeo = new THREE.BufferGeometry();
                orionTrail = new THREE.Line(trailGeo, trailMat);
                scene.add(orionTrail);

                // 8. FONDO DE ESTRELLAS (Starfield 3D real)
                const starsGeo = new THREE.BufferGeometry();
                const starsCoords = [];
                for(let i=0; i<1500; i++) {
                    starsCoords.push((Math.random()-0.5)*2e6/SCALE, (Math.random()-0.5)*2e6/SCALE, (Math.random()-0.5)*2e6/SCALE);
                }
                starsGeo.setAttribute('position', new THREE.Float32BufferAttribute(starsCoords, 3));
                const starsMat = new THREE.PointsMaterial({color: 0xffffff, size: 1/SCALE, sizeAttenuation: true});
                scene.add(new THREE.Points(starsGeo, starsMat));

                // 9. Cuadrícula de Referencia Táctica (Plano Eclíptico)
                const gridHelper = new THREE.GridHelper(800000/SCALE, 40, 0x002222, 0x001111);
                scene.add(gridHelper);
            }

            // === BUCLE DE ANIMACIÓN (60 FPS) ===
            function animate() {
                requestAnimationFrame(animate);
                
                // Rotación de la Tierra (lenta, estética)
                if(earth) earth.rotation.y += 0.0005;
                
                // Actualizar controles táctiles
                if(controls) controls.update();
                
                // Renderizar la escena
                if(renderer && scene && camera) renderer.render(scene, camera);
            }

            // === ACTUALIZACIÓN DE DATOS (Telemetría Web Socket / Polling) ===
            async function updateTelemetry() {
                try {
                    const res = await fetch('/api/telemetry');
                    const d = await res.json();
                    
                    // 1. Actualizar HUD Texto
                    document.getElementById('sys-time').innerText = d.sys_time;
                    document.getElementById('v-source').innerText = d.signal.source;
                    document.getElementById('v-status').innerText = d.signal.status;
                    document.getElementById('v-status').style.color = d.signal.status === 'NOMINAL' ? '#00ff88' : '#ffea00';
                    
                    document.getElementById('o-vel').innerText = d.orion.v_kms.toFixed(4) + ' km/s';
                    document.getElementById('o-dist-e').innerText = d.orion.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';
                    document.getElementById('o-dist-m').innerText = d.orion.dist_moon_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';
                    
                    document.getElementById('m-vel').innerText = d.moon.v_kms.toFixed(4) + ' km/s';
                    document.getElementById('m-dist').innerText = d.moon.dist_km.toLocaleString('en-US', {maximumFractionDigits: 1}) + ' km';

                    // 2. Actualizar Posiciones 3D (Escaladas a 1:1000)
                    // Mapeo astronómico: Skyfield XYZ -> Three.js XYZ (Ajustamos ejes si es necesario)
                    if(moon) moon.position.set(d.moon.x / SCALE, d.moon.z / SCALE, -d.moon.y / SCALE);
                    if(orion) {
                        const ox = d.orion.x / SCALE;
                        const oy = d.orion.z / SCALE;
                        const oz = -d.orion.y / SCALE;
                        orion.position.set(ox, oy, oz);
                        
                        // Orientación básica de la nave (apuntando a la Luna)
                        if(moon) orion.lookAt(moon.position);

                        // 3. Actualizar Trayectoria (Trail)
                        trailPositions.push(ox, oy, oz);
                        if(trailPositions.length > MAX_TRAIL_POINTS * 3) {
                            trailPositions.splice(0, 3); // Eliminar punto más antiguo
                        }
                        orionTrail.geometry.setAttribute('position', new THREE.Float32BufferAttribute(trailPositions, 3));
                        orionTrail.geometry.attributes.position.needsUpdate = true;
                    }

                } catch (err) { console.error("FIDO Telemetry LOS:", err); }
            }

            // Manejo de cambio de tamaño de ventana (rotación de móvil)
            window.addEventListener('resize', () => {
                camera.aspect = window.innerWidth / window.innerHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(window.innerWidth, window.innerHeight);
            });

            // LIIIIIFFTOFF!
            initThree();
            animate();
            updateTelemetry();
            setInterval(updateTelemetry, 3000); // Radar refresh cada 3s

        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
