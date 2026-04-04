#!/bin/bash

# 1. Iniciar tu servidor FastAPI (Motor de Datos) en segundo plano
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} &
SERVER_PID=$!

echo "Iniciando motor de telemetría..."
sleep 5 # Le damos 5 segundos para conectar a la NASA

# 2. Encender el monitor virtual (720p)
export DISPLAY=:99
Xvfb :99 -screen 0 1280x720x24 -nolisten tcp &
sleep 2

# 3. Lanzar Chromium forzando renderizado por procesador (SwiftShader)
# Apuntamos a localhost porque todo corre dentro de la misma máquina
chromium --no-sandbox \
         --disable-dev-shm-usage \
         --disable-gpu \
         --use-gl=swiftshader \
         --window-size=1280,720 \
         --kiosk \
         "http://localhost:${PORT:-8000}" &
         
echo "Renderizando holograma 3D..."
sleep 10 # Tiempo para que cargue la gráfica espacial

# 4. El Cañón de Transmisión a YouTube
# Toma la clave desde las variables de entorno de Railway
KEY="${YOUTUBE_STREAM_KEY}"

echo "Iniciando uplink a YouTube Live..."

ffmpeg -f x11grab -s 1280x720 -framerate 30 -i :99 \
       -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \
       -c:v libx264 -preset ultrafast -b:v 2500k -maxrate 3000k -bufsize 6000k -pix_fmt yuv420p -g 60 \
       -c:a aac -b:a 128k -ar 44100 \
       -f flv "rtmp://a.rtmp.youtube.com/live2/$KEY"
