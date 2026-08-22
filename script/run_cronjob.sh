#!/bin/sh

show_help() {
    echo "Usage: sh scripts/run_cronjob.sh [ --env <environment> ] | [ --help ] | [ --path <filepath> ]"
    echo ""
    echo "--env       Set environment: dev | stg | prod"
    echo "--path      Specify the cronjob script to run (e.g., cronjob/pic_assignment_queue.py)"
    echo "--help, -h  Show this help message."
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_DIR/.venv"

ENV=""
ENV_FILE=""
FILEPATH=""

while [ $# -gt 0 ]; do
    case "$1" in
    --env)
        shift
        ENV="$1"
        case "$ENV" in
        dev)
            ENV_FILE="$PROJECT_DIR/env/.env.development"
            ;;
        stg)
            ENV_FILE="$PROJECT_DIR/env/.env.staging"
            ;;
        prod)
            ENV_FILE="$PROJECT_DIR/env/.env.production"
            ;;
        *)
            echo "Error: Invalid environment '$ENV'"
            show_help
            ;;
        esac
        ;;

    --path)
        shift
        FILEPATH="$1"
        ;;

    --help | -h)
        show_help
        ;;

    *)
        echo "Error: Unknown argument '$1'"
        show_help
        ;;
    esac
    shift
done

if [ -z "$ENV_FILE" ]; then
    echo "Error: --env is required"
    show_help
fi

if [ -z "$FILEPATH" ]; then
    echo "Error: --path is required"
    show_help
fi

case "$FILEPATH" in
    /*) ;;
    *) FILEPATH="$PROJECT_DIR/$FILEPATH" ;;
esac

if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found: $ENV_FILE"
    exit 1
fi

if [ ! -f "$FILEPATH" ]; then
    echo "Filepath not found: $FILEPATH"
    exit 1
fi

FILENAME=$(basename "$FILEPATH")
FILENAME="${FILENAME%.*}"

LOG_DIR="$PROJECT_DIR/log"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/${FILENAME}-${ENV}.log"

if [ -d "$VENV_DIR" ]; then
    . "$VENV_DIR/bin/activate"
    echo "Virtual environment activated from $VENV_DIR"
else
    echo "Virtual environment not found at $VENV_DIR"
    exit 1
fi

export ENV_TYPE="$ENV"
export ENV_FILE="$ENV_FILE"
export $(grep -v '^#' "$ENV_FILE" | xargs)
export PATH="$HOME/.local/bin:$PATH"

echo "----------------------------------------"
echo "Environment : $ENV"
echo "Env file    : $ENV_FILE"
echo "Script      : $FILEPATH"
echo "Log file    : $LOG_FILE"
echo "----------------------------------------"

uv run "$FILEPATH" >> "$LOG_FILE" 2>&1
