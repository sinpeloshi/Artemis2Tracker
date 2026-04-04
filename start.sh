#!/bin/bash

echo "Arrancando Sistema Artemis II - Master Control..."
# Arranca el motor de física en segundo plano
python worker.py &

# Arranca el servidor web al frente
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
