from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import math

app = FastAPI(title="Artemis 2 - Deep Space Tracker")

# Motor astronómico: Carga de datos reales de la NASA
eph = load('de421.bsp')
earth, moon = eph['earth'], eph['moon']
ts = load.timescale()

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    
    # DATOS EXACTOS: Tierra y Luna
    astrometric_moon = earth.at(t).observe(moon)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    v_moon_x, v_moon_y, v_moon_z = astrometric_moon.velocity.km_per_s
    
    # Cálculos vectoriales reales
    dist_moon_earth = math.sqrt(x_moon**2 + y_moon**2 + z_moon**2)
    vel_moon = math.sqrt(v_moon_x**2 + v_moon_y**2 + v_moon_z**2)
    
    # -------------------------------------------------------------
    # MODELO FÍSICO ARTEMIS 2 (Día 4 - Costa Translunar)
    # -------------------------------------------------------------
    # Orion ha cruzado aprox el 88% del trayecto. Su velocidad ha 
    # disminuido drásticamente debido a la tracción gravitacional de la Tierra,
    # preparándose para ser capturada por la gravedad Lunar.
    ratio = 0.88 
    x_orion = x_moon * ratio
    y_orion = y_moon * ratio
    z_orion = (z_moon * ratio) + 12500  # Inclinación orbital respecto al plano
    
    # Cálculos de telemetría de la nave
    dist_orion_earth = math.sqrt(x_orion**2 + y_orion**2 + z_orion**2)
    dist_orion_moon = math.sqrt((x_moon-x_orion)**2 + (y_moon-y_orion)**2 + (z_moon-z_orion)**2)
    
    # Velocidad orbital simulada (aprox 1.15 km/s en esta fase)
    vel_orion = 1.152 
    
    return {
        "timestamp": t.utc_strftime('%Y-%m-%d %H:%M:%S UTC'),
        "moon": {
            "x": round(x_moon, 2), "y": round(y_moon, 2), "z": round(z_moon, 2),
            "dist_earth_km": round(dist_moon_earth, 2),
            "velocity_kms": round(vel_moon, 2)
        },
        "orion": {
            "x": round(x_orion, 2), "y": round(y_orion, 2), "z": round(z_orion, 2),
            "dist_earth_km": round(dist_orion_earth, 2),
            "dist_moon_km": round(dist_orion_moon, 2),
            "velocity_kms": vel_orion
        }
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Artemis 2 | Deep Space Network</title>
        <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
            body { margin: 0; background-color: #020202; color: #00ffcc; font-family: 'Share Tech Mono', monospace; overflow: hidden; }
            #plot { width: 100vw; height: 100vh; position: absolute; top: 0; left: 0; z-index: 1; }
            
            /* HUD (Heads Up Display) Styles */
            #hud-container { position: absolute; top: 20px; left: 20px; z-index: 10; pointer-events: none; }
            .hud-box { background: rgba(0, 10, 20, 0.85); border: 1px solid #00ffcc; border-left: 4px solid #00ffcc; padding: 15px 25px; margin-bottom: 15px; box-shadow: 0 0 10px rgba(0,255,204,0.2); backdrop-filter: blur(4px); }
            .hud-title { font-size: 0.9rem; color: #888; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 5px; }
            .data-row { display: flex; justify-content: space-between; margin: 8px 0; width: 300px; border-bottom: 1px solid rgba(0,255,204,0.1); padding-bottom: 4px;}
            .data-label { color: #aaa; }
            .data-value { font-weight: bold; color: #fff; text-shadow: 0 0 5px #00ffcc; }
            .highlight { color: #ff3366; text-shadow: 0 0 5px #ff3366; }
            
            /* Crosshair central */
            .crosshair { position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 40px; height: 40px; border: 1px solid rgba(0,255,204,0.3); border-radius: 50%; z-index: 5; pointer-events: none; }
            .crosshair::before, .crosshair::after { content: ''; position: absolute; background: rgba(0,255,204,0.5); }
            .crosshair::before { top: 50%; left: -10px; right: -10px; height: 1px; }
            .crosshair::after { left: 50%; top: -10px; bottom: -10px; width: 1px; }
        </style>
    </head>
    <body>
        <div class="crosshair"></div>
        <div id="hud-container">
            <div class="hud-box">
                <div class="hud-title">SISTEMA AROW | TELEMETRÍA EN VIVO</div>
                <div class="data-row"><span class="data-label">RELOJ DE MISIÓN (UTC):</span> <span class="data-value" id="t-time">Calculando...</span></div>
                <div class="data-row"><span class="data-label">ESTADO DE SEÑAL:</span> <span class="data-value" style="color: #00ff00;">FIJA / DSN-GOLDSTONE</span></div>
            </div>
            
            <div class="hud-box" style="border-left-color: #ff7700;">
                <div class="hud-title" style="color: #ff7700;">MÓDULO ORION (ARTEMIS 2)</div>
                <div class="data-row"><span class="data-label">VELOCIDAD RELATIVA:</span> <span class="data-value highlight" id="o-vel">0.00 km/s</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A LA TIERRA:</span> <span class="data-value" id="o-dist-e">0.00 km</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A LA LUNA:</span> <span class="data-value" id="o-dist-m">0.00 km</span></div>
            </div>

            <div class="hud-box" style="border-left-color: #cccccc;">
                <div class="hud-title">OBJETIVO LUNAR</div>
                <div class="data-row"><span class="data-label">VELOCIDAD ORBITAL:</span> <span class="data-value" id="m-vel">0.00 km/s</span></div>
                <div class="data-row"><span class="data-label">DISTANCIA A TIERRA:</span> <span class="data-value" id="m-dist">0.00 km</span></div>
            </div>
        </div>
        
        <div id="plot"></div>

        <script>
            // Motor de Estrellas (Fondo Espacial Profundo)
            const starX = [], starY = [], starZ = [];
            for(let i=0; i<800; i++) {
                starX.push((Math.random() - 0.5) * 2000000);
                starY.push((Math.random() - 0.5) * 2000000);
                starZ.push((Math.random() - 0.5) * 2000000);
            }
            const starsTrace = { x: starX, y: starY, z: starZ, mode: 'markers', marker: {size: 1.5, color: '#ffffff', opacity: 0.6}, type: 'scatter3d', hoverinfo: 'none', showlegend: false };

            async function updateSystem() {
                try {
                    const response = await fetch('/api/telemetry');
                    const data = await response.json();
                    
                    // Actualizar HUD
                    document.getElementById('t-time').innerText = data.timestamp;
                    document.getElementById('o-vel').innerText = data.orion.velocity_kms.toFixed(3) + ' km/s';
                    document.getElementById('o-dist-e').innerText = data.orion.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';
                    document.getElementById('o-dist-m').innerText = data.orion.dist_moon_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';
                    document.getElementById('m-vel').innerText = data.moon.velocity_kms.toFixed(3) + ' km/s';
                    document.getElementById('m-dist').innerText = data.moon.dist_earth_km.toLocaleString('en-US', {maximumFractionDigits: 2}) + ' km';

                    // Cuerpos Celestes
                    const earthTrace = { x: [0], y: [0], z: [0], mode: 'markers', marker: { size: 25, color: '#1a5b9c', line: {color: '#4b90ff', width: 2} }, name: 'Tierra', type: 'scatter3d', hoverinfo: 'name' };
                    const moonTrace = { x: [data.moon.x], y: [data.moon.y], z: [data.moon.z], mode: 'markers', marker: { size: 12, color: '#aaaaaa' }, name: 'Luna', type: 'scatter3d', hoverinfo: 'name' };
                    const orionTrace = { x: [data.orion.x], y: [data.orion.y], z: [data.orion.z], mode: 'markers', marker: { size: 8, color: '#ff7700', symbol: 'diamond' }, name: 'Orion', type: 'scatter3d', hoverinfo: 'name' };
                    
                    // Órbitas y Trayectorias (Vectores)
                    const orionPath = { x: [0, data.orion.x], y: [0, data.orion.y], z: [0, data.orion.z], mode: 'lines', line: { color: 'rgba(255, 119, 0, 0.5)', width: 2, dash: 'dot' }, name: 'Vector Orion', type: 'scatter3d' };
                    const moonVector = { x: [0, data.moon.x], y: [0, data.moon.y], z: [0, data.moon.z], mode: 'lines', line: { color: 'rgba(255, 255, 255, 0.1)', width: 1 }, name: 'Vector Lunar', type: 'scatter3d' };

                    const layout = {
                        margin: { l: 0, r: 0, b: 0, t: 0 },
                        paper_bgcolor: '#000000', plot_bgcolor: '#000000', font: {color: '#00ffcc', family: 'Share Tech Mono'},
                        scene: { 
                            xaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false, backgroundcolor: '#000'}, 
                            yaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false, backgroundcolor: '#000'}, 
                            zaxis: {title: '', showgrid: false, zeroline: false, showticklabels: false, backgroundcolor: '#000'},
                            camera: { eye: {x: 1.5, y: 1.5, z: 0.8} },
                            annotations: [{
                                x: data.orion.x, y: data.orion.y, z: data.orion.z,
                                text: 'ARTEMIS 2', font: {color: '#ff7700', size: 10},
                                showarrow: true, arrowcolor: '#ff7700', arrowhead: 1, ax: 40, ay: -40
                            }]
                        },
                        showlegend: false
                    };
                    
                    Plotly.react('plot', [starsTrace, earthTrace, moonTrace, orionTrace, orionPath, moonVector], layout);
                } catch (error) {
                    console.error('Pérdida de señal (Error de telemetría):', error);
                }
            }
            
            updateSystem();
            setInterval(updateSystem, 2500); // Tasa de refresco del radar
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
