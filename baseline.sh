#!/bin/bash
set -euo pipefail

usage() {
  cat <<'HELP'
Usage: bash baseline.sh {generate|submit|resume|worker|collect} RUN_DIRECTORY

generate  Create 10,000 automata (COUNT and SEED_START override defaults).
submit    Generate if needed, verify SgpDec, submit a Slurm array and collector.
resume    Resubmit an existing run; completed automata are skipped.
collect   Export CSV and Excel results, including pending and failed cases.
worker    Internal Slurm array entry point.

Required for submit/resume: SGPDEC_DIR (clean lower-bound branch checkout).
Optional: GAPCMD, SGPDEC_COMMIT, AUTOMATA_ENV, PYTHON_MODULE, PYTHON,
          BATCH_SIZE=20, MAX_PARALLEL=50, SLURM_ACCOUNT=def-nehaniv_cpu,
          SLURM_MEMORY=32G, SLURM_TIME=2-00:00:00,
          GAP_MEMORY=24g, TIMEOUT_SECONDS=7200.
Defaults give 500 array tasks with at most 50 running concurrently.
HELP
}

if [[ $# -eq 0 || "${1:-}" == --help || "${1:-}" == -h ]]; then
  usage
  exit 0
fi
if [[ $# -ne 2 ]]; then usage >&2; exit 1; fi
MODE="$1"
RUN_DIR="$2"
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
RUN_DIR=$("$PYTHON" -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$RUN_DIR")

case "$MODE" in
  generate)
    exec "$PYTHON" "$SOURCE_DIR/baseline.py" generate --run-dir "$RUN_DIR" \
      --count "${COUNT:-10000}" --seed-start "${SEED_START:-0}"
    ;;
  worker)
    exec "$PYTHON" "$RUN_DIR/source/baseline.py" analyze --run-dir "$RUN_DIR" \
      --task-id "${SLURM_ARRAY_TASK_ID:?Missing Slurm array task ID}" \
      --batch-size "${BATCH_SIZE:-20}"
    ;;
  collect)
    exec "$PYTHON" "$RUN_DIR/source/baseline.py" collect --run-dir "$RUN_DIR"
    ;;
  submit|resume)
    command -v sbatch >/dev/null || { echo 'sbatch unavailable; submit from a Slurm cluster.' >&2; exit 1; }
    : "${SGPDEC_DIR:?Set SGPDEC_DIR to the pinned lower-bound branch checkout}"
    if [[ -f "$RUN_DIR/array_jobs.txt" ]]; then
      PREVIOUS_JOB=$(tail -n 1 "$RUN_DIR/array_jobs.txt")
      if [[ -n "$(squeue --noheader --jobs="$PREVIOUS_JOB" --format='%i' 2>/dev/null)" ]]; then
        echo "Array $PREVIOUS_JOB is still active; wait for it before resubmitting." >&2
        exit 1
      fi
    fi
    if [[ ! -f "$RUN_DIR/manifest.json" ]]; then
      if [[ "$MODE" == resume ]]; then echo 'No existing run to resume.' >&2; exit 1; fi
      "$PYTHON" "$SOURCE_DIR/baseline.py" generate --run-dir "$RUN_DIR" \
        --count "${COUNT:-10000}" --seed-start "${SEED_START:-0}"
    fi
    "$PYTHON" "$RUN_DIR/source/baseline.py" preflight --run-dir "$RUN_DIR" \
      --gap "${GAPCMD:-$HOME/gap/gap-4.14.0/gap}" --sgpdec-dir "$SGPDEC_DIR" \
      --sgpdec-commit "${SGPDEC_COMMIT:-8e0f8cb20ace52762dc9dcc2be3358db4abc51bd}" \
      --gap-memory "${GAP_MEMORY:-24g}" --timeout "${TIMEOUT_SECONDS:-7200}"
    export BATCH_SIZE="${BATCH_SIZE:-20}"
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
    ARRAY_JOB=$(sbatch --parsable --job-name=mealy-baseline \
      --account="${SLURM_ACCOUNT:-def-nehaniv_cpu}" --cpus-per-task=1 \
      --mem="${SLURM_MEMORY:-32G}" --time="${SLURM_TIME:-2-00:00:00}" \
      --array="0-${LAST_TASK}%${MAX_PARALLEL}" --chdir="$RUN_DIR" \
      --output="$RUN_DIR/logs/array-%A_%a.out" --error="$RUN_DIR/logs/array-%A_%a.err" \
      "$RUN_DIR/source/baseline.sh" worker "$RUN_DIR")
    ARRAY_JOB="${ARRAY_JOB%%;*}"
    printf 'Array job: %s\n' "$ARRAY_JOB"
    printf '%s\n' "$ARRAY_JOB" >> "$RUN_DIR/array_jobs.txt"
    COLLECT_JOB=$(sbatch --parsable --job-name=mealy-baseline-collect \
      --account="${SLURM_ACCOUNT:-def-nehaniv_cpu}" --cpus-per-task=1 --mem=4G --time=01:00:00 \
      --dependency="afterany:${ARRAY_JOB}" --chdir="$RUN_DIR" \
      --output="$RUN_DIR/logs/collect-%j.out" --error="$RUN_DIR/logs/collect-%j.err" \
      "$RUN_DIR/source/baseline.sh" collect "$RUN_DIR")
    printf 'Collector job: %s\n' "$COLLECT_JOB"
    printf '%s\n' "$COLLECT_JOB" >> "$RUN_DIR/collector_jobs.txt"
    ;;
  *) usage >&2; exit 1 ;;
esac
