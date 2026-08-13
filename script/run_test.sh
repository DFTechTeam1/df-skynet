#!/bin/sh

show_help() {
    echo "Usage: sh scripts/run_test.sh --env <environment> --test <type> | [ --help ]"
    echo ""
    echo "--env       Set environment: dev | stg | prod"
    echo "--test      Set test type: unit | api | e2e"
    echo "--help, -h  Show this help message."
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ENV=""
ENV_FILE=""
TEST_TYPE=""

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
    --test)
        shift
        TEST_TYPE="$1"
        case "$TEST_TYPE" in
        unit | api | e2e) ;;
        *)
            echo "Error: Invalid test type '$TEST_TYPE'"
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

if [ -z "$TEST_TYPE" ]; then
    echo "Error: --test is required"
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
    echo "Unsupported OS. Please run tests manually."
    exit 1
fi

echo "Running $TEST_TYPE tests with environment variables from $ENV_FILE..."
PYTHONPATH="$PROJECT_DIR" python -m pytest "$PROJECT_DIR/tests/$TEST_TYPE" -v
STATUS=$?

if [ "$STATUS" -eq 5 ]; then
    echo "No $TEST_TYPE tests found, skipping."
    exit 0
fi

exit "$STATUS"
