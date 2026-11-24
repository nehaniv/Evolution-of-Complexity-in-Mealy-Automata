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

## Constrained Random Baseline

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

## Evolution timelines and group inventories

`EvolutionaryTimeline.py` saves population-best checkpoints and first-perfect
witnesses, then analyzes each reachable action with GAP/SgpDec. Alongside the
complexity bounds and `holonomy_groups.csv`, it exports `permutator_groups.csv`
and a **Permutator groups** worksheet in `experiment_results.xlsx`.

Each permutator record includes run, generation, snapshot kind, skeleton level,
representative index/set, action domain and degree, order, structure description,
permutation generators, triviality and solvability. Pair it with its holonomy
record using `(run, generation, snapshot_kind, level, representative_index)`;
the representative sets are also checked for agreement. Permutator permutations
act on the recorded domain using GAP labels `1..N`: label `j` corresponds to the
`j`th sorted original reachable state in the snapshot. Fixed points are retained
in the domain even when absent from the printed generators. Singleton classes
are omitted from both inventories since their groups are trivial.

To add these records to an existing completed experiment:

```bash
python3 EvolutionaryTimeline.py --analyze_only /path/to/experiment --gap /path/to/gap
```

The original bounds scripts and cache keys are unchanged. Valid bounds results
are reused; a separate GAP pass constructs the skeleton and computes only the
permutator inventory, without the essential-dependency lower-bound calculation.
Its results are cached in `*.permutators.result.json`, with separate GAP scripts
and logs. Subsequent analyses reuse both caches. As before, bounds caches require
matching snapshots, scripts and GAP/SgpDec software metadata. The evolution and
its random-number stream are unchanged. Exact evolution resumption still
requires the original runner version; use the patched runner for analysis only
on experiments created with the old runner.

`non_solvable_group_occurrences` continues to count holonomy occurrences.
`non_solvable_permutator_occurrences` counts permutator occurrences separately.
These count non-solvable representative groups, rather than simple non-abelian
composition factors. Repeated isomorphic groups on different representatives
are retained. A failed/missing permutator analysis has a separate status and
blank count, never a fabricated zero; validated bounds remain available.

For comparisons with random baselines, use the same reachable-action restriction,
group inventory convention, alphabet and number of complete states. Match or
stratify by reachable-state count `N`. Compare independent baseline automata
against the population best at common scheduled generations; event-driven
snapshots and first-perfect witnesses have different sampling rules. Keep
permutator and holonomy counts separate because the latter groups are quotients
of the former.

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


## Backfill permutators from the Nibi timeline bundle

For the saved Mac/Nibi experiment, `BackfillPermutators.py` validates the original
local logs and `nibi_analysis/batch*/jobs/*/analysis.log` results. It checks the
snapshot and program hashes, software versions/modifications, Nibi log hashes,
completion markers, and group inventories. Only the executable and installation
paths may differ between Mac and Nibi. It does not read bounds from the spreadsheet.
The whole experiment directory, including the Nibi task results, must be copied.

From the repository with the usual Python environment and GAP installation:

```bash
python3 BackfillPermutators.py results/nibi_permutators --check_only
python3 -u BackfillPermutators.py results/nibi_permutators --gap "$(command -v gap)" --limit 5
python3 -u BackfillPermutators.py results/nibi_permutators --gap "$(command -v gap)"
```

The first command does not launch GAP or modify files. For the November 19 Nibi
batch, the expected count is 546/548 unless additional analyses have since finished.
The helper NEVER runs evolution or complexity-bound searches. Snapshots without
validated bounds remain pending; fix those separately. `--limit 5` limits new
permutator calculations to five for a smoke test. Rerunning without `--limit`
reuses validated completed permutator logs. The process returns exit code 1 when
any snapshot is pending or failed, including the two known missing bounds.

New reports, logs, source copies, software metadata and caches go in
`results/nibi_permutators/permutator_backfill/`; the original bounds files and
reports are not changed. The new directory contains a relative `snapshots`
symlink to the original snapshots. Keep both directories together if archiving
it; the spreadsheet and group CSV files can be sent individually. Bounds log
paths in `bounds_provenance.json` are relative to the original experiment.
The two non-solvable occurrence counts remain separate. The new report includes
only the snapshots, not per-generation metrics or fresh plots.

Do not run two backfills in the same output directory simultaneously. The helper
locks its own directory. Keep the Mac awake while it runs. If interrupted, repeat
the same command: completed inventories are reused, and the current unfinished
inventory is recalculated. Close the workbook before a rerun updates it.

Validation: the supplemental parser/cache tests use simulated GAP output; the
real long generation-30000 log was also reparsed successfully. Run the two live
GAP tests on your own installation with:

```bash
SGPDEC_TEST_GAP="$(command -v gap)" python3 -m unittest discover -s tests -v
```
