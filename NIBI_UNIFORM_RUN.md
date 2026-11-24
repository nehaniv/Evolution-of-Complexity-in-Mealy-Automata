# Nibi uniform baseline run

## Audit of the retained sample

The 10,000-automaton run `mealy-baseline-10000-indexed-20261121` is the
Hamiltonian-path baseline. Its manifest and frozen `source/baseline.py` agree:
the generator fixes the initial state to 0, forces `0 -> 1 -> ... -> 8`, and
closes transitions from those nine states. It is not the uniform sample.

The final collection on November 22, 2026 contains 9,989 completed bound searches,
11 timed-out searches with certified partial bounds, and no pending cases.
The sample, results, frozen source and attempt logs are retained separately.
The audited frozen `baseline.py` SHA-256 is
`a9ce1c35eba804c5e3c81e236c2ada503e19ccce1c6fe2f3f98df4a38cba4efa`.
The working branch starts from `origin/main` commit
`c7161aa3748d948d08c4d95e1379c797ed0fc73b`.

Use `nina-uniform-baseline` for the new experiment. The combined supplied patch
is applied, with a correction to load the frozen sampler when Slurm executes a
spooled copy of `baseline_uniform.sh`. A regression test covers that layout.
The sampler's random-call order and the group calculations are unchanged.
The ALIFE 2026 release is unchanged.

## Environment and validation

On Nibi, from the checked-out `nina-uniform-baseline` branch:

```bash
module load python/3.10
source "$HOME/automata-env/bin/activate"
export GAPCMD="$HOME/gap/gap-4.14.0/gap"
export SGPDEC_DIR="$HOME/mealy-baseline-20261121/deps/sgpdec"
export SGPDEC_COMMIT=8e0f8cb20ace52762dc9dcc2be3358db4abc51bd
export SLURM_ACCOUNT=def-nehaniv_cpu
export MPLBACKEND=Agg
export MPLCONFIGDIR="${TMPDIR:-/tmp}/mealy-matplotlib-${USER}"
export PYTHONDONTWRITEBYTECODE=1

SGPDEC_TEST_GAP="$GAPCMD" SGPDEC_TEST_DIR="$SGPDEC_DIR" \
  python3 -m unittest tests_baseline tests_baseline_inventory tests_uniform_baseline -v
bash -n baseline.sh
bash -n baseline_uniform.sh
bash -n baseline_inventory.sh
```

Local validation on November 24 passed 20 tests; three live GAP/SgpDec tests
were skipped because that installation was unavailable locally. Do not count
those skipped tests as a passed cluster pilot. Nibi's planned outage includes
login nodes and scheduling through November 25, 2026 at 16:00 EST:
<https://status.alliancecan.ca/view_incident?incident=1782>.

## Two-automaton pilot

Use a new directory. Preserve any pre-existing run and inspect its manifest
before choosing a different directory or using `resume`.

```bash
PILOT_RUN="$HOME/scratch/mealy-uniform-pilot-20261124"
COUNT=2 BATCH_SIZE=1 MAX_PARALLEL=2 SLURM_TIME=03:00:00 \
  bash baseline_uniform.sh submit "$PILOT_RUN"
```

Wait for the bound array and its collector to finish. Then submit the paired
group inventory and wait for that array and collector:

```bash
BATCH_SIZE=1 MAX_PARALLEL=2 SLURM_TIME=00:30:00 \
  bash baseline_inventory.sh submit "$PILOT_RUN"
bash baseline_uniform.sh collect "$PILOT_RUN"
bash baseline_inventory.sh collect "$PILOT_RUN"
```

Before production, check both pilot automata's initial states and reachable
labels against the saved tables and GAP inputs; check all bound, performance
and inventory statuses; reconcile raw/capped upper bounds; inspect both paired
group tables and the workbook. Investigate errors before proceeding.

## Production and collection

After the pilot passes, use a new directory for the uniform sample:

```bash
UNIFORM_RUN="$HOME/scratch/mealy-uniform-10000"
bash baseline_uniform.sh submit "$UNIFORM_RUN"
```

Defaults are 10,000 automata, seeds 0 through 9,999, 15 labelled states,
exactly nine reachable states, eight input symbols and two output symbols.
The initial state is sampled uniformly within the sampled reachable subset.
The bound array has 500 batches of 20, at most 50 concurrent tasks, and a
two-hour limit per case. Keep the selected SgpDec revision fixed.

After the bound array finishes:

```bash
bash baseline_inventory.sh submit "$UNIFORM_RUN"
```

After both arrays finish, run these as two separate commands:

```bash
bash baseline_uniform.sh collect "$UNIFORM_RUN"
bash baseline_inventory.sh collect "$UNIFORM_RUN"
```

Deliver `inventory/baseline_inventory_results.xlsx`, its CSV,
`inventory/holonomy_groups.csv`, `inventory/permutator_groups.csv`,
`inventory/group_distribution.csv`, and the run metadata separately from Git.
Keep non-solvable holonomy and permutator occurrence counts separate; neither
is a SNAG composition-factor multiplicity.

Retain the complete `automata.jsonl`, seeds and metadata, both source snapshots,
`manifest.json`, `analysis.json`, inventory configuration and software versions,
all case attempts, scheduler logs and final reports. Copy them into a new
persistent directory under `$HOME/mealy-uniform-20261124/results/` and verify
checksums before relying on that copy. Preserve timeout/failed statuses and
certified partial bounds. Missing measurements remain blank.
