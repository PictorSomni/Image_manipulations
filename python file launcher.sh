#!/bin/bash
# macos_run_python.sh - Shell script to run a Python file

# Exit immediately if a command exits with a non-zero status
set -e

# Path to Python interpreter (use python3 on modern macOS)
PYTHON_BIN=$(which python3)

# Path to your Python file (absolute or relative)
PYTHON_FILE="script.py"

# Check if Python exists
if [ -z "$PYTHON_BIN" ]; then
    echo "Error: python3 not found. Install it with 'brew install python' or from python.org."
    exit 1
fi

# Check if the Python file exists
if [ ! -f "$PYTHON_FILE" ]; then
    echo "Error: $PYTHON_FILE not found."
    exit 1
fi

# Run the Python file
"$PYTHON_BIN" "$PYTHON_FILE"
