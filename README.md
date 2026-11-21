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

This generates and saves the automata, freezes a copy of the analysis source, checks SgpDec, and submits 500 independent array tasks of 20 automata each, with at most 50 tasks running concurrently. Each task requests one CPU, 32 GB RAM, and four days. Each GAP process has a 24 GB workspace limit and a four-hour timeout. A collector job runs after the array ends, including when tasks fail. The 500-task array leaves space for the collector under Nibi's 1,000-job submission limit.

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
