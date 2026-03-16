#!/usr/bin/env bash
# Start Qdrant server for Agent42 local development
# Usage: bash scripts/start-qdrant.sh

QDRANT_DIR="$(dirname "$0")/../.agent42/qdrant-server"
QDRANT_BIN="$QDRANT_DIR/qdrant.exe"
QDRANT_CONFIG="$QDRANT_DIR/config.yaml"
QDRANT_PID="$QDRANT_DIR/qdrant.pid"

# Check if already running
if curl -s http://localhost:6333/collections > /dev/null 2>&1; then
    echo "Qdrant already running on port 6333"
    exit 0
fi

if [ ! -f "$QDRANT_BIN" ]; then
    echo "ERROR: Qdrant binary not found at $QDRANT_BIN"
    exit 1
fi

echo "Starting Qdrant server..."
cd "$QDRANT_DIR" && ./qdrant.exe --config-path config.yaml &
QDRANT_PID_VAL=$!
echo "$QDRANT_PID_VAL" > "$QDRANT_PID"

# Wait for startup
for i in $(seq 1 10); do
    if curl -s http://localhost:6333/collections > /dev/null 2>&1; then
        echo "Qdrant started (PID: $QDRANT_PID_VAL, port: 6333)"
        exit 0
    fi
    sleep 1
done

echo "ERROR: Qdrant failed to start within 10 seconds"
exit 1
