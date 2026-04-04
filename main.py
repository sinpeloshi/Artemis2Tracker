import os
from flask import Flask, render_template_string
from datetime import datetime, timezone

app = Flask(__name__)

# Acá metemos el HTML y CSS con los gráficos mejorados (efectos 3D y sombras)
# Usamos variables de Jinja {{ data.variable }} para conectar el backend con la vista
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mission Control - Artemis II</title>
<style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { 
        background-color: #020408; 
        color: white; 
        font-family: 'Courier New', Courier, monospace; 
        display: flex; 
        flex-direction: column; 
        height: 100vh; 
        overflow: hidden; 
    }

    /* Grilla de fondo espacial */
    .space-container { 
        flex-grow: 1; 
        position: relative; 
        background-image: 
            linear-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(255, 255, 255, 0.03) 1px, transparent 1px);
        background-size: 50px 50px;
    }

    /* Tierra mejorada con gradientes y atmósfera */
    .earth { 
        position: absolute; 
        top: 25%; 
        left: 30%; 
        width: 120px; 
        height: 120px; 
        border-radius: 50%;
        background: radial-gradient(circle at 30% 30%, #2b78e4, #0b224d, #020a1c);
        box-shadow: 
            0 0 40px rgba(43, 120, 228, 0.4),
            inset -20px -20px 40px rgba(0,0,0,0.9);
    }
    .label-earth { 
        position: absolute; 
        top: -25px; 
        left: 50%; 
        transform: translateX(-50%); 
        color: #00e5ff; 
        font-weight: bold; 
        font-size: 14px; 
        text-shadow: 0 0 8px #00e5ff; 
    }

    /* Luna con textura simulada */
    .moon { 
        position: absolute; 
        bottom: 15%; 
        right: 20%; 
        width: 70px; 
        height: 70px; 
        border-radius: 50%;
        background: radial-gradient(circle at 30% 30%, #e0e0e0, #7a7a7a, #1a1a1a);
        box-shadow: inset -15px -15px 25px rgba(0,0,0,0.9);
    }
    .label-moon { 
        position: absolute; 
        top: -25px; 
        left: 50%; 
        transform: translateX(-50%); 
        color: #aaaaaa; 
        font-weight: bold; 
        font-size: 12px; 
        white-space: nowrap;
    }

    /* Marcador de nave */
    .orion { 
        position: absolute; 
        top: 55%; 
        right: 45%; 
        width: 4px; 
        height: 18px; 
        background-color: #ff5500; 
        border-radius: 2px; 
        box-shadow: 0 0 12px #ff5500, 0 0 25px #ff5500; 
    }
    .label-orion { 
        position: absolute; 
        left: 12px; 
        top: 2px; 
        color: #ff5500; 
        font-weight: bold; 
        font-size: 12px; 
        white-space: nowrap; 
        text-shadow: 0 0 5px #ff5500; 
    }

    /* Tiempo UTC superior izquierdo */
    .utc-time {
        position: absolute;
        top: 10px;
        left: 10px;
        color: #00e5ff;
        font-size: 14px;
        font-weight: bold;
        text-shadow: 0 0 5px #00e5ff;
    }

    /* Panel inferior de telemetría */
    .telemetry-panel { 
        background-color: #050a12; 
        border-top: 2px solid #005577; 
        padding: 15px 20px; 
        font-size: 13px; 
        color: #7090b0; 
        height: 220px;
        overflow-y: auto;
    }
    .panel-section {
        margin-bottom: 15px;
        border-left: 3px solid #005577;
        padding-left: 10px;
    }
    .orange-border { border-left-color: #ff5500; }
    .cyan-border { border-left-color: #00e5ff; }
    
    .section-title { font-weight: bold; margin-bottom: 8px; }
    .title-orange { color: #ff5500; }
    .title-cyan { color: #00e5ff; }

    .data-row { display: flex; justify-content: space-between; margin-bottom: 4px; }
    .value-highlight { font-weight: bold; color: white; }
    .value-orange { color: #ff5500; font-weight: bold; }
</style>
</head>
<body>

    <div class="space-container">
        <div class="utc-time">MISSION CONTROL LIVE<br>{{ data.utc_time }}</div>
        
        <div class="earth"><div class="label-earth">EARTH</div></div>
        <div class="orion"><div class="label-orion">ORION II</div></div>
        <div class="moon"><div class="label-moon">LUNAR TARGET</div></div>
    </div>

    <div class="telemetry-panel">
        <div class="panel-section orange-border">
            <div class="section-title title-orange">ORION SPACECRAFT (ARTEMIS II)</div>
            <div class="data-row"><span>VELOCIDAD INERCIAL</span> <span class="value-orange">{{ data.vel_inercial }}</span></div>
            <div class="data-row"><span>VELOCIDAD (MACH)</span> <span class="value-highlight">{{ data.vel_mach }}</span></div>
            <div class="data-row"><span>ALTITUD (TIERRA)</span> <span class="value-highlight">{{ data.altitud_tierra }}</span></div>
            <div class="data-row"><span>DISTANCIA (LUNA)</span> <span class="value-highlight">{{ data.distancia_luna }}</span></div>
        </div>

        <div class="panel-section cyan-border">
            <div class="section-title title-cyan">DEEP SPACE DYNAMICS</div>
            <div class="data-row"><span>LATENCIA LUZ (IDA)</span> <span class="value-highlight">{{ data.latencia_luz }}</span></div>
            <div class="data-row"><span>COORD. ECUATORIALES (RA/Dec)</span> <span class="value-highlight">{{ data.coord_ra_dec }}</span></div>
        </div>
    </div>

</body>
</html>
"""

@app.route('/')
def dashboard():
    # Acá generás o extraés tu telemetría real. 
    # Te dejé este diccionario como base para que pases los datos al HTML.
    telemetry_data = {
        "utc_time": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3] + " UTC",
        "vel_inercial": "1.58080 km/s",
        "vel_mach": "4.37 M",
        "altitud_tierra": "200,984 km",
        "distancia_luna": "201,882 km",
        "latencia_luz": "0.6784 s",
        "coord_ra_dec": "223.56° RA / -21.69° DEC"
    }
    
    # Renderizamos la plantilla HTML inyectando el diccionario 'telemetry_data'
    return render_template_string(HTML_TEMPLATE, data=telemetry_data)

if __name__ == '__main__':
    # Esta línea asegura que tome el puerto dinámico de Railway, si no usa el 8080 por defecto
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
