from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from skyfield.api import load
import uvicorn

app = FastAPI(title="Artemis 2 Live Tracker")

# Descarga de efemérides astronómicas de la NASA
eph = load('de421.bsp')
earth, moon = eph['earth'], eph['moon']
ts = load.timescale()

@app.get("/api/telemetry")
async def get_telemetry():
    t = ts.now()
    
    # Cálculo astronómico de la posición de la Luna hoy
    astrometric_moon = earth.at(t).observe(moon)
    x_moon, y_moon, z_moon = astrometric_moon.position.km
    
    # -------------------------------------------------------------
    # SIMULACIÓN DÍA 4: Trayectoria Artemis 2 (4 de abril de 2026)
    # -------------------------------------------------------------
    # Aquí calculamos un vector dinámico asumiendo el avance actual
    distancia_ratio = 0.85 # Al 85% de la distancia hacia la Luna
    
    x_orion = x_moon * distancia_ratio
    y_orion = y_moon * distancia_ratio
    z_orion = (z_moon * distancia_ratio) + 5000 # Desviación orbital natural
    
    return {
        "timestamp": t.utc_strftime('%Y-%m-%d %H:%M:%S UTC'),
        "moon": {"x": round(x_moon, 2), "y": round(y_moon, 2), "z": round(z_moon, 2)},
        "orion": {"x": round(x_orion, 2), "y": round(y_orion, 2), "z": round(z_orion, 2)}
    }

@app.get("/")
async def get_frontend():
    html_content = """
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="UTF-8">
        <title>Artemis 2 Tracker en Vivo</title>
        <script src="https://cdn.plot.ly/plotly-2.24.1.min.js"></script>
        <style>
            body { margin: 0; background-color: #050505; color: #00ff00; font-family: monospace; overflow: hidden; }
            #plot { width: 100vw; height: 100vh; }
            #info { position: absolute; top: 20px; left: 20px; z-index: 10; background: rgba(0,0,0,0.8); padding: 15px; border: 1px solid #333; border-radius: 8px; }
            h2 { margin: 0 0 10px 0; font-size: 1.2rem; color: #ffffff;}
            p { margin: 5px 0; }
        </style>
    </head>
    <body>
        <div id="info">
            <h2>Misión Artemis 2</h2>
            <p id="time-display">Estableciendo enlace de telemetría...</p>
        </div>
        <div id="plot"></div>
        <script>
            async function updatePlot() {
                try {
                    const response = await fetch('/api/telemetry');
                    const data = await response.json();
                    
                    document.getElementById('time-display').innerText = 'Reloj de Misión: ' + data.timestamp;
                    
                    // Configuración de los astros y la nave
                    const earthTrace = { x: [0], y: [0], z: [0], mode: 'markers', marker: { size: 20, color: '#4b90ff' }, name: 'Tierra', type: 'scatter3d' };
                    const moonTrace = { x: [data.moon.x], y: [data.moon.y], z: [data.moon.z], mode: 'markers', marker: { size: 10, color: '#cccccc' }, name: 'Luna', type: 'scatter3d' };
                    const orionTrace = { x: [data.orion.x], y: [data.orion.y], z: [data.orion.z], mode: 'markers', marker: { size: 6, color: '#ff7700', symbol: 'diamond' }, name: 'Orion', type: 'scatter3d' };
                    
                    // Línea punteada mostrando el origen desde la Tierra
                    const trajectoryTrace = { x: [0, data.orion.x], y: [0, data.orion.y], z: [0, data.orion.z], mode: 'lines', line: { color: '#ff7700', width: 1, dash: 'dot' }, showlegend: false, type: 'scatter3d' };

                    const layout = {
                        margin: { l: 0, r: 0, b: 0, t: 0 },
                        paper_bgcolor: '#050505', plot_bgcolor: '#050505', font: {color: '#ffffff'},
                        scene: { 
                            xaxis: {title: 'X', showgrid: false, zeroline: false, showticklabels: false}, 
                            yaxis: {title: 'Y', showgrid: false, zeroline: false, showticklabels: false}, 
                            zaxis: {title: 'Z', showgrid: false, zeroline: false, showticklabels: false},
                            camera: { eye: {x: 1.2, y: 1.2, z: 0.5} }
                        },
                        showlegend: true,
                        legend: {x: 0.8, y: 0.9}
                    };
                    
                    Plotly.react('plot', [earthTrace, moonTrace, trajectoryTrace, orionTrace], layout);
                } catch (error) {
                    console.error('Error de telemetría:', error);
                }
            }
            
            updatePlot();
            // Refresco automático de datos cada 3 segundos
            setInterval(updatePlot, 3000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)
