#!/bin/sh

show_help() {
    echo "Usage: sh scripts/run_worker.sh --env <environment> --role <role> | [ --help ]"
    echo ""
    echo "--env       Set environment: dev | stg | prod"
    echo "--role      Set worker role: generation (image_generation,video_generation) | udin (udin_uploads)"
    echo "--help, -h  Show this help message."
    echo ""
    echo "Run this script twice (once per --role) to get both worker processes."
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENV=""
ENV_FILE=""
ROLE=""
QUEUES=""

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
    --role)
        shift
        ROLE="$1"
        case "$ROLE" in
        generation)
            QUEUES="image_generation,video_generation"
            ;;
        udin)
            QUEUES="udin_uploads"
            ;;
        *)
            echo "Error: Invalid role '$ROLE'"
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

if [ -z "$ROLE" ]; then
    echo "Error: --role is required"
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
    echo "Unsupported OS. Please turn-on the worker manually."
    exit 1
fi

echo "Running celery worker (role=$ROLE, queues=$QUEUES) with environment variables from $ENV_FILE..."
celery -A services.celery_app:celery_app worker --loglevel=info -Q "$QUEUES" --autoscale=10,1 -n "engine-worker-$ROLE-$ENV@%h"
