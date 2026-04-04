# Usamos una imagen ligera de Debian con Python
FROM python:3.11-slim

# Instalamos Xvfb (Pantalla virtual), Chromium (Navegador) y FFmpeg (Codificador)
RUN apt-get update && apt-get install -y \
    xvfb \
    chromium \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Preparamos el entorno de Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiamos todo tu código
COPY . .

# Damos permisos al script de arranque
RUN chmod +x start.sh

# Comando maestro
CMD ["./start.sh"]
