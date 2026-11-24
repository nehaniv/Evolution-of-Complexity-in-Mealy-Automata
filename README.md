# Evolution-of-Complexity-in-Mealy-Automata

## ALIFE 2026 Paper and Citation

The [**ALIFE 2026** release](https://github.com/nehaniv/Evolution-of-Complexity-in-Mealy-Automata/releases/tag/alife-2026) contains the evolution, complexity analysis, and constrained random baseline code accompanying the following paper. Please cite it when using this code:

Nehaniv, Chrystopher L., Hanna Derets, and Nina Phuong Nghi Do. 2026. "[Excavating Fogel's Fossil Record: Hierarchical Complexity in Evolved Automata](https://doi.org/10.1162/ISAL.a.990)." *Proceedings of the 2026 Artificial Life Conference* 38: 64–72, MIT Press.

## Mealy Automata Evolution Framework

This project implements an **evolutionary strategy (ES)** for evolving **Mealy automata** to solve predictive tasks such as:
- Traversal of deterministic environments (e.g., "SimpleHardestEnvironment")
- Pattern prediction (e.g., EightBall, FogelPalindrome)

## Complexity Analysis using Krohn-Rhodes Algebraic Automata Theory
- Complexity Upper Bound computed using the holonomy decomposition method
- Complexity Lower Bound computed by finding a longest chain of essential dependencies
- Note: The number of reachable states minus 1 is a sharp upper bound too

The evolution framework and its complexity analysis are implemented in:
- `ES-Automata-Fogel.py`

A bash script is provided for running the system with customizable parameters:
- `MealyEvolutionStrategy.sh`

The constrained random baseline and its GAP analysis are provided in:

- `baseline.sh`

## Uniform baseline for new comparisons

Use **`baseline_uniform.sh`** for the required non-evolved baseline. It samples
uniformly over labelled 15-state Mealy automata with a designated initial state,
eight inputs, two outputs, and exactly nine reachable states. `uniform_sampling.py`
chooses a nine-state subset uniformly, chooses the initial state uniformly within
it, and samples all transitions within that subset independently and uniformly,
rejecting only tables for which fewer than nine states are reachable. The
acceptance probability is the same for every subset/initial-state choice.
Transitions from the other six states and all output entries are sampled
independently and uniformly. Thus each complete labelled automaton satisfying
the condition has the same sampling probability; no Hamiltonian path is imposed.
This is uniform over labelled automata, not over isomorphism classes.

The first ten seeds reproduce the transition/output tables of the earlier
uniform-generator package. The actual initial state and full tables are stored
in `automata.jsonl`. Bound analysis and group inventories independently restrict
to the actual reachable states and relabel them for GAP, rather than assuming
that states `0..8` are the reachable set.

With the same clean SgpDec checkout and GAP installation configured below:

```bash
# Small pilot in a NEW directory; wait for its bound array to finish.
COUNT=2 BATCH_SIZE=1 MAX_PARALLEL=2 bash baseline_uniform.sh submit /path/to/uniform-pilot
bash baseline_inventory.sh submit /path/to/uniform-pilot
# After both arrays finish, collect current bounds plus structural data.
bash baseline_uniform.sh collect /path/to/uniform-pilot
bash baseline_inventory.sh collect /path/to/uniform-pilot

# Production run, again in a NEW directory; defaults to seeds 0..9999.
bash baseline_uniform.sh submit /path/to/uniform-10000
# After its bound array finishes (or independently if cluster capacity permits):
bash baseline_inventory.sh submit /path/to/uniform-10000
# Recollect after all bound and inventory jobs finish.
bash baseline_uniform.sh collect /path/to/uniform-10000
bash baseline_inventory.sh collect /path/to/uniform-10000
```

The first job computes certified lower bounds and upper bounds capped at `N-1`.
The second records representative holonomy and permutator groups, recomputes
performance, and joins the saved bounds into CSV/Excel with the same group-count
conventions as Annie's evolution timelines. See the supplementary-record section
below for outputs and retry commands. Bounds and inventory statuses are separate.
Before joining an existing bound, the inventory collector checks that its saved
`analyze.g` generators equal the automaton's actual reachable action. Missing or
mismatched GAP inputs give an invalid bound status and a diagnostic, with the
original result untouched. A uniform generator inserted into the old fixed-state
runner may therefore need its bounds recomputed from the saved automata.

`baseline_uniform.sh` refuses to operate on an existing directory with a
different sampling label. Preserve old datasets and their frozen `source/`
copies; applying this patch does not change their sampling method or rerun them.
An already valid uniform dataset can be backfilled directly if it uses the
indexed-JSONL batch layout. Older `.g`/CSV-only data need a format adapter and
must retain their original generator, metadata and complete automata. Do not
regenerate or relabel such data merely to satisfy a filename convention.

Direct `python3 baseline.py generate` also defaults to uniform sampling.
`baseline.sh` explicitly selects the legacy Hamiltonian method for reproducing
the paper's original baseline. Dataset labels in both summary workbooks come
from the saved manifest.

The recent 10,000-automaton runner is on `main` (November 2026 commits).
`nina` and `nina-2` are older branches; `nina-2` has already been merged into
`main`. Apply the combined patch on a clean branch based on current `main`.
The original evolution code in `ES-Automata-Fogel.py` is unchanged.

## Legacy Hamiltonian-path baseline

`baseline.sh` now runs a **10,000-automaton baseline** using seeds 0–9,999. Each automaton has 15 states and exactly 9 states reachable from initial state 0. The first 10 automata reproduce the ALIFE 2026 baseline. Fitness uses `MultiTraversal` in `SimpleHardestEnvironment`, with input symbols `1`–`8` and output symbols `0`–`1`.

**Sampling limitation:** the generator forces a Hamiltonian path `0 -> 1 -> ... -> 8` through the reachable states and keeps their transitions within `0`–`8`. It does **not** sample uniformly from all 15-state automata with 9 reachable states. Automata without a Hamiltonian path from the initial state through all reachable states cannot be generated. The fixed labels and forced path further constrain the sample.

### SgpDec lower-bound branch

The parallel baseline requires [`feature/essential-dependency-progress`](https://github.com/gap-packages/sgpdec/tree/feature/essential-dependency-progress), pinned by default to commit `8e0f8cb20ace52762dc9dcc2be3358db4abc51bd`. It calls `MaxChainOfEssentialDependencyWithProgress` and records its numeric lower bound, search status, and certified progress. It never estimates a lower bound by counting arrows in printed output.

Use a separate, clean checkout so existing GAP installations remain available:

```bash
git clone --branch feature/essential-dependency-progress https://github.com/gap-packages/sgpdec.git ~/sgpdec-lowerbounds
git -C ~/sgpdec-lowerbounds checkout 8e0f8cb20ace52762dc9dcc2be3358db4abc51bd
export SGPDEC_DIR="$HOME/sgpdec-lowerbounds"
export GAPCMD="$HOME/gap/gap-4.14.0/gap"
```

GAP loads that exact checkout with `SetPackagePath`. A preflight checks the installed API and known complexity-0 and complexity-2 examples before any array is submitted. A different intended revision can be selected with `SGPDEC_COMMIT`, but it must provide this API and pass preflight. Every result records the revision used.

### Submit on a Slurm cluster

Run from the repository directory with the dependencies installed in `~/automata-env` (or set `AUTOMATA_ENV`). The defaults match the Nibi CPU allocation; adjust `SLURM_ACCOUNT` on another cluster.

```bash
export SLURM_ACCOUNT=def-nehaniv_cpu
bash baseline.sh submit "$HOME/scratch/mealy-baseline-10000"
```

This generates and saves the automata, freezes a copy of the analysis source, checks SgpDec, and submits 500 independent array tasks of 20 automata each, with at most 50 tasks running concurrently. Each task requests one CPU, 32 GB RAM, and two days. Each GAP process has a 24 GB workspace limit and a two-hour timeout. A collector job runs after the array ends, including when tasks fail. The 500-task array leaves space for the collector under Nibi's 1,000-job submission limit.

A smaller pilot can be submitted first:

```bash
COUNT=10 BATCH_SIZE=1 MAX_PARALLEL=10 bash baseline.sh submit "$HOME/scratch/mealy-baseline-pilot"
```

`COUNT`, `SEED_START`, `BATCH_SIZE`, `MAX_PARALLEL`, `SLURM_MEMORY`, `SLURM_TIME`, `GAP_MEMORY`, `TIMEOUT_SECONDS`, `PYTHON_MODULE`, and `PYTHON` are configurable environment variables. Keep the task wall time longer than `BATCH_SIZE * TIMEOUT_SECONDS` plus startup time. Generate a dataset without Slurm using `bash baseline.sh generate RUN_DIRECTORY`.

### Results and resuming

The run directory contains:

- `baseline_results.xlsx`: one row per automaton, with reachable state count, holonomy upper bound, lower bound, certified upper bound, exactness, fitness, status, seed, and provenance; a separate sheet summarizes interval frequencies.
- `baseline_results.csv` and `interval_distribution.csv`: the same measurements and grouped interval counts for analysis tools.
- `automata.jsonl`: full transition/output tables for all 15 states, not just seeds. `metadata.csv` indexes each record by byte offset, length, and SHA-256 checksum, avoiding thousands of small input files on the cluster filesystem.
- `cases/`: separate logs, numeric bounds, lower-bound progress, and results for each automaton and attempt.
- `manifest.json`, `analysis.json`, and `source/`: generation settings, file hashes, pinned software, and the exact run source.

The holonomy upper bound is stored separately from `certified_upper_bound = min(holonomy_upper_bound, reachable_states - 1)`. The latter can stop the lower-bound search once exact complexity is proved. `search_exhausted` means the dependency search finished; it does not by itself mean the complexity is exact.

Timeouts retain certified partial lower bounds when available and are labelled `timeout`. Missing or failed analyses have blank bounds, never invented zeros. Interval frequencies separate completed and timed-out searches, and fractions use all requested automata as the denominator. The collector returns exit code 2 if any analysis is unfinished, after saving the available results.

```bash
# Inspect or collect current results at any time.
squeue -u "$USER"
bash baseline.sh collect "$HOME/scratch/mealy-baseline-10000"

# After the array ends, retry unfinished cases. Completed results are reused.
bash baseline.sh resume "$HOME/scratch/mealy-baseline-10000"
```

Each retry preserves earlier attempt logs. Increase `TIMEOUT_SECONDS` and `SLURM_TIME` together when longer searches are needed; changing GAP or SgpDec requires a new run directory. Use a fresh directory for a new sample. Copy completed results from scratch to persistent storage under your cluster's retention policy.

The original 10-automaton script remains available in the [ALIFE 2026 release](https://github.com/nehaniv/Evolution-of-Complexity-in-Mealy-Automata/releases/tag/alife-2026).

### Validation

```bash
python3 -m unittest tests_baseline -v
bash -n baseline.sh
```

### Supplementary performance and group records

`baseline_inventory.py` adds the structural and performance records used in
`EvolutionaryTimeline.py`, including the new representative permutator inventory.
It reads an existing baseline run and writes exclusively under its new
`inventory/` directory. The generated automata, frozen `source/`, existing
bound results and any running lower-bound searches are preserved. Use the
supplement with the current `main` baseline format (`automata.jsonl`,
`metadata.csv`, `manifest.json`, `analysis.json`); Annie's branch contains an
older baseline script and does not supply that batch format.

For Nina's existing 10,000-automaton dataset, install these new files beside
`baseline.py` and run:

```bash
bash baseline_inventory.sh submit /path/to/ninas-baseline-run
```

The supplement uses the pinned GAP/SgpDec installation from `analysis.json`,
checks the saved source and archive hashes, and freezes its own source. Its
default array has 100 tasks of 100 automata with at most 50 tasks in parallel.
Each inventory has a five-minute GAP limit; each task requests one day, one CPU
and 32 GB. `INVENTORY_TIMEOUT_SECONDS`, `BATCH_SIZE`, `MAX_PARALLEL`,
`SLURM_ACCOUNT`, `SLURM_MEMORY`, and `SLURM_TIME` are configurable. Choose a task
wall time greater than batch size times inventory timeout plus startup/export
overhead. Set `INVENTORY_TIMEOUT_SECONDS` explicitly on `resume` to raise the
inventory retry limit; completed inventories remain cached, and each result
retains its own timeout setting. Otherwise the existing limit is retained.
This group pass builds a skeleton but does not run the essential-dependency
lower-bound search. Completed inventories are cached separately.

```bash
# Collect at any time, including while the original bounds search is running.
bash baseline_inventory.sh collect /path/to/ninas-baseline-run

# Retry missing/failed inventories after the inventory array finishes.
bash baseline_inventory.sh resume /path/to/ninas-baseline-run
```

For a small local pilot instead of Slurm:

```bash
python3 baseline_inventory.py prepare --run-dir /path/to/run --timeout 300
python3 /path/to/run/inventory/source/baseline_inventory.py analyze \
  --run-dir /path/to/run --task-id 0 --batch-size 2
python3 /path/to/run/inventory/source/baseline_inventory.py collect --run-dir /path/to/run
```

`inventory/baseline_inventory_results.xlsx` and its corresponding CSV record:

- Original automaton ID, seed, initial state, complete/reachable state counts,
  sampling method, archive byte offsets and hashes, and the original reachable
  state labels. Full transition/output tables remain in `automata.jsonl`; the
  saved reachable labels identify both the restricted action and its relabelling.
- Recomputed raw all-start traversal performance, penalized fitness, state cost,
  per-start coverage and perfect-traversal status. Fitness is checked against the
  original value using the saved evolution source.
- Existing lower and upper bounds, bound status, and distance/normalized bounds
  relative to `N-1`. The group pass also supplies a certified upper bound when
  the lower-bound result is still pending. Recollect after the original bound
  jobs finish to include their latest results.
- Holonomy depth, number of group-bearing levels, and separate counts of
  non-solvable holonomy and permutator group occurrences.
- Inventory status, errors, elapsed time, GAP/Semigroups versions, SgpDec commit,
  source hashes and analysis settings. Pending/failed counts remain blank.

Separate `Holonomy groups` and `Permutator groups` worksheets and CSV files
record one occurrence per representative per non-singleton skeleton level,
retaining repetitions on distinct representatives. Each includes level,
representative index/set, order, structure description, permutation generators,
triviality and solvability; permutators additionally include their action domain
and degree. Pair the two inventories using automaton ID, level and representative
index. Permutator generators use GAP labels `1..N`, in the order of the sorted
original reachable labels. Singleton classes are omitted since their groups are
trivial. These are the same group/count conventions used in Annie's patch.

`Group distribution` reports the joint frequency of the two non-solvable-group
counts, with denominators for both all requested automata and completed
inventories. Such counts measure group occurrences; SNAG composition-factor
multiplicities require a subsequent calculation from the recorded groups. The
two inventories should be analysed separately since holonomy groups are
quotients of permutator groups. The Excel exporter streams large group tables
and splits sheets if Excel's row limit is reached; CSV retains the whole table.

Baseline records have automaton IDs instead of evolutionary run/generation and
event fields. Population checkpoints and first-emergence times do not apply to
independently generated baseline automata. The sampling label comes from the
original manifest: running this supplement does not convert the Hamiltonian-path
baseline into a uniform sample. Comparisons with uniform samples must retain
that distinction and match the reachable-state count, alphabets and environment.

```bash
python3 -m unittest tests_baseline tests_baseline_inventory -v
bash -n baseline_inventory.sh
# To enable the live integration checks as well:
SGPDEC_TEST_GAP=/path/to/gap SGPDEC_TEST_DIR=/path/to/sgpdec \
  python3 -m unittest tests_baseline_inventory -v
```

Uniform sampler and full-pipeline checks:

```bash
python3 -m unittest tests_baseline tests_baseline_inventory tests_uniform_baseline -v
bash -n baseline_uniform.sh
SGPDEC_TEST_GAP=/path/to/gap SGPDEC_TEST_DIR=/path/to/sgpdec \
  python3 -m unittest tests_baseline tests_baseline_inventory tests_uniform_baseline -v
```

##  Python Environment Setup

We recommend using a Python virtual environment to manage dependencies cleanly.

### Prerequisites
- Python 3.10 or newer (tested with Python 3.13)
- [GAP](https://www.gap-system.org/) with package [SgpDec](https://github.com/gap-packages/sgpdec) (for algebraic decomposition and complexity analysis of automata)
- `graphviz` (for visualization of automata) 
- `pdflatex` (for LaTeX report generation)

#### Quick Setup Using `venv`

```bash
# Create and activate virtual environment
python3 -m venv automata-env
source automata-env/bin/activate  # or 'automata-env\Scripts\activate' on Windows

# Install dependencies
pip install -r requirements.txt

```


#### Quick Setup Using Conda


```
conda env create -f environment.yml
conda activate automata-env
```


##  Running the Evolution and Complexity Analysis
bash MealyEvolutionStrategy.sh


You can modify MealyEvolutionStrategy.sh to adjust:

Population size, Number of states, Number of offspring, Number of generations, Number of runs, Fitness function (and possibly Environment variant), Initialization method (e.g. self-looped, random, from file)


A number of results are timestamped and saved:

LaTeX reports (.tex, compiled to .pdf)  - note there is a preliminary evolution report produced that does not rely on the complexity analysis. 

GAP scripts and outputs (.g, .txt)

Graphs (.pdf)

Summary Excel files (.xlsx)

Pickled best automata (.pkl)
