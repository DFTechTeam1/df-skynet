#!/bin/sh
# pre-push gate: the full test suite is slow, so it is SKIPPED by default.
# Opt in for a single push with:  RUN_TESTS=1 git push
[ "$RUN_TESTS" = "1" ] || { echo "all-tests skipped — 'RUN_TESTS=1 git push' to run"; exit 0; }
exec sh "$(dirname "$0")/run_test.sh" --env dev --test all
