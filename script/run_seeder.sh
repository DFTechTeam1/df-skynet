#!/bin/sh

show_help() {
    echo "Usage: sh script/run_seeder.sh --env <dev | stg | prod>"
    echo ""
    echo "Runs every seeder in seeder/ in dependency order via run_cronjob.sh."
    echo "Output of each seeder goes to log/<seeder>-<env>.log"
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SEEDER_DIR="$PROJECT_DIR/seeder"

ENV=""
while [ $# -gt 0 ]; do
    case "$1" in
    --env)
        shift
        ENV="$1"
        ;;
    --help | -h) show_help ;;
    *)
        echo "Error: Unknown argument '$1'"
        show_help
        ;;
    esac
    shift
done

case "$ENV" in
dev | stg | prod) ;;
*)
    echo "Error: --env must be dev | stg | prod"
    show_help
    ;;
esac

# admin_setting first (settings rows), model after it (fills enhancer/assistant), then the rest.
ORDER="admin_setting menu model api_key"

# Pick up any seeder not listed above, so new files run without editing this script.
EXTRA=""
for f in "$SEEDER_DIR"/*.py; do
    name="$(basename "$f" .py)"
    case " $ORDER " in
    *" $name "*) ;;
    *) EXTRA="$EXTRA $name" ;;
    esac
done

for name in $ORDER $EXTRA; do
    echo ">>> seeder/$name.py ($ENV)"
    if ! sh "$SCRIPT_DIR/run_cronjob.sh" --env "$ENV" --path "seeder/$name.py"; then
        echo "Seeder '$name' failed, see log/$name-$ENV.log"
        exit 1
    fi
done

echo "All seeders finished."
