#!/bin/bash
set -euo pipefail

if [[ $# -ne 2 || "${1:-}" == --help ]]; then
  cat <<'HELP'
Usage: bash baseline_inventory.sh {prepare|submit|resume|worker|collect} RUN_DIRECTORY

Supplement an existing baseline.py run without changing its automata or bounds.
Requires the run's analysis.json and its pinned GAP/SgpDec installation.
Default: 100 automata/task, at most 50 parallel tasks, 300 seconds/GAP inventory.
Optional: BATCH_SIZE, MAX_PARALLEL, INVENTORY_TIMEOUT_SECONDS, SLURM_ACCOUNT,
          SLURM_MEMORY, SLURM_TIME, AUTOMATA_ENV, PYTHON_MODULE, PYTHON.
HELP
  exit 0
fi
MODE="$1"
SOURCE_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if command -v module >/dev/null 2>&1; then
  module load "${PYTHON_MODULE:-python/3.10}"
fi
if [[ -f "${AUTOMATA_ENV:-$HOME/automata-env}/bin/activate" ]]; then
  source "${AUTOMATA_ENV:-$HOME/automata-env}/bin/activate"
fi
PYTHON="${PYTHON:-python3}"
export PYTHONDONTWRITEBYTECODE=1
export MPLBACKEND=Agg
export MPLCONFIGDIR="${SLURM_TMPDIR:-${TMPDIR:-/tmp}}/mealy-matplotlib-${USER:-user}"
RUN_DIR=$("$PYTHON" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$2")
TIMEOUT_ARGS=()
if [[ -n "${INVENTORY_TIMEOUT_SECONDS:-}" ]]; then
  TIMEOUT_ARGS=(--timeout "$INVENTORY_TIMEOUT_SECONDS")
fi

case "$MODE" in
  prepare)
    exec "$PYTHON" "$SOURCE_DIR/baseline_inventory.py" prepare --run-dir "$RUN_DIR" "${TIMEOUT_ARGS[@]}"
    ;;
  worker)
    exec "$PYTHON" "$RUN_DIR/inventory/source/baseline_inventory.py" analyze --run-dir "$RUN_DIR" \
      --task-id "${SLURM_ARRAY_TASK_ID:?Missing Slurm array task ID}" --batch-size "${BATCH_SIZE:-100}"
    ;;
  collect)
    exec "$PYTHON" "$RUN_DIR/inventory/source/baseline_inventory.py" collect --run-dir "$RUN_DIR"
    ;;
  submit|resume)
    command -v sbatch >/dev/null || { echo 'sbatch unavailable; submit from a Slurm cluster.' >&2; exit 1; }
    if [[ -f "$RUN_DIR/inventory/array_jobs.txt" ]]; then
      PREVIOUS_JOB=$(tail -n 1 "$RUN_DIR/inventory/array_jobs.txt")
      if [[ -n "$(squeue --noheader --jobs="$PREVIOUS_JOB" --format='%i' 2>/dev/null)" ]]; then
        echo "Inventory array $PREVIOUS_JOB is still active; wait before resubmitting." >&2
        exit 1
      fi
    fi
    "$PYTHON" "$SOURCE_DIR/baseline_inventory.py" prepare --run-dir "$RUN_DIR" "${TIMEOUT_ARGS[@]}"
    export BATCH_SIZE="${BATCH_SIZE:-100}"
    export MAX_PARALLEL="${MAX_PARALLEL:-50}"
    LAST_TASK=$("$PYTHON" - "$RUN_DIR" "$BATCH_SIZE" "$MAX_PARALLEL" <<'PY'
import json
from pathlib import Path
import sys
count = json.loads((Path(sys.argv[1]) / 'manifest.json').read_text())['count']
batch, parallel = map(int, sys.argv[2:])
if batch < 1 or parallel < 1:
    raise SystemExit('BATCH_SIZE and MAX_PARALLEL must be positive.')
print((count - 1) // batch)
PY
)
    ARRAY_JOB=$(sbatch --parsable --job-name=mealy-groups \
      --account="${SLURM_ACCOUNT:-def-nehaniv_cpu}" --cpus-per-task=1 \
      --mem="${SLURM_MEMORY:-32G}" --time="${SLURM_TIME:-1-00:00:00}" \
      --array="0-${LAST_TASK}%${MAX_PARALLEL}" --chdir="$RUN_DIR" \
      --output="$RUN_DIR/inventory/array-%A_%a.out" --error="$RUN_DIR/inventory/array-%A_%a.err" \
      "$RUN_DIR/inventory/source/baseline_inventory.sh" worker "$RUN_DIR")
    ARRAY_JOB="${ARRAY_JOB%%;*}"
    printf '%s\n' "$ARRAY_JOB" >> "$RUN_DIR/inventory/array_jobs.txt"
    COLLECT_JOB=$(sbatch --parsable --job-name=mealy-groups-collect \
      --account="${SLURM_ACCOUNT:-def-nehaniv_cpu}" --cpus-per-task=1 --mem=4G --time=01:00:00 \
      --dependency="afterany:${ARRAY_JOB}" --chdir="$RUN_DIR" \
      --output="$RUN_DIR/inventory/collect-%j.out" --error="$RUN_DIR/inventory/collect-%j.err" \
      "$RUN_DIR/inventory/source/baseline_inventory.sh" collect "$RUN_DIR")
    printf 'Inventory array: %s; collector: %s\n' "$ARRAY_JOB" "$COLLECT_JOB"
    ;;
  *) echo "Unknown mode: $MODE" >&2; exit 1 ;;
esac
