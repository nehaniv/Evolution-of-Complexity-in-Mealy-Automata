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

`baseline.sh` generates 10 automata using seeds 0–9, each with 15 states and exactly 9 states reachable from initial state 0. It evaluates them with `MultiTraversal` fitness in `SimpleHardestEnvironment`, using input symbols `1`–`8` and output symbols `0`–`1`, then runs GAP/SgpDec complexity analysis on their reachable parts.

**Sampling limitation:** the generator forces a Hamiltonian path `0 -> 1 -> ... -> 8` through the reachable states and keeps all transitions from those states within `0`–`8`. This guarantees exactly 9 reachable states, but it does **not** sample uniformly from all 15-state automata with 9 reachable states. Automata whose reachable part has no Hamiltonian path starting at the initial state cannot be generated; the fixed state labels and forced path further constrain the sample. These results should therefore be interpreted as a constrained random baseline.

The script is configured for a Slurm cluster. Before running it, adjust the `#SBATCH` account and resource settings, Python module, virtual environment path, and `GAPCMD` to match your installation. Run it from a directory containing `baseline.sh` and `ES-Automata-Fogel.py` after installing the dependencies below:

```bash
sbatch baseline.sh
```

It produces GAP input and output files, CSV metadata and summaries, optional Excel/PDF reports, and a compressed results archive. Its fixed `BASELINE_STAMP` preserves the experiment's output naming; use a separate working directory for each run to avoid overwriting earlier results.

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
