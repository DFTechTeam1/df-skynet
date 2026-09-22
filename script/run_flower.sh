#!/bin/sh

show_help() {
    echo "Usage: sh scripts/run_flower.sh [ --env <environment> ] | [ --help ]"
    echo ""
    echo "--env       Set environment: dev | stg | prod"
    echo "--help, -h  Show this help message."
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENV=""
ENV_FILE=""

while [ $# -gt 0 ]; do
    case "$1" in
    --env)
        shift
        ENV="$1"
        case "$ENV" in
        dev)
            ENV_FILE="$PROJECT_DIR/env/.env.development"
            PORT="10500"
            ;;
        stg)
            ENV_FILE="$PROJECT_DIR/env/.env.staging"
            PORT="11500"
            ;;
        prod)
            ENV_FILE="$PROJECT_DIR/env/.env.production"
            PORT="12500"
            ;;
        *)
            echo "Error: Invalid environment '$ENV'"
            show_help
            ;;
        esac
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

if [ ! -f "$ENV_FILE" ]; then
    echo "Environment file not found: $ENV_FILE"
    exit 1
fi

export ENV_TYPE="$ENV"
export ENV_FILE="$ENV_FILE"
export $(grep -v '^#' "$ENV_FILE" | xargs)

echo "Checking OS Environment"
if uname | grep -qiE "linux|darwin"; then
    echo "Unix-based OS detected"
    if [ ! -f "$PROJECT_DIR/.venv/bin/activate" ]; then
        echo "No virtual environment found. Please run: sh script/setup.sh"
        exit 1
    fi
    . "$PROJECT_DIR/.venv/bin/activate"
else
    echo "Unsupported OS. Please turn-on Flower manually."
    exit 1
fi

BASIC_AUTH_FLAG=""
if [ -n "$FLOWER_BASIC_AUTH" ]; then
    BASIC_AUTH_FLAG="--basic_auth=$FLOWER_BASIC_AUTH"
fi

echo "Running flower on port $PORT with environment variables from $ENV_FILE..."
celery -A services.celery_app:celery_app flower --port="$PORT" $BASIC_AUTH_FLAG
