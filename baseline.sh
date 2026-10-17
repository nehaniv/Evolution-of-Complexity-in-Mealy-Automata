#!/bin/bash
#SBATCH --account=def-nehaniv
#SBATCH --job-name=baseline-random-gap
#SBATCH --output=baseline-random-gap-%j.out
#SBATCH --error=baseline-random-gap-%j.err
#SBATCH --cpus-per-task=1
#SBATCH --mem=32G
#SBATCH --time=5-00:00:00

module load python/3.10
source ~/automata-env/bin/activate

set -euo pipefail

BASELINE_STAMP="baseline_20260612180910"
GAPCMD="$HOME/gap/gap-4.14.0/gap"

date
echo "Working directory: $(pwd)"
echo "Using GAPCMD: $GAPCMD"

if [ ! -f "ES-Automata-Fogel.py" ]; then
  echo "ERROR: Missing ES-Automata-Fogel.py"
  exit 1
fi

if [ ! -x "$GAPCMD" ]; then
  echo "ERROR: GAP executable not found at $GAPCMD"
  echo "Try: ls -l ~/gap/gap-4.14.0/gap"
  exit 1
fi

# Generate 10 constrained random automata with exactly 9 reachable states.
# The forced Hamiltonian path makes this a nonuniform constrained baseline.

cat > generate_baseline_random.py <<'PYEOF'
import importlib.util
import random
import csv

SOURCE_FILE = "ES-Automata-Fogel.py"
BASELINE_STAMP = "baseline_20260612180910"

TARGET_COUNT = 10
NUM_STATES = 15
TARGET_REACHABLE = 9

FITNESS_NAME = "MultiTraversal"
ENV_VARIANT = "SimpleHardestEnvironment"

spec = importlib.util.spec_from_file_location("es_automata", SOURCE_FILE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

input_alphabet = [str(i) for i in range(1, 9)]
output_alphabet = ["0", "1"]
env_dfa = mod.EnvironmentDFA(8, ["0", "1"], variant=ENV_VARIANT)

def make_random_automaton_with_exact_reachable(seed):
    random.seed(seed)

    automaton = mod.MealyAutomaton(
        NUM_STATES,
        input_alphabet,
        output_alphabet,
        self_loop_init=False,
    )

    reachable_states = list(range(TARGET_REACHABLE))       # 0..8
    unreachable_states = list(range(TARGET_REACHABLE, NUM_STATES))  # 9..14

    automaton.initial_state = 0

    # Force all 9 target states to be reachable: 0 -> 1 -> ... -> 8
    # This excludes reachable subautomata without such a Hamiltonian path;
    # it is not uniform sampling of all automata with 9 reachable states.
    for state in range(TARGET_REACHABLE - 1):
        inp = random.choice(input_alphabet)
        automaton.transitions[(state, inp)] = state + 1

    # Keep reachable states closed inside 0..8.
    # This prevents states 9..14 from becoming reachable.
    for state in reachable_states:
        for inp in input_alphabet:
            if automaton.transitions[(state, inp)] >= TARGET_REACHABLE:
                automaton.transitions[(state, inp)] = random.choice(reachable_states)

    # Unreachable states can transition randomly anywhere.
    # They remain unreachable because reachable states never point to them.
    for state in unreachable_states:
        for inp in input_alphabet:
            automaton.transitions[(state, inp)] = random.randint(0, NUM_STATES - 1)

    # Randomize outputs
    for state in range(NUM_STATES):
        for inp in input_alphabet:
            automaton.outputs[(state, inp)] = random.choice(output_alphabet)

    actual_reachable = len(automaton.get_reachable_states())
    if actual_reachable != TARGET_REACHABLE:
        raise RuntimeError(f"Expected {TARGET_REACHABLE} reachable states, got {actual_reachable}")

    return automaton

def save_gap_file(automaton, baseline_id, reachable_only=True):
    suffix = "_reachable.g" if reachable_only else ".g"
    filename = f"baseline_random_{baseline_id}_{BASELINE_STAMP}{suffix}"

    states = automaton.get_reachable_states() if reachable_only else range(automaton.num_states)
    state_map = {old: i + 1 for i, old in enumerate(states)}

    with open(filename, "w") as gf:
        gf.write('LoadPackage("semigroups");\n')
        gf.write('LoadPackage("SgpDec");\n\n')

        for inp in automaton.input_alphabet:
            next_states = [state_map[automaton.transitions[(s, inp)]] for s in states]
            outputs = [int(automaton.outputs[(s, inp)]) for s in states]

            gf.write(f"NextState{inp} := Transformation([{', '.join(map(str, next_states))}]);\n")
            gf.write(f"# Output{inp} := [{', '.join(map(str, outputs))}];\n")

        gf.write(f"\nS_gen := [{', '.join([f'NextState{inp}' for inp in automaton.input_alphabet])}];\n")
        gf.write("S := Semigroup(S_gen); sk := Skeleton(S);\n")
        gf.write('Print("number of reachable states: ", Size(BaseSet(sk)), "\\n");\n')

        gf.write("cpxbound := 0;\n")
        gf.write("for dx in [1..DepthOfSkeleton(sk)-1] do\n")
        gf.write("  no_holonomy_group_seen_yet_at_this_level := true;\n")
        gf.write("  for x1 in RepresentativeSets(sk)[dx] do\n")
        gf.write("    px1 := PermutatorGroup(sk, x1);\n")
        gf.write("    hx1 := HolonomyGroup@SgpDec(sk, x1);\n")
        gf.write("    if IsTrivial(hx1) then\n")
        gf.write("      trivialgroup := true;\n")
        gf.write("    else\n")
        gf.write("      if no_holonomy_group_seen_yet_at_this_level then\n")
        gf.write("        cpxbound := cpxbound + 1;\n")
        gf.write("        no_holonomy_group_seen_yet_at_this_level := false;\n")
        gf.write("      fi;\n")
        gf.write("    fi;\n")
        gf.write("  od;\n")
        gf.write("od;\n")

        gf.write('Print("complexity upper bound:", cpxbound, "\\n");\n')
        gf.write('Print("non-aperiodic:", Minimum([cpxbound, 1]), "\\n");\n')
        gf.write("DisplayHolonomyComponents(sk);\n")
        gf.write('Print("\\n  Max Chain of Essential Dependencies: ");\n')
        gf.write("MaxChainOfEssentialDependency(sk);\n")

    return filename

selected = []

for baseline_id in range(1, TARGET_COUNT + 1):
    seed = baseline_id - 1
    automaton = make_random_automaton_with_exact_reachable(seed)

    fitness, _ = mod.multitraversal_fitness(automaton, env_dfa)
    reachable = len(automaton.get_reachable_states())

    save_gap_file(automaton, baseline_id, reachable_only=True)
    save_gap_file(automaton, baseline_id, reachable_only=False)

    selected.append({
        "Baseline ID": baseline_id,
        "Random Seed": seed,
        "Fitness": fitness,
        "Reachable States": reachable,
        "Number of States": NUM_STATES,
        "Target Reachable States": TARGET_REACHABLE,
        "Fitness Function": FITNESS_NAME,
        "Environment": ENV_VARIANT,
        "Generation Method": "constrained random exact reachable (forced Hamiltonian path; nonuniform)",
    })

    print(f"Selected baseline {baseline_id}: seed={seed}, fitness={fitness}, reachable={reachable}", flush=True)

metadata_file = f"baseline_random_metadata_{BASELINE_STAMP}.csv"
fieldnames = list(selected[0].keys())

with open(metadata_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(selected)

print(f"Wrote {metadata_file}")
print(f"Generated {len(selected)} baseline automata with exactly {TARGET_REACHABLE} reachable states.")
PYEOF

python3 generate_baseline_random.py

echo "Generated baseline reachable GAP files:"
ls baseline_random_*_${BASELINE_STAMP}_reachable.g

# 2. Test GAP

cat > test_sgpdec_baseline_load.g <<EOF
LoadPackage("semigroups");
LoadPackage("SgpDec");
Print("SgpDec baseline load test complete\\n");
QUIT;
EOF

"$GAPCMD" -q -A test_sgpdec_baseline_load.g > test_sgpdec_baseline_load.out 2> test_sgpdec_baseline_load.err || {
  echo "ERROR: GAP/SgpDec load test failed"
  cat test_sgpdec_baseline_load.err
  exit 1
}

cat test_sgpdec_baseline_load.out

# 3. Run GAP on generated baseline automata

shopt -s nullglob
gfiles=(baseline_random_[0-9]*_${BASELINE_STAMP}_reachable.g)

if [ ${#gfiles[@]} -eq 0 ]; then
  echo "ERROR: No baseline reachable .g files were generated."
  exit 1
fi

for gfile in "${gfiles[@]}"; do
  id=$(basename "$gfile" | sed -E "s/baseline_random_([0-9]+)_${BASELINE_STAMP}_reachable\.g/\1/")

  wrapper="gap_wrapper_baseline_${id}_${BASELINE_STAMP}.g"
  output="gap_output_baseline_${id}_${BASELINE_STAMP}.txt"
  error="gap_error_baseline_${id}_${BASELINE_STAMP}.txt"

  echo "===== Running GAP baseline $id ====="
  echo "Using file: $gfile"
  date

  cat > "$wrapper" <<EOF
Read("$gfile");
QUIT;
EOF

  "$GAPCMD" -q -A "$wrapper" > "$output" 2> "$error"

  echo "===== Finished GAP baseline $id ====="
  date
done

# 4. Combine and parse results

COMBINED="gap_output_baseline_${BASELINE_STAMP}.txt"
CLEANED="gap_output_baseline_${BASELINE_STAMP}_cleaned.txt"

cat gap_output_baseline_[0-9]*_${BASELINE_STAMP}.txt > "$COMBINED"
sed -r 's/\x1b\[[0-9;]*[mK]//g' "$COMBINED" > "$CLEANED" || cp "$COMBINED" "$CLEANED"

cat > parse_baseline_gap.py <<'PYEOF'
import re
import csv
import subprocess

BASELINE_STAMP = "baseline_20260612180910"
metadata_file = f"baseline_random_metadata_{BASELINE_STAMP}.csv"

metadata = {}
with open(metadata_file, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        metadata[int(row["Baseline ID"])] = row

rows = []

for baseline_id in sorted(metadata.keys()):
    fname = f"gap_output_baseline_{baseline_id}_{BASELINE_STAMP}.txt"

    with open(fname, "r", errors="replace") as f:
        block = f.read()

    block = re.sub(r"\\\s*\n", "", block)

    reachable_match = re.search(r"number of reachable states:\s*(\d+)", block, re.I)
    complexity_match = re.search(r"complexity upper bound:\s*(\d+)", block, re.I)
    aperiodic_match = re.search(r"non-aperiodic:\s*(\d+)", block, re.I)

    reachable = int(reachable_match.group(1)) if reachable_match else ""
    complexity = int(complexity_match.group(1)) if complexity_match else ""
    non_aperiodic = int(aperiodic_match.group(1)) if aperiodic_match else ""
    aperiodic = "Yes" if non_aperiodic == 0 else ("No" if non_aperiodic != "" else "")

    chain_match = re.search(
        r"Max Chain of Essential Dependencies:\s*Maximum Chain Found:\s*(.*?)(?:\n\s*\n|\Z)",
        block,
        re.I | re.S,
    )

    if not chain_match:
        chain_match = re.search(
            r"Maximum Chain Found:\s*(.*?)(?:\n\s*\n|\Z)",
            block,
            re.I | re.S,
        )

    if chain_match:
        chain_text = chain_match.group(1).replace("\n", " ").strip()
        chain_length = 0 if aperiodic == "Yes" else (chain_text.count("->") + 1 if chain_text else 0)
    else:
        chain_text = "NO MAX CHAIN MATCH FOUND"
        chain_length = ""

    m = metadata[baseline_id]

    rows.append({
        "Baseline ID": baseline_id,
        "Random Seed": m["Random Seed"],
        "Fitness": m["Fitness"],
        "Number of States": m["Number of States"],
        "Reachable States": reachable,
        "Complexity Upper Bound": complexity,
        "Max Chain Lower Bound": chain_length,
        "Aperiodic": aperiodic,
        "Chain Text": chain_text,
    })

csv_file = f"baseline_summary_{BASELINE_STAMP}.csv"

with open(csv_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print(f"Wrote {csv_file}")

try:
    import pandas as pd
    xlsx_file = f"baseline_summary_{BASELINE_STAMP}.xlsx"
    pd.DataFrame(rows).to_excel(xlsx_file, index=False)
    print(f"Wrote {xlsx_file}")
except Exception as e:
    print(f"Could not write XLSX: {e}")

tex_file = f"baseline_gap_report_{BASELINE_STAMP}.tex"
combined_file = f"gap_output_baseline_{BASELINE_STAMP}_cleaned.txt"

with open(combined_file, "r", errors="replace") as f:
    gap_content = f.read()

summary_lines = []
for r in rows:
    summary_lines.append(
        f"{r['Baseline ID']} & {r['Random Seed']} & {r['Fitness']} & {r['Reachable States']} & {r['Complexity Upper Bound']} & {r['Max Chain Lower Bound']} & {r['Aperiodic']} \\\\"
    )

with open(tex_file, "w") as f:
    f.write(r"""\documentclass{article}
\usepackage{geometry}
\geometry{margin=1in}
\usepackage{longtable}
\usepackage{verbatim}
\begin{document}
\title{Random Baseline GAP Analysis Report}
\maketitle

\section*{Baseline Setup}
Pure random sampling up to 100,000 candidates did not yield enough automata with exactly 9 reachable states. This report uses constrained random automata with exactly 9 reachable states, generated using 15 states, MultiTraversal fitness, SimpleHardestEnvironment, input alphabet 1--8, output alphabet 0--1.

The generator fixes initial state 0, forces a Hamiltonian path $0 \to 1 \to \cdots \to 8$, and keeps transitions from these states within this set. This guarantees exactly 9 reachable states but does not sample uniformly from all 15-state automata with 9 reachable states. Reachable subautomata without a Hamiltonian path starting at the initial state cannot be generated, and the fixed labels and forced path further constrain the sample.

\section*{Summary Table}
\begin{longtable}{r|r|r|r|r|r|r}
ID & Seed & Fitness & Reachable & Upper Bound & Lower Bound & Aperiodic \\
\hline
""")
    f.write("\n".join(summary_lines))
    f.write(r"""
\end{longtable}

\newpage
\section*{Collected GAP Output}
\begin{verbatim}
""")
    f.write(gap_content)
    f.write(r"""
\end{verbatim}
\end{document}
""")

print(f"Wrote {tex_file}")

try:
    subprocess.run(["pdflatex", "-interaction=nonstopmode", tex_file], check=False, stdout=subprocess.DEVNULL)
    print(f"Tried compiling {tex_file}")
except Exception as e:
    print(f"Could not run pdflatex: {e}")
PYEOF

python3 parse_baseline_gap.py

# 5. Package outputs

OUTDIR="baseline_random_gap_${BASELINE_STAMP}"

rm -rf "$OUTDIR"
mkdir "$OUTDIR"

cp baseline_random_*_${BASELINE_STAMP}*.g "$OUTDIR"/
cp gap_wrapper_baseline_*_${BASELINE_STAMP}.g "$OUTDIR"/
cp gap_output_baseline_*_${BASELINE_STAMP}.txt "$OUTDIR"/
cp gap_error_baseline_*_${BASELINE_STAMP}.txt "$OUTDIR"/ 2>/dev/null || true
cp gap_output_baseline_${BASELINE_STAMP}.txt "$OUTDIR"/
cp gap_output_baseline_${BASELINE_STAMP}_cleaned.txt "$OUTDIR"/
cp baseline_random_metadata_${BASELINE_STAMP}.csv "$OUTDIR"/
cp baseline_summary_${BASELINE_STAMP}.csv "$OUTDIR"/
cp baseline_summary_${BASELINE_STAMP}.xlsx "$OUTDIR"/ 2>/dev/null || true
cp baseline_gap_report_${BASELINE_STAMP}.tex "$OUTDIR"/
cp baseline_gap_report_${BASELINE_STAMP}.pdf "$OUTDIR"/ 2>/dev/null || true
cp test_sgpdec_baseline_load.out test_sgpdec_baseline_load.err "$OUTDIR"/ 2>/dev/null || true

tar -czvf baseline_random_gap_${BASELINE_STAMP}.tar.gz "$OUTDIR"

echo "===== DONE BASELINE ====="
echo "Created package: baseline_random_gap_${BASELINE_STAMP}.tar.gz"
date
