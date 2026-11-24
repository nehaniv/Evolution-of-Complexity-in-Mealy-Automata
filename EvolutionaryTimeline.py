#!/usr/bin/env python3
"""
Track how Mealy automata and their complexity change during evolution.

What gets saved:
- The best automaton at selected generations.
- An extra checkpoint when the best automaton's reachable-state count changes.
- The first automaton that achieves perfect traversal from every start.
- Both the complete automaton and its reachable part.
- Fitness and reachable-state counts for every generation.
- Checkpoints that let you continue an interrupted experiment.

Scheduled saves:
Generations 0, 1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000,
then every 5000 generations through 100000.
The final generation is always saved.
Generation 0 means the initial population, before evolution starts.

After all runs finish:
GAP analyzes the saved automata to calculate complexity bounds,
holonomy and representative permutator groups, and their separate
numbers of non-solvable group occurrences.
Results are saved in experiment_results.xlsx, with CSV files and plots.
Complexity is reported as a range unless the lower and upper bounds agree.

Sample start:
python3 -u EvolutionaryTimeline.py \
  --runs 1 \
  --generations 10 \
  --output results/timeline_test
"""

from __future__ import annotations
import argparse
import copy
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

SCHEMA = 2
METRICS = ['run', 'generation', 'best_fitness', 'mean_fitness',
           'best_reachable_states', 'mean_reachable_states', 'unpenalized_performance', 'state_cost', 'perfect_traversal']
DEFAULT_RECORD = sorted(set([0, 1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000] + list(range(5000, 100001, 5000))))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w') as f:
        json.dump(data, f, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def read_json(path):
    return json.loads(Path(path).read_text())


def save_csv(path, rows, fields=None):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields or list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def encode_automaton(a):
    return dict(num_states=a.num_states, input_alphabet=list(a.input_alphabet),
                output_alphabet=list(a.output_alphabet), initial_state=a.initial_state,
                transitions=[[s, i, a.transitions[s, i]] for s in range(a.num_states)
                             for i in a.input_alphabet],
                outputs=[[s, i, a.outputs[s, i]] for s in range(a.num_states)
                         for i in a.input_alphabet])


def decode_automaton(d, cls):
    # No constructor call: restoring must not consume random numbers.
    a = cls.__new__(cls)
    for key in ('num_states', 'input_alphabet', 'output_alphabet', 'initial_state'):
        setattr(a, key, copy.deepcopy(d[key]))
    a.transitions = {(s, i): t for s, i, t in d['transitions']}
    a.outputs = {(s, i): o for s, i, o in d['outputs']}
    return a


def rng_state():
    n = np.random.get_state()
    return {'python': random.getstate(),
            'numpy': [n[0], n[1].tolist(), n[2], n[3], n[4]]}


def restore_rng(d):
    def tuples(x):
        return tuple(tuples(v) for v in x) if isinstance(x, list) else x
    random.setstate(tuples(d['python']))
    n = d['numpy']
    np.random.set_state((n[0], np.array(n[1], dtype=np.uint32), n[2], n[3], n[4]))


def load_core(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f'Original Python file not found: {path}')
    if 'URA_EVOLUTION_SEED' in path.read_text():
        raise ValueError('Use the original ES-Automata-Fogel.py, not the Nibi patched copy.')
    # Support sibling imports without executing the original __main__ block.
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('mealy_original', path)
    core = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = core
    spec.loader.exec_module(core)
    return core


class FitnessEvaluator:
    """Observe every evaluated parent/offspring without changing selection."""
    def __init__(self, core, cfg):
        self.core, self.cfg = core, cfg
        self.env = core.EnvironmentDFA(8, ['0', '1'], variant=cfg['env_variant'])
        self.pending = None
        self.first_perfect = None

    def evaluate(self, a):
        name = self.cfg['fitness']
        if name == 'MultiTraversal':
            score, details = self.core.multitraversal_fitness(a, self.env)
            counts = [int(r['run_fitness']) for r in details['per_start']]
        elif name == 'Traversal':
            score, details = self.core.traversal_fitness(a, self.env)
            counts = [len({pair for pair, _ in details if pair[1] in self.env.input_alphabet})]
        else:
            seq = ('00011000' * 12)[:84] if name == 'EightBall' else '101110011101' * 10
            fn = self.core.eightball_fitness if name == 'EightBall' else self.core.fogel_palindrome_fitness
            return fn(a, seq)[0], None
        target = self.env.num_states * len(self.env.input_alphabet)
        expected_starts = self.env.num_states if name == 'MultiTraversal' else 1
        coverage = dict(raw_traversal_score=sum(counts), transitions_per_start=counts,
                        target_per_start=target, expected_start_count=expected_starts,
                        perfect_traversal=len(counts) == expected_starts and all(c == target for c in counts))
        return score, coverage

    def __call__(self, a):
        score, coverage = self.evaluate(a)
        if self.first_perfect is None and coverage and coverage['perfect_traversal']:
            if self.pending is None or score > self.pending['fitness']:
                self.pending = dict(automaton=copy.deepcopy(a), fitness=float(score), coverage=coverage)
        return score


def make_fitness(core, cfg):
    return FitnessEvaluator(core, cfg)


def select_generation(pop, offspring_size, fitness):
    # Same reproduction, mutation and offspring-priority tie break as original.
    offspring = [random.choice(pop).clone() for _ in range(offspring_size)]
    for a in offspring:
        a.mutate()
    combined = [(a, 0) for a in pop] + [(a, 1) for a in offspring]
    scores = [fitness(a) for a, _ in combined]
    ranked = sorted(zip(scores, combined), key=lambda pair: (pair[0], pair[1][1]), reverse=True)
    return [a for _, (a, _) in ranked[:len(pop)]]


def summarize_population(pop, fitness, run, generation):
    scores = [fitness(a) for a in pop]
    idx = max(range(len(scores)), key=lambda i: scores[i])
    best = pop[idx]
    row = dict(run=run, generation=generation, best_fitness=float(scores[idx]),
               mean_fitness=float(np.mean(scores)),
               best_reachable_states=len(best.get_reachable_states()),
               mean_reachable_states=float(np.mean([len(a.get_reachable_states()) for a in pop])))
    score, coverage = fitness.evaluate(best)
    raw = coverage['raw_traversal_score'] if coverage else score + len(best.get_reachable_states())
    row.update(unpenalized_performance=raw, state_cost=float(raw-score),
               perfect_traversal=coverage['perfect_traversal'] if coverage else '')
    return best, row


def write_checkpoint(out, cfg, base, pop, run, gen, milestone=False, first_perfect=None):
    state = dict(schema=SCHEMA, config_sha=hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest(),
                 run=run, generation=gen, initial_population=base,
                 population=[encode_automaton(a) for a in pop], rng=rng_state(), first_perfect=first_perfect)
    if milestone:
        atomic_json(out / 'checkpoints' / f'run_{run:03d}' / f'gen_{gen:06d}.json', state)
    atomic_json(out / 'checkpoint.json', state)


def save_snapshot(out, cfg, best, row, kind="population_best", coverage=None, reasons=None):
    run, gen = row['run'], row['generation']
    d = dict(row, init_seed=cfg['init_seed'], evolution_seed=cfg['seed_base'] + run - 1,
             automaton=encode_automaton(best), snapshot_kind=kind, coverage=coverage, reasons=reasons or [])
    reachable = set(best.get_reachable_states())
    d["reachable_automaton"] = dict(states=sorted(reachable), initial_state=best.initial_state,
        input_alphabet=best.input_alphabet, output_alphabet=best.output_alphabet,
        transitions=[v for v in d["automaton"]["transitions"] if v[0] in reachable],
        outputs=[v for v in d["automaton"]["outputs"] if v[0] in reachable])
    suffix = '_first_perfect' if kind == 'first_perfect_witness' else ''
    path = out / 'snapshots' / f'run_{run:03d}' / f'gen_{gen:06d}{suffix}.json'
    atomic_json(path, d)
    # Source graph is portable; rendering it is optional and done after evolution.
    best.to_dot(reachable_only=True).save(filename=str(path.with_suffix('.dot')))
    best.to_dot(reachable_only=False).save(filename=str(path.with_suffix('.complete.dot')))


def record_first_perfect(out, cfg, fitness, row):
    if fitness.first_perfect is not None or fitness.pending is None:
        return False
    witness = fitness.pending
    witness_row = dict(row, best_fitness=witness['fitness'],
                       best_reachable_states=len(witness['automaton'].get_reachable_states()),
                       unpenalized_performance=witness['coverage']['raw_traversal_score'],
                       state_cost=witness['coverage']['raw_traversal_score']-witness['fitness'], perfect_traversal=True)
    save_snapshot(out, cfg, witness['automaton'], witness_row,
                  kind='first_perfect_witness', coverage=witness['coverage'], reasons=['first_perfect_all_start_traversal'])
    fitness.first_perfect = dict(run=row['run'], generation=row['generation'],
                                fitness=witness['fitness'], coverage=witness['coverage'])
    atomic_json(out / 'events' / f'run_{row["run"]:03d}_first_perfect.json', fitness.first_perfect)
    print(f'  FIRST PERFECT TRAVERSAL: run {row["run"]}, generation {row["generation"]}, '
          f'raw={witness["coverage"]["raw_traversal_score"]}, fitness={witness["fitness"]}', flush=True)
    return True


def evolve(out, cfg, core, resume=False):
    fitness = make_fitness(core, cfg)
    if resume:
        state = read_json(out / 'checkpoint.json')
        h = hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()
        if state['schema'] != SCHEMA or state['config_sha'] != h:
            raise ValueError('Checkpoint does not match experiment configuration.')
        base = state['initial_population']
        first_run, first_gen = state['run'], state['generation']
        restored = [decode_automaton(d, core.MealyAutomaton) for d in state['population']]
        restore_rng(state['rng'])
    else:
        random.seed(cfg['init_seed'])
        np.random.seed(cfg['init_seed'])
        inputs = [str(i) for i in range(1, 9)] if cfg['fitness'] in ('Traversal', 'MultiTraversal') else ['0', '1']
        initial = [core.MealyAutomaton(cfg['num_states'], inputs, ['0', '1'],
                   self_loop_init=cfg['self_loop_init']) for _ in range(cfg['population_size'])]
        base = [encode_automaton(a) for a in initial]
        atomic_json(out / 'initial_population.json', base)
        first_run, first_gen = 1, 0
    (out / 'metrics').mkdir(exist_ok=True)
    records = set(cfg['record_generations'])
    for run in range(first_run, cfg['runs'] + 1):
        continuing = resume and run == first_run
        if continuing:
            pop, start = restored, first_gen
        else:
            random.seed(cfg['seed_base'] + run - 1)
            np.random.seed(cfg['seed_base'] + run - 1)
            pop = [decode_automaton(d, core.MealyAutomaton) for d in base]
            start = 0
        fitness.pending = None
        fitness.first_perfect = state.get('first_perfect') if continuing else None
        path = out / 'metrics' / f'run_{run:03d}.csv'
        if continuing:
            temp = path.with_suffix('.resume.tmp')
            last_generation, previous_n = -1, None
            with path.open(newline='') as src, temp.open('w', newline='') as dst:
                writer = csv.DictWriter(dst, fieldnames=METRICS)
                writer.writeheader()
                for metric in csv.DictReader(src):
                    gen = int(metric['generation'])
                    if gen > start:
                        break
                    if gen != last_generation + 1:
                        raise ValueError(f'Metrics gap before resume: {path}')
                    writer.writerow(metric)
                    last_generation = gen
                    previous_n = int(metric['best_reachable_states'])
            if last_generation != start:
                raise ValueError(f'Metrics missing before resume: {path}')
            temp.replace(path)
        else:
            best, row = summarize_population(pop, fitness, run, 0)
            save_csv(path, [row], METRICS)
            save_snapshot(out, cfg, best, row, reasons=['initial', 'scheduled'])
            previous_n = row['best_reachable_states']
            record_first_perfect(out, cfg, fitness, row)
            write_checkpoint(out, cfg, base, pop, run, 0, milestone=True, first_perfect=fitness.first_perfect)
        print(f'Run {run}/{cfg["runs"]}, starting at generation {start}', flush=True)
        with path.open('a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=METRICS)
            for gen in range(start + 1, cfg['generations'] + 1):
                fitness.pending = None
                pop = select_generation(pop, cfg['offspring_size'], fitness)
                best, row = summarize_population(pop, fitness, run, gen)
                writer.writerow(row)
                event = record_first_perfect(out, cfg, fitness, row)
                changed = row['best_reachable_states'] != previous_n
                reasons = (['scheduled'] if gen in records else []) + (['first_perfect_all_start_traversal'] if event else []) + (['reachable_state_count_changed'] if changed else [])
                if gen == cfg['generations']:
                    reasons.append('final')
                if reasons:
                    save_snapshot(out, cfg, best, row, reasons=reasons)
                previous_n = row['best_reachable_states']
                if reasons or gen % cfg['checkpoint_every'] == 0:
                    f.flush()
                    os.fsync(f.fileno())
                    write_checkpoint(out, cfg, base, pop, run, gen, milestone=bool(reasons), first_perfect=fitness.first_perfect)
                if gen in records or gen % cfg['progress_every'] == 0:
                    print(f'  generation {gen}: fitness={row["best_fitness"]:g}, '
                          f'reachable={row["best_reachable_states"]}', flush=True)
    event_rows = []
    for rr in range(1, cfg['runs'] + 1):
        ep = out / 'events' / f'run_{rr:03d}_first_perfect.json'
        ev = read_json(ep) if ep.exists() else None
        event_rows.append(dict(run=rr, first_perfect_generation=ev['generation'] if ev else '',
                               first_perfect_fitness=ev['fitness'] if ev else '',
                               status='found' if ev else 'not_observed'))
    save_csv(out / 'first_perfect_traversal.csv', event_rows)
    atomic_json(out / 'evolution_complete.json', {'runs': cfg['runs'], 'generations': cfg['generations']})


def normalize_gap(text):
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    text = re.sub(r'\\\r?\n[ \t]*', '', text)
    return re.sub(r'(?m)^(?:[ \t]*(?:gap>|>)[ \t]*)+', '', text)


GAP_HEADER = '''SizeScreen([4096, 100000]);;
if LoadPackage("SgpDec") <> true then QUIT_GAP(1); fi;
if not IsBound(InfoEssentialDependency) or not IsBound(MaxChainOfEssentialDependencyWithProgress) then
  Print("Updated SgpDec branch is required\\n"); QUIT_GAP(1);
fi;
SetInfoLevel(InfoEssentialDependency, 2);
'''


def gap_run(executable, script, logfile, timeout):
    with Path(logfile).open('w') as f:
        p = subprocess.run([executable, '-q', '-b', str(script)], stdout=f,
                           stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=timeout or None)
    text = normalize_gap(Path(logfile).read_text(errors='replace'))
    if p.returncode or re.search(r'(?m)^\s*(?:Error,|Error:|Syntax error:)', text):
        raise RuntimeError(f'GAP failed; inspect {logfile}')
    return text


def require_line(text, name):
    hits = re.findall(r'^' + re.escape(name) + r':(.*)$', text, re.M)
    if len(hits) != 1:
        raise ValueError(f'Expected exactly one {name} marker, got {len(hits)}')
    return hits[0].strip()


def software_probe(out, executable):
    executable = shutil.which(executable)
    if not executable:
        raise FileNotFoundError('GAP not found. Activate your usual environment or pass --gap /path/to/gap.')
    code = GAP_HEADER + '''Print("URA_GAP_VERSION:", GAPInfo.Version, "\\n");
Print("URA_SEMIGROUPS_VERSION:", PackageInfo("Semigroups")[1].Version, "\\n");
Print("URA_SGPDEC_PATH:", PackageInfo("SgpDec")[1].InstallationPath, "\\n");
Print("URA_SOFTWARE_DONE\\n");
QUIT_GAP(0);
'''
    out.mkdir(parents=True, exist_ok=True)
    script = out / 'software_check.g'
    script.write_text(code)
    text = gap_run(executable, script, out / 'software_check.log', 180)
    if 'URA_SOFTWARE_DONE' not in text.splitlines():
        raise ValueError('GAP software check did not complete; see software_check.log')
    data = {k: require_line(text, marker) for k, marker in
            [('gap_version', 'URA_GAP_VERSION'), ('semigroups_version', 'URA_SEMIGROUPS_VERSION'),
             ('sgpdec_path', 'URA_SGPDEC_PATH')]}
    def git(*args):
        return subprocess.check_output(['git', '-C', data['sgpdec_path'], *args], text=True).strip()
    # SHA and modifications are required, not guessed from the package version.
    data['sgpdec_sha'] = git('rev-parse', 'HEAD')
    data['sgpdec_branch'] = git('branch', '--show-current')
    data['sgpdec_status'] = git('status', '--porcelain')
    patch = git('diff', 'HEAD')
    (out / 'sgpdec_changes.patch').write_text(patch + '\n')
    untracked = git('ls-files', '--others', '--exclude-standard').splitlines()
    data['untracked_sha256'] = {p: digest(Path(data['sgpdec_path']) / p) for p in untracked
                                if (Path(data['sgpdec_path']) / p).is_file()}
    data['sgpdec_diff_sha256'] = hashlib.sha256(patch.encode()).hexdigest()
    data['gap_executable'] = executable
    atomic_json(out / 'software.json', data)
    return data


def gap_program(snapshot):
    a = snapshot['automaton']
    edges = {(s, i): t for s, i, t in a['transitions']}
    reachable, todo = set(), [a['initial_state']]
    while todo:
        s = todo.pop()
        if s not in reachable:
            reachable.add(s)
            todo.extend(edges[s, i] for i in a['input_alphabet'])
    states = sorted(reachable)
    mapping = {s: j + 1 for j, s in enumerate(states)}
    if len(states) != snapshot['best_reachable_states']:
        raise ValueError('Snapshot reachable-state count is inconsistent')
    gens = ['Transformation([' + ','.join(str(mapping[edges[s, i]]) for s in states) + '])'
            for i in a['input_alphabet']]
    code = GAP_HEADER + f'URA_N := {len(states)};;\n'
    if len(states) == 1:
        code += 'URA_HOLO := 0;; URA_LB := 0;; URA_DEPTH := 0;; URA_GROUP_COUNT := 0;;\n'
    else:
        code += 'URA_S := Semigroup([' + ','.join(gens) + ']);;\n'
        code += '''URA_SK := Skeleton(URA_S);;
URA_HOLO := 0;;
URA_DEPTH := Maximum(0, DepthOfSkeleton(URA_SK)-1);;
URA_GROUP_COUNT := 0;;
if URA_DEPTH > 0 then
  for URA_D in [1..URA_DEPTH] do
    URA_NONTRIVIAL := false;
    URA_REP := 0;
    for URA_X in RepresentativeSets(URA_SK)[URA_D] do
      URA_REP := URA_REP + 1;
      URA_H := HolonomyGroup@SgpDec(URA_SK, URA_X);
      URA_GROUP_COUNT := URA_GROUP_COUNT + 1;
      Print("URA_GROUP:", URA_D, "|", URA_REP, "|", String(URA_X), "|",
            Size(URA_H), "|", StructureDescription(URA_H), "|",
            String(GeneratorsOfGroup(URA_H)), "|", IsSolvableGroup(URA_H), "\\n");
      if not IsTrivial(URA_H) then URA_NONTRIVIAL := true; fi;
    od;
    if URA_NONTRIVIAL then URA_HOLO := URA_HOLO + 1; fi;
  od;
fi;
DisplayHolonomyComponents(URA_SK);
URA_LB := MaxChainOfEssentialDependency(URA_SK);;
'''
    code += '''Print("URA_N:", URA_N, "\\n");
Print("URA_HOLO:", URA_HOLO, "\\n");
Print("URA_DEPTH:", URA_DEPTH, "\\n");
Print("URA_GROUP_COUNT:", URA_GROUP_COUNT, "\\n");
Print("URA_LB:", URA_LB, "\\n");
Print("URA_DONE\\n");
QUIT_GAP(0);
'''
    return code


def parse_bounds(text, n):
    if text.splitlines().count('URA_DONE') != 1:
        raise ValueError('Missing exact GAP completion marker')
    if re.search(r'(?m)^\s*(?:Error,|Error:|Syntax error:)', text):
        raise ValueError('GAP error present')
    reported_n = int(require_line(text, 'URA_N'))
    holo, lower = int(require_line(text, 'URA_HOLO')), int(require_line(text, 'URA_LB'))
    upper = min(holo, n - 1)
    if reported_n != n or not 0 <= lower <= upper:
        raise ValueError(f'Inconsistent GAP bounds: n={reported_n}, lower={lower}, holonomy={holo}')
    return dict(complexity_lower=lower, holonomy_upper=holo, complexity_upper=upper,
                exact_complexity=lower if lower == upper else '', state_ceiling=n - 1,
                gap_to_ceiling_min=n - 1 - upper, gap_to_ceiling_max=n - 1 - lower,
                normalized_lower=lower / (n - 1) if n > 1 else '',
                normalized_upper=upper / (n - 1) if n > 1 else '')


def group_records(text, marker):
    records, pending = [], None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(marker):
            if pending is not None:
                raise ValueError('Unfinished group record before next group')
            pending = line[len(marker):]
        elif pending is not None:
            if line.startswith(('URA_', '#I', 'Error', 'Syntax error')) or re.match(r'^\d+:', line):
                raise ValueError('Unfinished group record before other output')
            pending += ' ' + line
        else:
            continue
        if re.search(r'\|\s*(?:true|false)\s*$', pending):
            records.append(pending)
            pending = None
    if pending is not None:
        raise ValueError('Unfinished group record at end of log')
    return records


def parse_groups(text, holonomy_number):
    # GAP can insert both backslash continuations and ordinary pretty-print
    # newlines inside one Print call. The final boolean terminates a record.
    text = normalize_gap(text)
    depth = int(require_line(text, 'URA_DEPTH'))
    expected = int(require_line(text, 'URA_GROUP_COUNT'))
    groups = []
    identities = set()
    records = group_records(text, "URA_GROUP:")
    for record in records:
        fields = record.split('|')
        if len(fields) != 7:
            raise ValueError('Malformed holonomy group record')
        level, rep, representative, order, structure, generators, solvable = [v.strip() for v in fields]
        if solvable not in ("true", "false"):
            raise ValueError("Missing group solvability")
        level, rep, order = int(level), int(rep), int(order)
        if not (representative.startswith('[') and representative.endswith(']')
                and generators.startswith('[') and generators.endswith(']') and structure):
            raise ValueError('Malformed holonomy group field')
        if not 1 <= level <= depth or rep < 1 or order < 1 or (level, rep) in identities:
            raise ValueError('Invalid or duplicate holonomy group record')
        identities.add((level, rep))
        groups.append(dict(level=level, representative_index=rep, representative_set=representative,
                           order=order, structure=structure, generators=generators, trivial=order == 1, solvable=solvable == "true"))
    nontrivial_levels = {g['level'] for g in groups if not g['trivial']}
    if len(groups) != expected or len(nontrivial_levels) != holonomy_number or depth < 0:
        raise ValueError('Holonomy group inventory is incomplete/inconsistent')
    return groups, depth


def permutator_program(snapshot):
    """Separate inventory so existing, expensive bounds caches remain reusable.

    Reuse the exact reachable action and skeleton construction from gap_program,
    stopping before its holonomy inventory and lower-bound calculation.
    """
    code, marker, _ = gap_program(snapshot).partition('URA_SK := Skeleton(URA_S);;')
    if snapshot['best_reachable_states'] > 1:
        if not marker:
            raise ValueError('Missing reachable skeleton construction')
        code += '''URA_SK := Skeleton(URA_S);;
URA_DEPTH := Maximum(0, DepthOfSkeleton(URA_SK)-1);;
URA_GROUP_COUNT := 0;;
if URA_DEPTH > 0 then
  for URA_D in [1..URA_DEPTH] do
    URA_REP := 0;
    for URA_X in RepresentativeSets(URA_SK)[URA_D] do
      URA_REP := URA_REP + 1;
      URA_P := PermutatorGroup(URA_SK, URA_X);
      URA_DOMAIN := ListBlist([1..URA_N], URA_X);
      URA_GROUP_COUNT := URA_GROUP_COUNT + 1;
      Print("URA_PERMUTATOR:", URA_D, "|", URA_REP, "|", String(URA_X), "|",
            String(URA_DOMAIN), "|", Length(URA_DOMAIN), "|", Size(URA_P), "|",
            StructureDescription(URA_P), "|", String(GeneratorsOfGroup(URA_P)), "|",
            IsSolvableGroup(URA_P), "\\n");
    od;
  od;
fi;
'''
    else:
        # The one-state branch of gap_program already includes its completion
        # markers and QUIT; use only the header, with an empty inventory.
        code = GAP_HEADER + 'URA_N := 1;; URA_DEPTH := 0;; URA_GROUP_COUNT := 0;;\n'
    return code + '''Print("URA_N:", URA_N, "\\n");
Print("URA_DEPTH:", URA_DEPTH, "\\n");
Print("URA_GROUP_COUNT:", URA_GROUP_COUNT, "\\n");
Print("URA_PERMUTATORS_DONE\\n");
QUIT_GAP(0);
'''


def parse_permutators(text, n, holonomy_groups, depth):
    """Validate a complete inventory and pair it with the holonomy inventory."""
    text = normalize_gap(text)
    if re.search(r'(?m)^\s*(?:Error,|Error:|Syntax error:)', text):
        raise ValueError('GAP error present')
    if text.splitlines().count('URA_PERMUTATORS_DONE') != 1:
        raise ValueError('Missing exact permutator completion marker')
    if (int(require_line(text, 'URA_N')) != n or
            int(require_line(text, 'URA_DEPTH')) != depth):
        raise ValueError('Permutator action/skeleton does not match bounds analysis')
    expected = {(g['level'], g['representative_index']): g for g in holonomy_groups}
    groups, seen = [], set()
    for record in group_records(text, 'URA_PERMUTATOR:'):
        fields = [v.strip() for v in record.split('|')]
        if len(fields) != 9:
            raise ValueError('Malformed permutator group record')
        level, rep, representative, domain, degree, order, structure, generators, solvable = fields
        level, rep, degree, order = int(level), int(rep), int(degree), int(order)
        key = (level, rep)
        h = expected.get(key)
        if key in seen or h is None or order < 1 or solvable not in ('true', 'false'):
            raise ValueError('Invalid or duplicate permutator group record')
        # Both generators and domain use GAP's 1-based reachable-state labels.
        points = json.loads(domain)
        if (not isinstance(points, list) or any(type(p) is not int for p in points) or
                len(points) != degree or degree < 2 or
                points != sorted(set(points)) or not all(1 <= p <= n for p in points)):
            raise ValueError('Invalid permutator action domain')
        if re.sub(r'\s+', '', representative) != re.sub(r'\s+', '', h['representative_set']):
            raise ValueError('Permutator and holonomy representatives differ')
        if order % h['order'] or (solvable == 'true' and not h['solvable']):
            raise ValueError('Holonomy group is inconsistent with its permutator quotient')
        seen.add(key)
        groups.append(dict(level=level, representative_index=rep, representative_set=representative,
                           domain=domain, degree=degree, order=order, structure=structure,
                           generators=generators, trivial=order == 1, solvable=solvable == 'true'))
    if seen != set(expected) or int(require_line(text, 'URA_GROUP_COUNT')) != len(groups):
        raise ValueError('Permutator group inventory is incomplete/inconsistent')
    return groups


def record_permutators(snapshot, snapshot_path, stem, software, software_key, bounds, timeout):
    """Cache independently of bounds; retry only missing/failed inventories."""
    code = permutator_program(snapshot)
    key = hashlib.sha256((digest(snapshot_path) + code + software_key).encode()).hexdigest()
    resultfile = stem.with_suffix('.permutators.result.json')
    cached = read_json(resultfile) if resultfile.exists() else None
    if cached and cached.get('cache_key') == key and cached['row']['permutator_status'] == 'completed':
        return cached['row']
    row = dict(permutator_status='failed', permutator_error='', permutator_groups='',
               non_solvable_permutator_occurrences='')
    stem.with_suffix('.permutators.g').write_text(code)
    try:
        text = gap_run(software['gap_executable'], stem.with_suffix('.permutators.g'),
                       stem.with_suffix('.permutators.log'), timeout)
        groups = parse_permutators(text, snapshot['best_reachable_states'],
                                   json.loads(bounds['holonomy_groups']), bounds['holonomy_depth'])
        row.update(permutator_status='completed', permutator_groups=json.dumps(groups),
                   non_solvable_permutator_occurrences=sum(not g['solvable'] for g in groups))
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
        row['permutator_error'] = str(e)
        print(f'  PERMUTATORS FAILED: {e}', flush=True)
    atomic_json(resultfile, {'cache_key': key, 'row': row})
    return row


def snapshots_for(out, cfg):
    paths = [out / 'snapshots' / f'run_{r:03d}' / f'gen_{g:06d}.json'
             for r in range(1, cfg['runs'] + 1) for g in cfg['record_generations']]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise ValueError(f'{len(missing)} snapshots missing; first: {missing[0]}')
    return sorted((out / 'snapshots').glob('run_*/gen_*.json'))


def analyze(out, cfg, software, timeout, render):
    if not (out / 'evolution_complete.json').exists():
        raise ValueError('Evolution has not finished; use --resume first.')
    paths = snapshots_for(out, cfg)
    rows, failed = [], 0
    software_key = hashlib.sha256(json.dumps(software, sort_keys=True).encode()).hexdigest()
    for idx, path in enumerate(paths, 1):
        snap = read_json(path)
        run, gen = snap['run'], snap['generation']
        dest = out / 'gap' / f'run_{run:03d}'
        dest.mkdir(parents=True, exist_ok=True)
        stem = dest / path.stem
        code = gap_program(snap)
        key = hashlib.sha256((digest(path) + code + software_key).encode()).hexdigest()
        resultfile = stem.with_suffix('.result.json')
        base = {k: snap[k] for k in METRICS + ['init_seed', 'evolution_seed']}
        base.update(snapshot_kind=snap.get('snapshot_kind', 'population_best'), checkpoint_reasons=';'.join(snap.get('reasons', [])), holonomy_number='', holonomy_depth='', non_solvable_group_occurrences='', holonomy_groups='', status='failed', complexity_lower='', holonomy_upper='', complexity_upper='',
                    exact_complexity='', state_ceiling=snap['best_reachable_states'] - 1,
                    gap_to_ceiling_min='', gap_to_ceiling_max='', normalized_lower='', normalized_upper='',
                    error='', snapshot=str(path.relative_to(out)), gap_log=str(stem.with_suffix('.log').relative_to(out)))
        print(f'GAP {idx}/{len(paths)}: run {run}, generation {gen}', flush=True)
        cached = read_json(resultfile) if resultfile.exists() else None
        if cached and cached.get('cache_key') == key and cached['row']['status'] == 'completed':
            row = cached['row']
        else:
            row = base
            stem.with_suffix('.g').write_text(code)
            try:
                text = gap_run(software['gap_executable'], stem.with_suffix('.g'), stem.with_suffix('.log'), timeout)
                row.update(parse_bounds(text, snap['best_reachable_states']), status='completed')
                groups, depth = parse_groups(text, row['holonomy_upper'])
                row.update(holonomy_number=row['holonomy_upper'], holonomy_depth=depth,
                           non_solvable_group_occurrences=sum(not g['solvable'] for g in groups), holonomy_groups=json.dumps(groups))
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as e:
                row['status'] = 'failed'
                row['error'] = str(e)
                print(f'  FAILED: {e}', flush=True)
            atomic_json(resultfile, {'cache_key': key, 'row': row})
        # Keep the original bounds cache/key intact, including on backfill.
        row = dict(row, permutator_status='pending', permutator_error='', permutator_groups='',
                   non_solvable_permutator_occurrences='',
                   permutator_log=str(stem.with_suffix('.permutators.log').relative_to(out)))
        if row['status'] == 'completed':
            row.update(record_permutators(snap, path, stem, software, software_key, row, timeout))
        if row['status'] != 'completed' or row['permutator_status'] != 'completed':
            failed += 1
        rows.append(row)
        save_csv(out / 'timeline.csv', rows)
        if render and shutil.which('dot'):
            subprocess.run(['dot', '-Tpdf', str(path.with_suffix('.dot')), '-o', str(path.with_suffix('.pdf'))], check=True)
    group_rows = []
    for row in rows:
        if row['status'] == 'completed':
            for group in json.loads(row['holonomy_groups']):
                group_rows.append(dict(run=row['run'], generation=row['generation'], snapshot_kind=row['snapshot_kind'], **group))
    save_csv(out / 'holonomy_groups.csv', group_rows, ['run', 'generation', 'snapshot_kind', 'level', 'representative_index', 'representative_set', 'order', 'structure', 'generators', 'trivial', 'solvable'])
    permutator_rows = []
    for row in rows:
        if row['permutator_status'] == 'completed':
            for group in json.loads(row['permutator_groups']):
                permutator_rows.append(dict(run=row['run'], generation=row['generation'], snapshot_kind=row['snapshot_kind'], **group))
    save_csv(out / 'permutator_groups.csv', permutator_rows, ['run', 'generation', 'snapshot_kind', 'level', 'representative_index', 'representative_set', 'domain', 'degree', 'order', 'structure', 'generators', 'trivial', 'solvable'])
    print(f'GAP validated: {len(rows)-failed}/{len(rows)} snapshots', flush=True)
    return rows, failed


def make_plots(out, cfg, rows=None):
    """Within-run plots; the shaded band is a bound interval, not uncertainty SE."""
    plots = out / 'plots'
    plots.mkdir(exist_ok=True)
    all_metrics = []
    if rows is not None:
        rows = [r for r in rows if r.get('snapshot_kind', 'population_best') == 'population_best']
    for run in range(1, cfg['runs'] + 1):
        with (out / 'metrics' / f'run_{run:03d}.csv').open() as f:
            stride = max(1, cfg['generations'] // 5000)
            metrics = [r for r in csv.DictReader(f) if int(r['generation']) % stride == 0 or int(r['generation']) == cfg['generations']]
        all_metrics.append(metrics)
        generations = [int(r['generation']) for r in metrics]
        fig, axes = plt.subplots(3 if rows else 2, 1, figsize=(10, 9 if rows else 6), sharex=True)
        axes[0].plot(generations, [float(r['best_fitness']) for r in metrics], label='Best fitness')
        axes[0].plot(generations, [float(r['mean_fitness']) for r in metrics], alpha=.5, label='Population mean')
        axes[0].set_ylabel('Fitness')
        axes[0].legend()
        axes[1].plot(generations, [int(r['best_reachable_states']) for r in metrics], color='tab:purple', label='Best automaton: reachable states')
        axes[1].set_ylabel('States')
        axes[1].legend()
        if rows:
            rr = [r for r in rows if r['run'] == run]
            gg = [r['generation'] for r in rr]
            lo = [r['complexity_lower'] if r['status'] == 'completed' else np.nan for r in rr]
            hi = [r['complexity_upper'] if r['status'] == 'completed' else np.nan for r in rr]
            axes[2].plot(gg, lo, 'o-', label='Certified lower bound')
            axes[2].plot(gg, hi, 's-', label='Certified upper bound')
            axes[2].fill_between(gg, lo, hi, alpha=.15)
            axes[2].plot(gg, [r['state_ceiling'] for r in rr], 'k--', label='Reachable states − 1')
            axes[2].set_ylabel('Complexity bounds')
            axes[2].legend()
        ep = out / 'events' / f'run_{run:03d}_first_perfect.json'
        if ep.exists():
            for ax in axes:
                ax.axvline(read_json(ep)['generation'], color='tab:green', linestyle=':', linewidth=1.2)
        axes[-1].set_xlabel('Completed generations (green dotted line = first perfect traversal)')
        axes[-1].set_xscale('symlog', linthresh=10)
        fig.suptitle(f'Run {run}: evolution' + (' and snapshot complexity' if rows else ''))
        fig.tight_layout()
        fig.savefig(plots / f'run_{run:03d}_timeline.pdf')
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    for ax, key, label in zip(axes, ['best_fitness', 'best_reachable_states'], ['Best fitness', 'Best automaton: reachable states']):
        values = np.array([[float(r[key]) for r in mm] for mm in all_metrics])
        for vv in values:
            ax.plot(generations, vv, alpha=.18, linewidth=.7)
        mean, sd = values.mean(axis=0), values.std(axis=0)
        ax.plot(generations, mean, color='black', label='Across-run mean')
        ax.fill_between(generations, mean-sd, mean+sd, color='gray', alpha=.2, label='±1 SD across runs')
        ax.set_ylabel(label)
        ax.legend()
    axes[-1].set_xscale('symlog', linthresh=10)
    axes[-1].set_xlabel('Completed generations')
    fig.suptitle(f'Evolution across {cfg["runs"]} runs')
    fig.tight_layout()
    fig.savefig(plots / 'all_runs_evolution.pdf')
    plt.close(fig)
    if rows:
        summary = []
        for gen in cfg['record_generations']:
            rr = [r for r in rows if r['generation'] == gen]
            good = [r for r in rr if r['status'] == 'completed']
            complete = len(good) == cfg['runs']
            entry = dict(generation=gen, runs_recorded=len(rr), gap_completed=len(good),
                         mean_fitness=float(np.mean([r['best_fitness'] for r in rr])),
                         mean_reachable_states=float(np.mean([r['best_reachable_states'] for r in rr])))
            for key in ['complexity_lower', 'complexity_upper', 'gap_to_ceiling_min', 'gap_to_ceiling_max']:
                entry['mean_' + key] = float(np.mean([r[key] for r in good])) if complete else ''
            summary.append(entry)
        save_csv(out / 'generation_summary.csv', summary)
        fig, ax = plt.subplots(figsize=(10, 5))
        gx = [r['generation'] for r in summary]
        low = [r['mean_complexity_lower'] if r['mean_complexity_lower'] != '' else np.nan for r in summary]
        high = [r['mean_complexity_upper'] if r['mean_complexity_upper'] != '' else np.nan for r in summary]
        ax.plot(gx, low, 'o-', label='Mean certified lower bound')
        ax.plot(gx, high, 's-', label='Mean certified upper bound')
        ax.fill_between(gx, low, high, alpha=.15, label='Bounds on sample mean complexity')
        ax.plot(gx, [r['mean_reachable_states']-1 for r in summary], 'k--', label='Mean reachable states − 1')
        ax.set_xscale('symlog', linthresh=10)
        ax.set_xlabel('Completed generations (only saved snapshots have GAP analysis)')
        ax.set_ylabel('Mean complexity bounds across runs')
        ax.set_title('Complexity timeline; bounds omitted where any GAP analysis failed')
        ax.legend()
        fig.tight_layout()
        fig.savefig(plots / 'all_runs_complexity.pdf')
        plt.close(fig)
        fig, ax = plt.subplots(figsize=(9, 6))
        for run in range(1, cfg['runs'] + 1):
            rr = [r for r in rows if r['run'] == run and r['status'] == 'completed']
            if not rr:
                continue
            x = [r['best_fitness'] for r in rr]
            low = [r['gap_to_ceiling_min'] for r in rr]
            high = [r['gap_to_ceiling_max'] for r in rr]
            line, = ax.plot(x, low, 'o', markersize=3, label=f'Run {run}')
            ax.vlines(x, low, high, color=line.get_color(), alpha=.45)
        ax.set_xlabel('Best automaton fitness at saved generation')
        ax.set_ylabel('Distance to reachable-state ceiling: (n − 1) − complexity')
        ax.set_title('Does better fitness accompany a smaller complexity gap?\nVertical segments show certified intervals; lower is closer')
        ax.legend(ncol=2, fontsize=8)
        fig.tight_layout()
        fig.savefig(plots / 'fitness_vs_complexity_gap.pdf')
        plt.close(fig)


def export_spreadsheet(out, cfg):
    """Portable local Python export. No full-generation data duplicated into Excel.

    CSV contains all generations; this workbook contains measured checkpoints.
    No experiment data are fabricated when GAP has not yet run.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    book = Workbook(write_only=False)
    book.remove(book.active)
    sheets = {}
    def table(name, rows, headers=None):
        ws = book.create_sheet(name)
        sheets[name] = ws
        keys = headers or (list(rows[0]) if rows else ['status'])
        ws.append(keys)
        for row in rows:
            ws.append([row.get(k, '') for k in keys])
        ws.freeze_panes = 'C2' if len(keys) > 3 else 'A2'
        ws.auto_filter.ref = ws.dimensions
        for cell in ws[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='203B53')
            cell.alignment = Alignment(wrap_text=True)
        ws.row_dimensions[1].height = 44
        for j, key in enumerate(keys, 1):
            ws.column_dimensions[get_column_letter(j)].width = min(42, max(15, len(key)+2))
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                if isinstance(cell.value, float): cell.number_format = '0.000'
        return ws
    paths = sorted((out / 'snapshots').glob('run_*/gen_*.json'))
    timeline = {}
    if (out / 'timeline.csv').exists():
        with (out / 'timeline.csv').open() as f:
            timeline = {r['snapshot']: r for r in csv.DictReader(f)}
    checkpoints, groups, permutators, events = [], [], [], []
    for path in paths:
        snap = read_json(path)
        row = dict(run=snap['run'], generation=snap['generation'],
                   snapshot_kind=snap['snapshot_kind'], checkpoint_reasons=';'.join(snap['reasons']),
                   unpenalized_performance=snap['unpenalized_performance'], fitness=snap['best_fitness'],
                   state_cost=snap['state_cost'], N=snap['best_reachable_states'],
                   perfect_traversal=snap['perfect_traversal'], L='', U='', holonomy_group_bearing_levels='',
                   holonomy_depth='', non_solvable_group_occurrences='', gap_status='pending',
                   non_solvable_permutator_occurrences='', permutator_status='pending',
                   init_seed=snap['init_seed'], evolution_seed=snap['evolution_seed'],
                   automaton_file=str(path.relative_to(out)))
        measured = timeline.get(str(path.relative_to(out)))
        if measured:
            row['gap_status'] = measured['status']
            row['permutator_status'] = measured.get('permutator_status', 'pending')
            if measured['status'] == 'completed':
                for target, source in [('L','complexity_lower'), ('U','complexity_upper'),
                      ('holonomy_group_bearing_levels','holonomy_number'), ('holonomy_depth','holonomy_depth'),
                      ('non_solvable_group_occurrences','non_solvable_group_occurrences')]:
                    row[target] = int(measured[source])
                for group in json.loads(measured['holonomy_groups']):
                    groups.append(dict(run=snap['run'], generation=snap['generation'], snapshot_kind=snap['snapshot_kind'], **group))
                if row['permutator_status'] == 'completed':
                    row['non_solvable_permutator_occurrences'] = int(measured['non_solvable_permutator_occurrences'])
                    for group in json.loads(measured['permutator_groups']):
                        permutators.append(dict(run=snap['run'], generation=snap['generation'], snapshot_kind=snap['snapshot_kind'], **group))
        checkpoints.append(row)
        if snap['snapshot_kind'] == 'first_perfect_witness' or 'reachable_state_count_changed' in snap['reasons']:
            events.append(dict(run=snap['run'], generation=snap['generation'], event=';'.join(snap['reasons']),
                               fitness=snap['best_fitness'], unpenalized_performance=snap['unpenalized_performance'],
                               N=snap['best_reachable_states'], automaton_file=str(path.relative_to(out))))
    table('Checkpoints', checkpoints)
    table('Holonomy groups', groups, ['run','generation','snapshot_kind','level','representative_index',
                                    'representative_set','order','structure','generators','trivial','solvable'])
    table('Permutator groups', permutators, ['run','generation','snapshot_kind','level','representative_index',
                                          'representative_set','domain','degree','order','structure',
                                          'generators','trivial','solvable'])
    table('Events', events, ['run','generation','event','fitness','unpenalized_performance','N','automaton_file'])
    meta = [dict(parameter=k, value=json.dumps(v) if isinstance(v,(dict,list)) else v) for k,v in cfg.items()]
    if (out/'software/software.json').exists():
        meta.extend(dict(parameter=k,value=json.dumps(v) if isinstance(v,(dict,list)) else v)
                    for k,v in read_json(out/'software/software.json').items())
    meta.extend([dict(parameter='Perfect all-start traversal',value='16 transitions from each of 8 starts within 100 steps; raw score 128'),
                 dict(parameter='Holonomy count',value='One group occurrence per representative per non-singleton decomposition level; duplicates retained'),
                 dict(parameter='Permutator count',value='Same representatives as holonomy; separate occurrence count, not a sum with holonomy or a count of SNAG composition factors'),
                 dict(parameter='Permutator coordinates',value='Domain and generators use GAP labels 1..N; label j corresponds to the jth sorted original reachable state. Singletons omitted (trivial groups).'),
                 dict(parameter='U definition',value='min(group-bearing holonomy levels, N-1)'),
                 dict(parameter='Best-so-far ties',value='Current best fitness survivor; original offspring-priority tie breaking retained'),
                 dict(parameter='Reachability',value='Reachable from the Mealy initial state under all input symbols'),
                 dict(parameter='Full trajectories',value='metrics/run_XXX.csv contains every generation; Excel includes checkpoints only'),
                 dict(parameter='Schedule after 100000',value='Event checkpoints continue; final generation always saved'),
                 dict(parameter='Sources',value='Professor email supplied in chat; original source and software versions saved with experiment')])
    table('Parameters',meta)
    target=out/'experiment_results.xlsx'
    tmp=out/'experiment_results.tmp.xlsx'
    book.save(tmp)
    tmp.replace(target)
    print(f'Spreadsheet: {target}',flush=True)


def boolean(s):
    if s.lower() not in ('true', 'false'):
        raise argparse.ArgumentTypeError('Use True or False')
    return s.lower() == 'true'


def arguments():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--source', default=str(Path(__file__).with_name('ES-Automata-Fogel.py')))
    p.add_argument('--population_size', type=int, default=5)
    p.add_argument('--offspring_size', type=int, default=50)
    p.add_argument('--num_states', type=int, default=15)
    p.add_argument('--runs', type=int, default=10)
    p.add_argument('--generations', type=int, default=100000)
    p.add_argument('--fitness', choices=['MultiTraversal', 'Traversal', 'EightBall', 'FogelPalindrome'], default='MultiTraversal')
    p.add_argument('--env_variant', choices=['SimpleHardestEnvironment', 'SimpleEasiestEnvironment'], default='SimpleHardestEnvironment')
    p.add_argument('--self_loop_init', type=boolean, default=True)
    p.add_argument('--record_generations', nargs='+', help='Space- or comma-separated completed generations; always includes 0 and final')
    p.add_argument('--checkpoint_every', type=int, default=1000)
    p.add_argument('--progress_every', type=int, default=1000)
    p.add_argument('--init_seed', type=int, default=314159)
    p.add_argument('--seed_base', type=int, default=271829)
    p.add_argument('--output', type=Path)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--resume', type=Path, help='Existing output directory; resume latest checkpoint')
    mode.add_argument('--analyze_only', type=Path, help='Existing output directory; reuse cached bounds and backfill/retry missing group inventories')
    p.add_argument('--gap', default='gap')
    p.add_argument('--gap_timeout', type=int, default=0, help='Seconds per snapshot; 0 means no limit')
    p.add_argument('--skip_gap', action='store_true', help='Evolution only; later use --analyze_only')
    p.add_argument('--render_snapshots', action='store_true', help='Render every saved DOT graph as PDF with dot')
    return p, p.parse_args()


def main():
    parser, args = arguments()
    # Fail before a long experiment if the Excel export dependency is absent.
    import openpyxl
    existing = args.resume or args.analyze_only
    runner_sha = digest(__file__)
    if existing:
        out = existing.resolve()
        cfg = read_json(out / 'config.json')
        if args.output:
            parser.error('--output cannot be combined with resume/analyze_only')
        print('Using saved parameters from config.json; evolution arguments are ignored.', flush=True)
        if args.resume:
            if cfg['source_sha256'] != digest(cfg['source']):
                raise ValueError('Original source changed since this experiment; restore it before resume.')
            if cfg['runner_sha256'] != runner_sha or cfg['python_version'] != sys.version or cfg['numpy_version'] != np.__version__:
                raise ValueError('Runner/Python/NumPy changed; exact resume requires original versions.')
    else:
        for key in ('population_size', 'offspring_size', 'runs', 'generations', 'checkpoint_every', 'progress_every'):
            if getattr(args, key) < 1:
                parser.error(f'--{key} must be positive')
        if args.num_states < 2:
            parser.error('--num_states must be >= 2 (original merge-state mutation needs two states)')
        if args.gap_timeout < 0:
            parser.error('--gap_timeout cannot be negative')
        if not (0 <= args.init_seed < 2**32 and 0 <= args.seed_base and args.seed_base + args.runs - 1 < 2**32):
            parser.error('Seeds must fit NumPy unsigned 32-bit integers')
        if args.record_generations:
            try:
                schedule = [int(v) for item in args.record_generations for v in item.split(',')]
            except ValueError:
                parser.error('record_generations must contain integers')
            if any(g < 0 or g > args.generations for g in schedule):
                parser.error('Record generations must be between 0 and --generations')
        else:
            schedule = [g for g in DEFAULT_RECORD if g <= args.generations]
        schedule = sorted(set(schedule + [0, args.generations]))
        source = Path(args.source).resolve()
        # Import before creating output so a bad/missing source is an immediate error.
        core = load_core(source)
        out = (args.output or Path('results') / ('timeline_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S_%f'))).resolve()
        out.mkdir(parents=True, exist_ok=False)
        keys = ('population_size', 'offspring_size', 'num_states', 'runs', 'generations', 'fitness',
                'env_variant', 'self_loop_init', 'checkpoint_every', 'progress_every', 'init_seed', 'seed_base')
        cfg = {k: getattr(args, k) for k in keys}
        cfg.update(schema=SCHEMA, source=str(source), source_sha256=digest(source), runner_sha256=runner_sha,
                   record_generations=schedule, python_version=sys.version, numpy_version=np.__version__,
                   initialization='shared seeded initial population', execution='Sequential locally')
        atomic_json(out / 'config.json', cfg)
        shutil.copy2(source, out / 'original_source.py')
        shutil.copy2(__file__, out / 'timeline_runner.py')
        with (out / 'python_packages.txt').open('w') as f:
            subprocess.run([sys.executable, '-m', 'pip', 'freeze'], stdout=f, check=True)
    print(f'Output directory: {out}', flush=True)
    print(f'{cfg["runs"]} runs; {cfg["offspring_size"]} offspring; {cfg["generations"]} generations/run', flush=True)
    print(f'Snapshot generations: {cfg["record_generations"]}', flush=True)
    # Validate GAP before committing to long evolution, but no complexity runs yet.
    software = None if args.skip_gap else software_probe(out / 'software', args.gap)
    if not args.analyze_only:
        if existing:
            core = load_core(cfg['source'])
        evolve(out, cfg, core, resume=bool(args.resume))
    export_spreadsheet(out, cfg)
    make_plots(out, cfg)
    if software:
        try:
            rows, failed = analyze(out, cfg, software, args.gap_timeout, args.render_snapshots)
        finally:
            export_spreadsheet(out, cfg)
        make_plots(out, cfg, rows)
        print(f'Results: {out / "timeline.csv"}', flush=True)
        return 1 if failed else 0
    print('Evolution saved. Run --analyze_only on this directory when ready for GAP.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nInterrupted. Resume from the last saved checkpoint with --resume OUTPUT_DIRECTORY.', file=sys.stderr)
        raise SystemExit(130)
