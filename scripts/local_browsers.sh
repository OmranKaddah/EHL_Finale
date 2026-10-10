#!/bin/bash
set -e

CHROME_PIDS=""
cleanup() {
    echo "Cleaning up Chrome processes..."
    for pid in $CHROME_PIDS; do
        kill "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Number of browsers to spawn (defaults to 4 as requested by the manifest)
NUM_BROWSERS=${1:-4}

echo "Starting $NUM_BROWSERS local Chrome instances..."

CDP_URLS="["
for i in $(seq 1 $NUM_BROWSERS); do
    PORT=$((9221 + i))
    USER_DATA_DIR="/tmp/ehl-rfq-chrome-$i"
    mkdir -p "$USER_DATA_DIR"
    
    # Start Chrome in the background. We omit --headless to display the windows.
    google-chrome \
        --remote-debugging-port=$PORT \
        --user-data-dir="$USER_DATA_DIR" \
        --window-size=1280,1024 \
        --no-first-run \
        --no-default-browser-check \
        --disable-infobars \
        > /dev/null 2>&1 &
    
    # Store the process ID to clean up later
    CHROME_PIDS="$CHROME_PIDS $!"
    
    if [ $i -gt 1 ]; then
        CDP_URLS="$CDP_URLS, "
    fi
    CDP_URLS="$CDP_URLS\"http://127.0.0.1:$PORT\""
done
CDP_URLS="$CDP_URLS]"

export CDP_URLS
echo "Exported CDP_URLS: $CDP_URLS"

# Wait a few seconds to let Chrome instances fully initialize their debugging ports
sleep 2

echo "Fetching Atira scouting environment..."
export ATIRA_API=${ATIRA_API:-https://ehl-challenge.atira.ai}
scout_exports="$(atira scout --challenge rfq --env)"
eval "$scout_exports"

echo "Starting RFQ agent..."
VENV_PYTHON=".venv/bin/python"
if [ ! -f "$VENV_PYTHON" ]; then
    echo "Virtual environment not found at .venv. Please run 'uv venv .venv' and install dependencies first."
    exit 1
fi

# Run the agent (use --prepare-only by default for local testing, can be removed to allow full submission)
if [ "$2" == "--submit" ]; then
    echo "Running in full submission mode..."
    .venv/bin/rfq-agent
else
    echo "Running in prepare-only mode (pass --submit as the second argument to allow signing and submitting)..."
    .venv/bin/rfq-agent --prepare-only
fi
