#!/bin/bash

echo "Iniciando Motor de Física FIDO en segundo plano (PostgreSQL Worker)..."
# El '&' al final manda este proceso a correr de fondo
python worker.py &

echo "Iniciando Gateway de Comunicaciones (FastAPI)..."
# Este comando corre al frente y sirve la web a los usuarios
uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
