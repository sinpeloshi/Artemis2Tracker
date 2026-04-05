"""
main.py — Artemis II FIDO Console
FastAPI + WebSocket + Three.js
Datos reales: JPL Horizons API vía worker.py
"""
from __future__ import annotations   # ← lazy annotations: compatible Python 3.7+

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

    /* ── Etiquetas 3D ── */
    .lbl3d {
      position: absolute; pointer-events: none;
      font-size: 10px; letter-spacing: .1em; color: #ffffff88;
      transform: translateX(-50%); white-space: nowrap;
      text-shadow: 0 0 6px #000;
    }

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
  <div id="lbl-earth" class="lbl3d">TIERRA</div>
  <div id="lbl-moon"  class="lbl3d">LUNA</div>
  <div id="lbl-orion" class="lbl3d" style="color:#ff6030cc">ORION</div>
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
/* ═══════════════════════════════════════════════════════════════════
   DISPLAY DESIGN
   Las posiciones J2000 reales se usan SOLO para el HUD (km exactos).
   Para la escena 3D usamos posiciones normalizadas:
     • Tierra  → siempre en el origen (0,0,0)
     • Luna    → siempre a DISPLAY_DIST unidades, dirección real J2000
     • Orion   → interpolado proporcional a dist_e / (dist_e + dist_m)
   Así los tres cuerpos son siempre visibles sin importar la distancia.
═══════════════════════════════════════════════════════════════════ */
const DISPLAY_DIST = 440;   // distancia visual Tierra-Luna (unidades)
const EARTH_R      = 40;    // radio visual Tierra
const MOON_R       = 20;    // radio visual Luna
const S            = 6;     // escala Orion
const TRAIL_MAX    = 900;

let scene, camera, renderer, controls;
let meshEarth, meshMoon, meshOrion, meshClouds;
let trailLine = null, pathLine = null;
const trail = [];

/* ── J2000 dirección → Vector3 Three.js ─────────────────────────── */
function j2dir(x, y, z) {
  const len = Math.sqrt(x*x + y*y + z*z) || 1;
  return new THREE.Vector3(x/len, z/len, -y/len);   // J2000→Three.js: Y↔Z, invertir Y
}

/* ── Inicializar escena ──────────────────────────────────────────── */
function initScene() {
  const el = document.getElementById('three-canvas');
  const w = el.clientWidth  || window.innerWidth;
  const h = el.clientHeight || window.innerHeight * 0.45;

  scene  = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(52, w/h, 0.5, 5000000);
  camera.position.set(120, 90, 420);   // vista inicial: ve Tierra y puede ver Luna

  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(w, h);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  el.appendChild(renderer.domElement);

  controls = new THREE.OrbitControls(camera, renderer.domElement);
  controls.enableDamping  = true;
  controls.dampingFactor  = 0.07;
  controls.minDistance    = 15;
  controls.maxDistance    = 1800;

  /* ── Iluminación ── */
  scene.add(new THREE.AmbientLight(0x223344, 1.6));
  const sun = new THREE.DirectionalLight(0xfff5ee, 2.2);
  sun.position.set(4000, 1500, 2000);
  scene.add(sun);

  /* ── Texturas lazy (no bloquean el render) ── */
  const tl = new THREE.TextureLoader();
  const lt = (url, cb) => tl.load(url, cb, undefined, () => {});

  /* ── Tierra ── */
  const earthMat = new THREE.MeshPhongMaterial({
    color: 0x1a5090, specular: 0x333333, shininess: 20 });
  lt('https://unpkg.com/three-globe/example/img/earth-blue-marble.jpg',
     t => { earthMat.map = t; earthMat.color.set(0xffffff); earthMat.needsUpdate = true; });
  lt('https://unpkg.com/three-globe/example/img/earth-water.png',
     t => { earthMat.specularMap = t; earthMat.needsUpdate = true; });
  meshEarth = new THREE.Mesh(new THREE.SphereGeometry(EARTH_R, 64, 64), earthMat);
  scene.add(meshEarth);

  /* ── Nubes ── */
  const cloudMat = new THREE.MeshPhongMaterial({ transparent: true, opacity: 0, depthWrite: false });
  lt('https://unpkg.com/three-globe/example/img/earth-clouds.png',
     t => { cloudMat.map = t; cloudMat.opacity = 0.32; cloudMat.needsUpdate = true; });
  meshClouds = new THREE.Mesh(new THREE.SphereGeometry(EARTH_R * 1.014, 64, 64), cloudMat);
  scene.add(meshClouds);

  /* ── Atmósfera ── */
  scene.add(new THREE.Mesh(
    new THREE.SphereGeometry(EARTH_R * 1.1, 48, 48),
    new THREE.MeshBasicMaterial({ color: 0x0044cc, transparent: true, opacity: 0.055, side: THREE.BackSide })
  ));

  /* ── Luna ── */
  const moonMat = new THREE.MeshStandardMaterial({ color: 0x888888, roughness: 0.95 });
  lt('https://unpkg.com/three-globe/example/img/moon_1k.jpg',
     t => { moonMat.map = t; moonMat.color.set(0xffffff); moonMat.needsUpdate = true; });
  meshMoon = new THREE.Mesh(new THREE.SphereGeometry(MOON_R, 48, 48), moonMat);
  meshMoon.position.set(DISPLAY_DIST, 0, 0);   // posición inicial hasta que llegue telemetría
  scene.add(meshMoon);

  /* ── Orion ── */
  const grp = new THREE.Group();
  const capMat = new THREE.MeshStandardMaterial({ color: 0xddddcc, metalness: 0.5, roughness: 0.4 });
  const smMat  = new THREE.MeshStandardMaterial({ color: 0x888880, metalness: 0.6, roughness: 0.5 });
  const panMat = new THREE.MeshStandardMaterial({ color: 0x1a5faa, metalness: 0.3, roughness: 0.5 });
  const cap = new THREE.Mesh(new THREE.ConeGeometry(1.8*S, 4.5*S, 8), capMat);
  const sm  = new THREE.Mesh(new THREE.CylinderGeometry(1.8*S, 1.8*S, 4*S, 8), smMat);
  cap.position.y =  4.5*S;
  sm.position.y  = -2.0*S;
  grp.add(cap, sm);
  [-7.5*S, 7.5*S].forEach(px => {
    const p = new THREE.Mesh(new THREE.BoxGeometry(13*S, 0.3*S, 3*S), panMat);
    p.position.set(px, 0, 0);
    grp.add(p);
  });
  meshOrion = grp;
  meshOrion.position.set(DISPLAY_DIST * 0.6, 0, 0);  // posición inicial
  scene.add(meshOrion);

  /* ── Línea de trayectoria Tierra→Luna (se actualiza con datos) ── */
  const pathGeo = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(0,0,0), new THREE.Vector3(DISPLAY_DIST, 0, 0)
  ]);
  pathLine = new THREE.Line(pathGeo,
    new THREE.LineBasicMaterial({ color: 0x00f2ff, transparent: true, opacity: 0.12 }));
  scene.add(pathLine);

  /* ── Estrellas ── */
  const sv = [];
  for (let i = 0; i < 12000; i++)
    sv.push((Math.random()-.5)*7000, (Math.random()-.5)*7000, (Math.random()-.5)*7000);
  const sg = new THREE.BufferGeometry();
  sg.setAttribute('position', new THREE.Float32BufferAttribute(sv, 3));
  scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0xffffff, size: 0.55 })));

  window.addEventListener('resize', onResize);
}

function onResize() {
  const el = document.getElementById('three-canvas');
  camera.aspect = el.clientWidth / el.clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(el.clientWidth, el.clientHeight);
}

/* ── Proyectar etiqueta HTML sobre posición 3D ─────────────────── */
function projectLabel(id, worldPos) {
  const el = document.getElementById(id);
  if (!el) return;
  const v  = worldPos.clone().project(camera);
  const cw = renderer.domElement.clientWidth;
  const ch = renderer.domElement.clientHeight;
  if (v.z > 1) { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.style.left = ((v.x * .5 + .5) * cw) + 'px';
  el.style.top  = ((-v.y * .5 + .5) * ch - 28) + 'px';
}

/* ── Trail ── */
function updateTrail(pos) {
  trail.push(pos.clone());
  if (trail.length > TRAIL_MAX) trail.shift();
  if (trailLine) { scene.remove(trailLine); trailLine.geometry.dispose(); }
  if (trail.length < 2) return;
  const geo = new THREE.BufferGeometry().setFromPoints(trail);
  trailLine = new THREE.Line(geo,
    new THREE.LineBasicMaterial({ color: 0xff5010, transparent: true, opacity: 0.55 }));
  scene.add(trailLine);
}

/* ── Render loop ── */
function animate() {
  requestAnimationFrame(animate);
  meshEarth.rotation.y += 0.00028;
  if (meshClouds) meshClouds.rotation.y += 0.00033;
  controls.update();
  renderer.render(scene, camera);
  // Etiquetas HTML
  projectLabel('lbl-earth', new THREE.Vector3(0, EARTH_R * 1.5, 0));
  projectLabel('lbl-moon',  meshMoon.position.clone().add(new THREE.Vector3(0, MOON_R * 1.6, 0)));
  projectLabel('lbl-orion', meshOrion.position.clone().add(new THREE.Vector3(0, S * 9, 0)));
}

/* ═══════════════════════════════════════════════════════════════════
   HUD
═══════════════════════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);
const fmt = (n, d=0) => isFinite(n) ? n.toLocaleString('en-US', { maximumFractionDigits: d }) : '—';
const sv  = (id, txt, cls) => { const e=$(id); if(!e) return; e.textContent=txt; if(cls) e.className='val '+cls; };

let pktCount=0, fpsTimer=0, fpsCount=0;

function updateHUD(d) {
  const s = d.ship, m = d.moon;

  $('met').textContent   = d.met;
  $('clock').textContent = d.time;

  const badge = $('src-badge');
  if      (d.source.includes('HORIZONS')) { badge.textContent='● JPL HORIZONS'; badge.className='live'; }
  else if (d.source.includes('CACHE'))    { badge.textContent='◌ CACHE';         badge.className='cached'; }
  else                                    { badge.textContent=d.source;           badge.className='init'; }

  sv('d-earth', fmt(s.dist_e)+' km',       'orange');
  sv('d-moon',  fmt(s.dist_m)+' km',       '');
  sv('v-speed', s.v.toFixed(3)+' km/s',    'orange');
  sv('v-light', s.light_e.toFixed(4)+' s', '');
  sv('v-lat',   s.lat_m.toFixed(2)+'°',    'yellow');
  sv('v-lon',   s.lon_m.toFixed(2)+'°',    'yellow');
  sv('v-x',  fmt(s.x));  sv('v-y',  fmt(s.y));  sv('v-z',  fmt(s.z));
  sv('v-vx', s.vx.toFixed(3)); sv('v-vy', s.vy.toFixed(3)); sv('v-vz', s.vz.toFixed(3));
  sv('m-x',  fmt(m.x));  sv('m-y',  fmt(m.y));  sv('m-z',  fmt(m.z));
  sv('pkt-cnt', ++pktCount);
  fpsCount++;
  const now = performance.now();
  if (now - fpsTimer > 1000) { sv('fps-val', fpsCount); fpsCount=0; fpsTimer=now; }

  /* ── Posiciones de display normalizadas ── */
  const moonR = Math.sqrt(m.x**2 + m.y**2 + m.z**2);
  if (!moonR || !s.dist_e || !s.dist_m) return;

  // Dirección real J2000 → Three.js, distancia siempre DISPLAY_DIST
  const moonDP = j2dir(m.x, m.y, m.z).multiplyScalar(DISPLAY_DIST);
  meshMoon.position.copy(moonDP);

  // Orion: proporción real de cuánto del trayecto recorrió
  const prog    = Math.max(0.04, Math.min(0.96, s.dist_e / (s.dist_e + s.dist_m)));
  const orionDP = moonDP.clone().multiplyScalar(prog);
  meshOrion.position.copy(orionDP);
  meshOrion.lookAt(moonDP);   // nariz apuntando a la Luna

  updateTrail(orionDP);

  // Actualizar línea de trayectoria Tierra→Luna
  if (pathLine) {
    pathLine.geometry.setFromPoints([new THREE.Vector3(0,0,0), moonDP]);
    pathLine.geometry.attributes.position.needsUpdate = true;
  }

  // Cámara: target en el punto medio del sistema
  controls.target.lerp(moonDP.clone().multiplyScalar(0.5), 0.012);
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws    = new WebSocket(proto + '//' + location.host + '/ws/telemetry');
  ws.onopen    = () => { sv('conn-st','WS OK','green'); };
  ws.onmessage = e => { try { updateHUD(JSON.parse(e.data)); } catch(_) {} };
  ws.onclose   = () => { sv('conn-st','RECONECTANDO','red'); setTimeout(connect, 2000); };
  ws.onerror   = () => ws.close();
}

initScene();
animate();
connect();
</script>
</body>
</html>
"""
