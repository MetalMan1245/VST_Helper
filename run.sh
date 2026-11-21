#!/usr/bin/env fish

set -l VENV_DIR ".venv"

# --- Setup (idempotent) ---
if not test -d $VENV_DIR
    echo "Creating virtual environment..."
    python3 -m venv $VENV_DIR
end

if not test -x $VENV_DIR/bin/vsthelper
    echo "Installing vst-helper and pytest..."
    $VENV_DIR/bin/pip install -q -e . pytest
end

# --- Determine command from first arg ---
set -l cmd "open"
if test (count $argv) -gt 0
    switch $argv[1]
        case "test" "-t" "--test"
            set cmd "test"
        case "health"
            set cmd "health"
        case "open"
            set cmd "open"
        case "*"
            echo "Unknown command: $argv[1]" >&2
            echo "Usage: ./run.sh [open|health|test|-t|--test] [extra args...]" >&2
            exit 1
    end
end

# --- Collect remaining args to pass through ---
set -l extra_args
if test (count $argv) -gt 1
    set extra_args $argv[2..-1]
end

# --- Dispatch ---
switch $cmd
    case "test"
        exec $VENV_DIR/bin/python -m pytest -v $extra_args
    case "health"
        exec $VENV_DIR/bin/vsthelper health $extra_args
    case "open"
        exec $VENV_DIR/bin/vsthelper open $extra_args
end
