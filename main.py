"""
main.py — Artemis II FIDO Console
FastAPI + WebSocket + Three.js
Datos reales: JPL Horizons API vía worker.py
"""

import os
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncpg

app = FastAPI(title="Artemis II FIDO Console")
DATABASE_URL = os.getenv("DATABASE_ARTEMIS")

# Set thread-safe en un único proceso (uvicorn --workers 1)
active_connections: set[WebSocket] = set()


async def broadcast_telemetry(conn, pid, channel, payload):
    dead = set()
    for ws in list(active_connections):
        try:
            await ws.send_text(payload)
        except Exception:
            dead.add(ws)
    active_connections.difference_update(dead)


@app.on_event("startup")
async def startup():
    if DATABASE_URL:
        app.state.db_conn = await asyncpg.connect(DATABASE_URL)
        await app.state.db_conn.add_listener("telemetry_stream", broadcast_telemetry)


@app.on_event("shutdown")
async def shutdown():
    if hasattr(app.state, "db_conn"):
        try:
            await app.state.db_conn.remove_listener("telemetry_stream", broadcast_telemetry)
        finally:
            await app.state.db_conn.close()


@app.websocket("/ws/telemetry")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.add(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        active_connections.discard(websocket)
    except Exception:
        active_connections.discard(websocket)


@app.get("/")
async def get():
    return HTMLResponse(content=HTML)


# ─────────────────────────────────────────────────────────────────────────────
# Frontend HTML/JS
# ─────────────────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">
  <title>NASA FIDO | Artemis II Live Console</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: 100%; height: 100%; background: #000; color: #e0e0e0;
                 font-family: 'Share Tech Mono', monospace; overflow: hidden; }

    /* ── Layout ── */
    #viewport  { height: 45vh; position: relative; border-bottom: 1px solid #00f2ff44; }
    #hud       { height: 55vh; display: grid; grid-template-columns: 1fr 1fr 1fr;
                 gap: 6px; padding: 8px; background: #010a0c; overflow-y: auto; }

    /* ── Tarjetas ── */
    .card {
      border: 1px solid #00f2ff33;
      background: rgba(0,242,255,.03);
      padding: 8px 10px;
      font-size: 11px;
    }
    .card-title {
      color: #00f2ff99;
      font-size: 10px;
      letter-spacing: .12em;
      text-transform: uppercase;
      margin-bottom: 6px;
      border-bottom: 1px solid #00f2ff22;
      padding-bottom: 4px;
    }
    .row  { display: flex; justify-content: space-between; margin: 3px 0; }
    .lbl  { color: #ffffff66; }
    .val  { color: #00f2ff; font-weight: bold; }
    .val.orange  { color: #ff6030; }
    .val.green   { color: #00ff88; }
    .val.yellow  { color: #ffcc00; }
    .val.red     { color: #ff3030; }

    /* ── Encabezado en el viewport ── */
    #overlay {
      position: absolute; top: 10px; left: 12px; z-index: 10;
      pointer-events: none;
    }
    #overlay .mission { font-size: 13px; color: #ffcc00; letter-spacing: .08em; }
    #overlay .met     { font-size: 22px; color: #ffcc00; font-weight: bold; line-height: 1.1; }
    #overlay .utc     { font-size: 12px; color: #ffffff88; }

    /* ── Badge de fuente de datos ── */
    #src-badge {
      position: absolute; top: 10px; right: 12px; z-index: 10;
      padding: 3px 9px; border-radius: 3px; font-size: 10px;
      letter-spacing: .1em; border: 1px solid currentColor;
      transition: color .4s, border-color .4s, background .4s;
    }
    #src-badge.live   { color: #00ff88; background: #00ff8818; }
    #src-badge.cached { color: #ffcc00; background: #ffcc0018; }
    #src-badge.init   { color: #888;    background: #88888818; }

    /* ── Canvas Three.js ── */
    #three-canvas canvas { display: block; }

    /* ── Tarjeta ancha ── */
    .wide  { grid-column: span 3; border-color: #ff603044; }
    .wide2 { grid-column: span 2; }
  </style>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
</head>
<body>

<div id="viewport">
  <div id="overlay">
    <div class="mission">ARTEMIS II · ORION INTEGRITY</div>
    <div class="met"  id="met">T+ 00:00:00:00</div>
    <div class="utc"  id="clock">--:--:-- UTC</div>
  </div>
  <div id="src-badge" class="init">INIT</div>
  <div id="three-canvas"></div>
</div>

<div id="hud">

  <!-- Fila 1: banner principal -->
  <div class="card wide">
    <div class="card-title">Navegación Cislunar — J2000 Geocéntrico</div>
    <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:4px">
      <div>
        <div class="row"><span class="lbl">DIST TIERRA</span><span class="val orange" id="d-earth">0 km</span></div>
        <div class="row"><span class="lbl">DIST LUNA</span>  <span class="val"        id="d-moon">0 km</span></div>
      </div>
      <div>
        <div class="row"><span class="lbl">VELOCIDAD</span>  <span class="val orange" id="v-speed">0.000 km/s</span></div>
        <div class="row"><span class="lbl">LUZ → TIERRA</span><span class="val"       id="v-light">0.0000 s</span></div>
      </div>
      <div>
        <div class="row"><span class="lbl">LAT SELÉNICA</span><span class="val yellow" id="v-lat">0.00°</span></div>
        <div class="row"><span class="lbl">LON SELÉNICA</span><span class="val yellow" id="v-lon">0.00°</span></div>
      </div>
    </div>
  </div>

  <!-- Fila 2 -->
  <div class="card wide2">
    <div class="card-title">Vector Posición J2000 (km)</div>
    <div class="row"><span class="lbl">X</span><span class="val" id="v-x">0</span></div>
    <div class="row"><span class="lbl">Y</span><span class="val" id="v-y">0</span></div>
    <div class="row"><span class="lbl">Z</span><span class="val" id="v-z">0</span></div>
  </div>

  <div class="card">
    <div class="card-title">Vector Velocidad (km/s)</div>
    <div class="row"><span class="lbl">Vx</span><span class="val" id="v-vx">0.000</span></div>
    <div class="row"><span class="lbl">Vy</span><span class="val" id="v-vy">0.000</span></div>
    <div class="row"><span class="lbl">Vz</span><span class="val" id="v-vz">0.000</span></div>
  </div>

  <!-- Fila 3: posición Luna -->
  <div class="card wide2">
    <div class="card-title">Luna — Posición J2000 (km)</div>
    <div class="row"><span class="lbl">X</span><span class="val" id="m-x">0</span></div>
    <div class="row"><span class="lbl">Y</span><span class="val" id="m-y">0</span></div>
    <div class="row"><span class="lbl">Z</span><span class="val" id="m-z">0</span></div>
  </div>

  <div class="card">
    <div class="card-title">Sistema</div>
    <div class="row"><span class="lbl">CONN</span>  <span class="val green" id="conn-st">WS OK</span></div>
    <div class="row"><span class="lbl">PAQUETES</span><span class="val" id="pkt-cnt">0</span></div>
    <div class="row"><span class="lbl">FPS</span>   <span class="val" id="fps-val">0</span></div>
  </div>

</div>

<script>
/* ─────────────────────────────────────────────────────────────────────
   Constantes
───────────────────────────────────────────────────────────────────── */
const SCALE       = 800;   // km → unidades Three.js  (400 000 km → 500 u)
const TRAIL_MAX   = 1000;  // puntos en la estela de la nave
const EARTH_R_KM  = 6371;
const MOON_R_KM   = 1737;

/* ─────────────────────────────────────────────────────────────────────
   Three.js — escena
───────────────────────────────────────────────────────────────────── */
let scene, camera, renderer, controls;
let meshEarth, meshMoon, meshOrion;
let trailLine = null;
const trailPositions = [];

function geo2three(x, y, z) {
  // J2000 geocéntrico → Three.js: X=X, Y=Z, Z=-Y
  return new THREE.Vector3(x / SCALE, z / SCALE, -y / SCALE);
}

function initScene() {
  const container = document.getElementById('three-canvas');
  const w = container.clientWidth  || window.innerWidth;
  const h = container.clientHeight || window.innerHeight * 0.45;

  scene    = new THREE.Scene();
  camera   = new THREE.PerspectiveCamera(50, w / h, 0.1, 2000000);
  camera.position.set(0, 300, 700);

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(w, h);
  renderer.setPixelRatio(window.devicePixelRatio);
  container.appendChild(renderer.domElement);

  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;

  // Luces
  scene.add(new THREE.AmbientLight(0x334455, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(3000, 1000, 2000);
  scene.add(sun);

  // Tierra
  const texLoader = new THREE.TextureLoader();
  const earthGeo  = new THREE.SphereGeometry(EARTH_R_KM / SCALE, 48, 48);
  const earthMat  = new THREE.MeshPhongMaterial({
    map:      texLoader.load('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg',
                             undefined,
                             undefined,
                             () => earthMat.color.set(0x1a5090)),  // fallback color
    specularMap: texLoader.load('https://unpkg.com/three-globe/example/img/earth-water.png'),
    specular: new THREE.Color(0x333333),
    shininess: 15,
  });
  meshEarth = new THREE.Mesh(earthGeo, earthMat);
  scene.add(meshEarth);

  // Luna
  const moonGeo = new THREE.SphereGeometry(MOON_R_KM / SCALE, 32, 32);
  const moonMat = new THREE.MeshStandardMaterial({ color: 0x999999, roughness: 0.9 });
  meshMoon = new THREE.Mesh(moonGeo, moonMat);
  scene.add(meshMoon);

  // Orion (cápsula estilizada: cono + cilindro)
  const orionGroup = new THREE.Group();
  const capsulaGeo = new THREE.ConeGeometry(1.8, 4, 8);
  const capsMat    = new THREE.MeshStandardMaterial({ color: 0xddddcc, metalness: 0.5 });
  const modServGeo = new THREE.CylinderGeometry(1.8, 1.8, 3.5, 8);
  const modMat     = new THREE.MeshStandardMaterial({ color: 0x888880, metalness: 0.6 });
  const capsula    = new THREE.Mesh(capsulaGeo, capsMat);
  const modServ    = new THREE.Mesh(modServGeo, modMat);
  capsula.position.y =  3.75;
  modServ.position.y = -1.75;
  orionGroup.add(capsula, modServ);

  // Paneles solares
  const panelGeo = new THREE.BoxGeometry(12, 0.2, 2.5);
  const panelMat = new THREE.MeshStandardMaterial({ color: 0x2266aa, metalness: 0.3 });
  [-7, 7].forEach(px => {
    const p = new THREE.Mesh(panelGeo, panelMat);
    p.position.set(px, 0, 0);
    orionGroup.add(p);
  });
  meshOrion = orionGroup;
  scene.add(meshOrion);

  // Glow de la Tierra
  const glowGeo = new THREE.SphereGeometry(EARTH_R_KM / SCALE * 1.08, 48, 48);
  const glowMat = new THREE.MeshBasicMaterial({
    color: 0x0033ff, transparent: true, opacity: 0.08, side: THREE.BackSide
  });
  scene.add(new THREE.Mesh(glowGeo, glowMat));

  // Grid de fondo
  const grid = new THREE.GridHelper(3000, 30, 0x001a22, 0x000d11);
  grid.position.y = -50;
  scene.add(grid);

  // Stars
  const starGeo = new THREE.BufferGeometry();
  const starVerts = [];
  for (let i = 0; i < 8000; i++) {
    starVerts.push(
      (Math.random() - 0.5) * 4000,
      (Math.random() - 0.5) * 4000,
      (Math.random() - 0.5) * 4000
    );
  }
  starGeo.setAttribute('position', new THREE.Float32BufferAttribute(starVerts, 3));
  scene.add(new THREE.Points(starGeo, new THREE.PointsMaterial({ color: 0xffffff, size: 0.5 })));

  window.addEventListener('resize', onResize);
}

function onResize() {
  const container = document.getElementById('three-canvas');
  const w = container.clientWidth;
  const h = container.clientHeight;
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  renderer.setSize(w, h);
}

function updateTrail(pos3) {
  trailPositions.push(pos3.clone());
  if (trailPositions.length > TRAIL_MAX) trailPositions.shift();

  if (trailLine) { scene.remove(trailLine); trailLine.geometry.dispose(); }
  if (trailPositions.length < 2) return;

  const geo = new THREE.BufferGeometry().setFromPoints(trailPositions);
  trailLine = new THREE.Line(
    geo,
    new THREE.LineBasicMaterial({ color: 0xff4800, transparent: true, opacity: 0.6 })
  );
  scene.add(trailLine);
}

function animate() {
  requestAnimationFrame(animate);
  meshEarth.rotation.y += 0.0003;
  controls.update();
  renderer.render(scene, camera);
}

/* ─────────────────────────────────────────────────────────────────────
   HUD helpers
───────────────────────────────────────────────────────────────────── */
const $ = id => document.getElementById(id);

function fmt(n, dec=0) {
  return isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: dec }) : '—';
}

function setVal(id, text, cls) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  if (cls) { el.className = 'val ' + cls; }
}

/* ─────────────────────────────────────────────────────────────────────
   WebSocket
───────────────────────────────────────────────────────────────────── */
let pktCount = 0, fpsTimer = 0, fpsCount = 0;

function updateHUD(d) {
  const s = d.ship, m = d.moon;

  // MET / Reloj
  $('met').textContent   = d.met;
  $('clock').textContent = d.time;

  // Badge de fuente
  const badge = $('src-badge');
  if (d.source.includes('HORIZONS')) {
    badge.textContent = '● JPL HORIZONS';
    badge.className   = 'live';
  } else if (d.source.includes('CACHE')) {
    badge.textContent = '◌ CACHE';
    badge.className   = 'cached';
  } else {
    badge.textContent = d.source;
    badge.className   = 'init';
  }

  // Navegación
  setVal('d-earth', fmt(s.dist_e) + ' km',    'orange');
  setVal('d-moon',  fmt(s.dist_m) + ' km',    '');
  setVal('v-speed', s.v.toFixed(3) + ' km/s', 'orange');
  setVal('v-light', s.light_e.toFixed(4) + ' s', '');
  setVal('v-lat',   s.lat_m.toFixed(2) + '°', 'yellow');
  setVal('v-lon',   s.lon_m.toFixed(2) + '°', 'yellow');

  // Vectores
  setVal('v-x', fmt(s.x));
  setVal('v-y', fmt(s.y));
  setVal('v-z', fmt(s.z));
  setVal('v-vx', s.vx.toFixed(3));
  setVal('v-vy', s.vy.toFixed(3));
  setVal('v-vz', s.vz.toFixed(3));

  // Luna
  setVal('m-x', fmt(m.x));
  setVal('m-y', fmt(m.y));
  setVal('m-z', fmt(m.z));

  // Sistema
  setVal('pkt-cnt', ++pktCount);

  // FPS
  fpsCount++;
  const now = performance.now();
  if (now - fpsTimer > 1000) {
    setVal('fps-val', fpsCount);
    fpsCount = 0;
    fpsTimer = now;
  }

  // Three.js
  const orionPos = geo2three(s.x, s.y, s.z);
  meshOrion.position.copy(orionPos);
  meshMoon.position.copy(geo2three(m.x, m.y, m.z));

  // Apuntar la nave hacia la Luna
  meshOrion.lookAt(meshMoon.position);

  updateTrail(orionPos);

  // Cámara sigue la nave suavemente
  controls.target.lerp(orionPos, 0.05);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(proto + '//' + location.host + '/ws/telemetry');

  ws.onopen = () => {
    $('conn-st').textContent = 'WS OK';
    $('conn-st').className   = 'val green';
  };
  ws.onmessage = e => {
    try { updateHUD(JSON.parse(e.data)); } catch (_) {}
  };
  ws.onclose = () => {
    $('conn-st').textContent = 'RECONECTANDO';
    $('conn-st').className   = 'val red';
    setTimeout(connect, 2000);
  };
  ws.onerror = () => ws.close();
}

/* ─────────────────────────────────────────────────────────────────────
   Init
───────────────────────────────────────────────────────────────────── */
initScene();
animate();
connect();
</script>
</body>
</html>
"""
