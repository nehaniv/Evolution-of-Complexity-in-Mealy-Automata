#!/usr/bin/env python3
"""Generate, analyze, and collect constrained random Mealy automata."""

import argparse
from collections import Counter
from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import time

from uniform_sampling import UNIFORM_SAMPLING, make_uniform_automaton

SGPDEC_COMMIT = '8e0f8cb20ace52762dc9dcc2be3358db4abc51bd'
SAMPLING = 'forced Hamiltonian path 0->1->...->8; nonuniform constrained random'
SOURCE_FILES = ('baseline.py', 'baseline.sh', 'baseline_uniform.sh', 'uniform_sampling.py',
                'baseline_analysis.g', 'ES-Automata-Fogel.py', 'baseline_inventory.py',
                'baseline_inventory.g', 'baseline_inventory.sh')
META_FIELDS = ('automaton_id', 'seed', 'num_states', 'reachable_states', 'fitness',
               'automaton_sha256', 'input_offset', 'input_bytes')
BOUND_FIELDS = ('holonomy_upper_bound', 'certified_upper_bound', 'lower_bound', 'exact',
                'search_exhausted', 'edge_tests', 'lower_bound_elapsed_ms')
RESULT_FIELDS = ('automaton_id', 'seed', 'reachable_states', 'holonomy_upper_bound',
                 'lower_bound', 'certified_upper_bound', 'exact', 'status', 'fitness',
                 'num_states', 'search_exhausted', 'edge_tests', 'lower_bound_elapsed_ms',
                 'elapsed_seconds', 'sgpdec_commit', 'automaton_sha256', 'attempt', 'error')


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(temporary, path)


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, fields, rows):
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    with temporary.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


@contextmanager
def exclusive_lock(path):
    """The kernel releases this lock even when Slurm kills a worker."""
    with path.open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'Another process is using {path}') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def load_framework(path):
    spec = importlib.util.spec_from_file_location('es_automata', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_automaton(module, seed):
    """Preserve every random call, in order, from the ALIFE 2026 baseline."""
    random.seed(seed)
    inputs = [str(i) for i in range(1, 9)]
    outputs = ['0', '1']
    automaton = module.MealyAutomaton(15, inputs, outputs, self_loop_init=False)
    automaton.initial_state = 0
    for state in range(8):
        automaton.transitions[(state, random.choice(inputs))] = state + 1
    for state in range(9):
        for symbol in inputs:
            if automaton.transitions[(state, symbol)] >= 9:
                automaton.transitions[(state, symbol)] = random.choice(list(range(9)))
    for state in range(9, 15):
        for symbol in inputs:
            automaton.transitions[(state, symbol)] = random.randint(0, 14)
    for state in range(15):
        for symbol in inputs:
            automaton.outputs[(state, symbol)] = random.choice(outputs)
    if automaton.get_reachable_states() != list(range(9)):
        raise ValueError('Expected reachable states 0 through 8')
    return automaton


def generate(args):
    root = args.run_dir.resolve()
    if root.exists():
        raise ValueError(f'Run directory exists: {root}. Resume it or choose a new directory.')
    root.mkdir(parents=True)
    for name in ('source', 'logs'):
        (root / name).mkdir()
    source = Path(__file__).resolve().parent
    for name in SOURCE_FILES:
        shutil.copy2(source / name, root / 'source' / name)
    module = load_framework(root / 'source' / 'ES-Automata-Fogel.py')
    environment = module.EnvironmentDFA(8, ['0', '1'], variant='SimpleHardestEnvironment')
    uniform = getattr(args, 'sampling', 'hamiltonian') == 'uniform'
    rows = []
    with (root / 'automata.jsonl').open('wb') as archive:
        for identifier in range(1, args.count + 1):
            seed = args.seed_start + identifier - 1
            automaton = make_uniform_automaton(module, seed) if uniform else make_automaton(module, seed)
            fitness, _ = module.multitraversal_fitness(automaton, environment)
            data = {
                'automaton_id': identifier, 'seed': seed, 'num_states': 15,
                'reachable_states': 9, 'initial_state': automaton.initial_state, 'fitness': fitness,
                'input_alphabet': automaton.input_alphabet, 'output_alphabet': automaton.output_alphabet,
                'transitions': [[automaton.transitions[(s, a)] for a in automaton.input_alphabet]
                                for s in range(15)],
                'outputs': [[automaton.outputs[(s, a)] for a in automaton.input_alphabet]
                            for s in range(15)],
            }
            payload = (json.dumps(data, sort_keys=True, separators=(',', ':')) + '\n').encode()
            offset = archive.tell()
            archive.write(payload)
            rows.append({**{key: data[key] for key in META_FIELDS[:5]},
                         'automaton_sha256': hashlib.sha256(payload).hexdigest(),
                         'input_offset': offset, 'input_bytes': len(payload)})
            if identifier % 1000 == 0:
                print(f'Generated {identifier:,}/{args.count:,} automata', flush=True)
    write_csv(root / 'metadata.csv', META_FIELDS, rows)
    save_json(root / 'manifest.json', {
        'schema_version': 2, 'created_at': now(), 'count': args.count,
        'automata_sha256': digest(root / 'automata.jsonl'),
        'automata_bytes': (root / 'automata.jsonl').stat().st_size,
        'seed_start': args.seed_start, 'num_states': 15, 'reachable_states': 9,
        'sampling': UNIFORM_SAMPLING if uniform else SAMPLING,
        'fitness': 'MultiTraversal', 'environment': 'SimpleHardestEnvironment',
        'python_version': sys.version, 'metadata_sha256': digest(root / 'metadata.csv'),
        'source_sha256': {name: digest(root / 'source' / name) for name in SOURCE_FILES},
    })
    print(f'Generated {args.count:,} automata in {root}')


def read_manifest(root):
    manifest = read_json(root / 'manifest.json')
    if (root / 'automata.jsonl').stat().st_size != manifest['automata_bytes']:
        raise ValueError('Automaton archive is missing data or has changed size')
    if digest(root / 'metadata.csv') != manifest['metadata_sha256']:
        raise ValueError('Metadata changed after generation')
    for name, checksum in manifest['source_sha256'].items():
        if digest(root / 'source' / name) != checksum:
            raise ValueError(f'Run source changed after generation: {name}')
    return manifest


def git_output(directory, *args):
    return subprocess.check_output(['git', '-C', str(directory), *args], text=True).strip()


def check_sgpdec(directory, expected):
    if not re.fullmatch(r'[0-9a-f]{40}', expected):
        raise ValueError('SgpDec must be pinned to a full 40-character commit SHA')
    if git_output(directory, 'rev-parse', 'HEAD') != expected:
        raise ValueError(f'SgpDec checkout does not match expected commit {expected}')
    if git_output(directory, 'status', '--porcelain', '--untracked-files=all'):
        raise ValueError('SgpDec checkout has local changes; use a clean pinned checkout')


def gap_prelude(config):
    return f'''SetPackagePath("sgpdec", {json.dumps(config['sgpdec_dir'])});
if LoadPackage("sgpdec") <> true then Error("SgpDec could not be loaded"); fi;
if not IsBound(MaxChainOfEssentialDependencyWithProgress) then
  Error("This SgpDec checkout lacks the required lower-bound API");
fi;
'''


def run_gap(config, script, log, timeout):
    # -r skips user startup files that may preload another SgpDec version.
    command = [config['gap'], '-q', '-b', '-r', '-A', '--quitonbreak', '-o', config['gap_memory'], str(script)]
    with log.open('w') as stream:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return process.wait(timeout=timeout), False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            return process.returncode, True


def read_fields(path):
    if not path.exists():
        return {}
    pairs = [line.split('\t', 1) for line in path.read_text().splitlines()]
    if any(len(pair) != 2 for pair in pairs):
        raise ValueError(f'Malformed GAP result: {path}')
    result = dict(pairs)
    if len(result) != len(pairs) or result.pop('snapshot_complete', None) != 'true':
        raise ValueError(f'Incomplete GAP result: {path}')
    for key, value in result.items():
        result[key] = (value == 'true') if value in ('true', 'false') else int(value)
    return result


def validate_bounds(fields):
    if not fields:
        return
    reachable, holonomy, upper = (fields[key] for key in
        ('reachable_states', 'holonomy_upper_bound', 'certified_upper_bound'))
    if not all(type(value) is int for value in (reachable, holonomy, upper)):
        raise ValueError('Bounds and state count must be integers')
    if reachable < 1 or holonomy < 0 or upper != min(holonomy, reachable - 1):
        raise ValueError('Invalid holonomy/certified upper bound')
    lower = fields.get('lower_bound')
    if lower is not None:
        if type(lower) is not int or not 0 <= lower <= upper:
            raise ValueError('Invalid certified lower bound')
        if fields.get('exact') != (lower == upper):
            raise ValueError('Exactness disagrees with interval endpoints')


def certified_progress(path, upper):
    """Read explicit certificates, not arrows in a printed witness chain."""
    if not path.exists():
        return None
    text = path.read_text()
    start = re.search(r'^Start: degree=(\d+), certified upper=(\d+)$', text, re.M)
    if not start or (int(start[1]), int(start[2])) != (upper['reachable_states'], upper['certified_upper_bound']):
        raise ValueError('Progress certificate does not match upper-bound calculation')
    best = 0
    for match in re.finditer(r'^NEW CERTIFIED LOWER BOUND (\d+)/(\d+) after \d+ edge tests \(\d+ ms\)$', text, re.M):
        lower, ceiling = map(int, match.group(1, 2))
        if ceiling != upper['certified_upper_bound'] or not best < lower <= ceiling:
            raise ValueError('Invalid lower-bound progress certificate')
        best = lower
    return best


def preflight(args):
    root = args.run_dir.resolve()
    read_manifest(root)
    directory = args.sgpdec_dir.resolve()
    check_sgpdec(directory, args.sgpdec_commit)
    executable = shutil.which(args.gap)
    if not executable:
        raise ValueError(f'GAP executable not found: {args.gap}')
    config = {'gap': str(Path(executable).resolve()), 'gap_memory': args.gap_memory,
              'sgpdec_dir': str(directory), 'sgpdec_commit': args.sgpdec_commit,
              'timeout_seconds': args.timeout}
    config_path = root / 'analysis.json'
    if config_path.exists():
        previous = read_json(config_path)
        if any(previous[key] != config[key] for key in ('gap', 'sgpdec_dir', 'sgpdec_commit')):
            raise ValueError('GAP/SgpDec is fixed for this run; use a new run directory')
    with exclusive_lock(root / 'preflight.lock'):
        work = root / 'preflight'
        work.mkdir(exist_ok=True)
        for name in ('full3', 'aperiodic'):
            case = work / name
            case.mkdir(exist_ok=True)
            for filename in ('upper.tsv', 'bounds.tsv', 'lower-progress.txt'):
                (case / filename).unlink(missing_ok=True)
        script = work / 'check.g'
        script.write_text(gap_prelude(config) + f'''
Read({json.dumps(str(root / 'source' / 'baseline_analysis.g'))});
AnalyzeBaseline(GeneratorsOfSemigroup(FullTransformationSemigroup(3)), 3,
  {json.dumps(str(work / 'full3'))});
AnalyzeBaseline([Transformation([1,1])], 2, {json.dumps(str(work / 'aperiodic'))});
Print("BASELINE_PREFLIGHT_OK\\n");
QUIT;
''')
        returncode, timed_out = run_gap(config, script, work / 'gap.log', 300)
        if timed_out or returncode != 0 or 'BASELINE_PREFLIGHT_OK' not in (work / 'gap.log').read_text():
            raise RuntimeError(f"SgpDec preflight failed; inspect {work / 'gap.log'}")
        for name, expected in (('full3', 2), ('aperiodic', 0)):
            fields = {**read_fields(work / name / 'upper.tsv'), **read_fields(work / name / 'bounds.tsv')}
            validate_bounds(fields)
            if fields.get('lower_bound') != expected or fields.get('certified_upper_bound') != expected:
                raise ValueError(f'Incorrect bounds for preflight case {name}')
        save_json(config_path, config)
    print(f'Preflight passed with SgpDec {args.sgpdec_commit}')



def read_automaton(root, metadata):
    with (root / 'automata.jsonl').open('rb') as archive:
        archive.seek(metadata['input_offset'])
        payload = archive.read(metadata['input_bytes'])
    if hashlib.sha256(payload).hexdigest() != metadata['automaton_sha256']:
        raise ValueError(f"Automaton {metadata['automaton_id']} changed after generation")
    return json.loads(payload)


def reachable_generators(data, expected):
    """Use the actual initial state and reachable labels, not fixed states 0..8."""
    transitions = data['transitions']
    seen, todo = set(), [data.get('initial_state', 0)]
    while todo:
        q = todo.pop()
        if type(q) is not int or not 0 <= q < len(transitions):
            raise ValueError('Invalid transition target or initial state')
        if q not in seen:
            seen.add(q)
            todo.extend(transitions[q])
    states = sorted(seen)
    if len(states) != expected:
        raise ValueError('Actual reachable-state count differs from metadata')
    mapping = {q: j + 1 for j, q in enumerate(states)}
    return [[mapping[transitions[q][a]] for q in states]
            for a in range(len(transitions[states[0]]))]


def analyze_one(root, metadata, config):
    identifier = metadata['automaton_id']
    case = root / 'cases' / f'{identifier:05d}'
    case.mkdir(parents=True, exist_ok=True)
    with exclusive_lock(case / 'worker.lock'):
        result_path = case / 'result.json'
        if result_path.exists():
            previous = read_json(result_path)
            if previous.get('status') == 'complete':
                if any(previous.get(key) != value for key, value in metadata.items()) or previous.get('sgpdec_commit') != config['sgpdec_commit']:
                    raise ValueError(f'Stored result for {identifier} has different provenance')
                validate_bounds(previous)
                if not all(key in previous for key in BOUND_FIELDS):
                    raise ValueError('Stored completed result lacks bounds')
                return True
        data = read_automaton(root, metadata)
        number = 1
        while (case / f'attempt-{number:04d}').exists():
            number += 1
        attempt = case / f'attempt-{number:04d}'
        attempt.mkdir()
        result = {**metadata, 'status': 'incomplete', 'started_at': now(),
                  'sgpdec_commit': config['sgpdec_commit'], 'attempt': str(attempt.relative_to(root)),
                  'timeout_seconds': config['timeout_seconds'], 'gap_memory': config['gap_memory']}
        save_json(result_path, result)
        reachable = metadata['reachable_states']
        generators = ['Transformation(' + json.dumps(g) + ')'
                      for g in reachable_generators(data, reachable)]
        script = attempt / 'analyze.g'
        script.write_text(gap_prelude(config) +
            f"Read({json.dumps(str(root / 'source' / 'baseline_analysis.g'))});\n" +
            'AnalyzeBaseline([' + ',\n'.join(generators) + f'], {reachable}, ' + json.dumps(str(attempt)) + ');\nQUIT;\n')
        started = time.monotonic()
        try:
            returncode, timed_out = run_gap(config, script, attempt / 'gap.log', config['timeout_seconds'])
            result['gap_returncode'] = returncode
            upper = read_fields(attempt / 'upper.tsv')
            validate_bounds(upper)
            if upper and upper['reachable_states'] != reachable:
                raise ValueError('Analysis did not use the recorded reachable states')
            result.update(upper)
            if timed_out:
                result['status'] = 'timeout'
                if upper:
                    lower = certified_progress(attempt / 'lower-progress.txt', upper)
                    if lower is not None:
                        result.update(lower_bound=lower, exact=(lower == upper['certified_upper_bound']))
                result['error'] = f"Exceeded {config['timeout_seconds']} seconds; lower-bound search may be incomplete"
            elif returncode != 0:
                raise RuntimeError(f'GAP exited with status {returncode}; inspect attempt gap.log')
            else:
                bounds = read_fields(attempt / 'bounds.tsv')
                required = set(BOUND_FIELDS) - {'holonomy_upper_bound'}
                if not upper or not required <= bounds.keys():
                    raise ValueError('GAP exited without a complete numeric result')
                result.update(bounds)
                result['status'] = 'complete'
            validate_bounds(result if upper else {})
        except (ValueError, RuntimeError, OSError, KeyError) as error:
            for key in BOUND_FIELDS:
                result.pop(key, None)
            result.update(status='failed', error=str(error))
        result.update(elapsed_seconds=round(time.monotonic() - started, 3), finished_at=now())
        save_json(result_path, result)
        print(f"Automaton {identifier}: {result['status']}, lower={result.get('lower_bound')}, upper={result.get('holonomy_upper_bound')}", flush=True)
        return result['status'] == 'complete'


def metadata_rows(root):
    with (root / 'metadata.csv').open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    for row in rows:
        for key in ('automaton_id', 'seed', 'num_states', 'reachable_states', 'input_offset', 'input_bytes'):
            row[key] = int(row[key])
        row['fitness'] = float(row['fitness'])
    return rows


def analyze(args):
    root = args.run_dir.resolve()
    manifest = read_manifest(root)
    config = read_json(root / 'analysis.json')
    check_sgpdec(Path(config['sgpdec_dir']), config['sgpdec_commit'])
    start = args.task_id * args.batch_size
    if start >= manifest['count']:
        raise ValueError('Task index is outside this run')
    successes = [analyze_one(root, row, config)
                 for row in metadata_rows(root)[start:start + args.batch_size]]
    return 0 if all(successes) else 1


def export_workbook(path, rows, summary, intervals):
    # Use the project's existing Excel dependency for unattended cluster exports.
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    workbook = Workbook()
    workbook.properties.creator = ''
    workbook.properties.lastModifiedBy = ''
    sheet = workbook.active
    sheet.title = 'Distribution'
    sheet.append(['Complexity intervals'])
    sheet.append(['Expected automata', summary['expected']])
    sheet.append(['Completed analyses', summary['complete']])
    sheet.append(['Available certified intervals', summary['intervals']])
    sheet.append(['Not completed', summary['expected'] - summary['complete']])
    sheet.append(['Sampling', summary['sampling']])
    sheet.append(['Intervals include certified partial bounds; see status.'])
    sheet.append([])
    interval_fields = ('lower_bound', 'holonomy_upper_bound', 'certified_upper_bound', 'status', 'count', 'fraction_of_all')
    sheet.append(list(interval_fields))
    for interval in intervals:
        sheet.append([interval[key] for key in interval_fields])
    details = workbook.create_sheet('Automata')
    details.append(list(RESULT_FIELDS))
    for row in rows:
        details.append([row.get(key) for key in RESULT_FIELDS])
    last_column = get_column_letter(len(RESULT_FIELDS))
    table = Table(displayName='AutomataResults', ref=f'A1:{last_column}{len(rows) + 1}')
    table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
    details.add_table(table)
    details.freeze_panes = 'C2'
    for target, header_row in ((sheet, 9), (details, 1)):
        target.sheet_view.showGridLines = False
        for row in target:
            for cell in row:
                cell.font = Font(name='Arial', size=10)
                cell.alignment = Alignment(vertical='center')
        for cell in target[header_row]:
            cell.font = Font(name='Arial', size=10, bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='243B53')
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        target.row_dimensions[header_row].height = 32
        for column in target.columns:
            target.column_dimensions[column[0].column_letter].width = 22
    sheet.column_dimensions['A'].width = 34
    sheet.column_dimensions['B'].width = 28
    sheet['A1'].font = Font(name='Arial', size=14, bold=True)
    for key, width in (('automaton_sha256', 68), ('sgpdec_commit', 44), ('attempt', 40), ('error', 72)):
        details.column_dimensions[get_column_letter(RESULT_FIELDS.index(key) + 1)].width = width
    for cell in details['I'][1:]:
        cell.number_format = '0.0'
    for cell in sheet['F'][9:]:
        cell.number_format = '0.00%'
    temporary = path.with_name(path.stem + '.tmp.xlsx')
    workbook.save(temporary)
    os.replace(temporary, path)


def collect(args):
    root = args.run_dir.resolve()
    manifest = read_manifest(root)
    config = read_json(root / 'analysis.json') if (root / 'analysis.json').exists() else {}
    rows = []
    for metadata in metadata_rows(root):
        path = root / 'cases' / f"{metadata['automaton_id']:05d}" / 'result.json'
        row = {**metadata, 'status': 'pending'}
        if path.exists():
            try:
                result = read_json(path)
                if any(result.get(key) != value for key, value in metadata.items()):
                    raise ValueError('Result does not match automaton metadata')
                if result.get('sgpdec_commit') != config.get('sgpdec_commit'):
                    raise ValueError('Result uses a different SgpDec revision')
                if 'holonomy_upper_bound' in result:
                    validate_bounds(result)
                if result['status'] == 'complete' and any(key not in result for key in BOUND_FIELDS):
                    raise ValueError('Completed result lacks bounds or search information')
                row.update(result)
            except (ValueError, KeyError) as error:
                row.update(status='invalid', error=str(error))
        rows.append(row)
    if len(rows) != manifest['count'] or [r['automaton_id'] for r in rows] != list(range(1, manifest['count'] + 1)):
        raise ValueError('Missing or duplicate automaton metadata')
    counts = Counter(row['status'] for row in rows)
    valid = [row for row in rows if row['status'] in ('complete', 'timeout') and row.get('lower_bound') is not None]
    groups = Counter((r['lower_bound'], r['holonomy_upper_bound'], r['certified_upper_bound'], r['status']) for r in valid)
    intervals = [dict(zip(('lower_bound', 'holonomy_upper_bound', 'certified_upper_bound', 'status'), key),
                      count=count, fraction_of_all=count / manifest['count'])
                 for key, count in sorted(groups.items())]
    summary = {'expected': manifest['count'], 'complete': counts['complete'],
               'intervals': len(valid), 'statuses': dict(counts), 'collected_at': now(),
               'sampling': manifest.get('sampling', SAMPLING), 'sgpdec_commit': config.get('sgpdec_commit')}
    with exclusive_lock(root / 'collect.lock'):
        write_csv(root / 'baseline_results.csv', RESULT_FIELDS, rows)
        write_csv(root / 'interval_distribution.csv',
                  ('lower_bound', 'holonomy_upper_bound', 'certified_upper_bound', 'status', 'count', 'fraction_of_all'), intervals)
        save_json(root / 'summary.json', summary)
        if not args.csv_only:
            export_workbook(root / 'baseline_results.xlsx', rows, summary, intervals)
    print(json.dumps(summary, indent=2))
    return 0 if counts['complete'] == manifest['count'] else 2


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError('must be nonnegative')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    generation = commands.add_parser('generate', help='Generate and snapshot a new run')
    generation.add_argument('--run-dir', type=Path, required=True)
    generation.add_argument('--count', type=positive, default=10000)
    generation.add_argument('--seed-start', type=nonnegative, default=0)
    generation.add_argument('--sampling', choices=['uniform', 'hamiltonian'], default='uniform',
                            help='Use baseline_uniform.sh for the required uniform baseline')
    generation.set_defaults(handler=generate)
    check = commands.add_parser('preflight', help='Verify pinned SgpDec and known bounds')
    check.add_argument('--run-dir', type=Path, required=True)
    check.add_argument('--gap', default='gap')
    check.add_argument('--sgpdec-dir', type=Path, required=True)
    check.add_argument('--sgpdec-commit', default=SGPDEC_COMMIT)
    check.add_argument('--gap-memory', default='24g')
    check.add_argument('--timeout', type=positive, default=7200)
    check.set_defaults(handler=preflight)
    worker = commands.add_parser('analyze', help='Analyze one array task; skip complete cases')
    worker.add_argument('--run-dir', type=Path, required=True)
    worker.add_argument('--task-id', type=nonnegative, default=0)
    worker.add_argument('--batch-size', type=positive, default=20)
    worker.set_defaults(handler=analyze)
    collector = commands.add_parser('collect', help='Export all rows and interval frequencies')
    collector.add_argument('--run-dir', type=Path, required=True)
    collector.add_argument('--csv-only', action='store_true')
    collector.set_defaults(handler=collect)
    args = parser.parse_args()
    try:
        return args.handler(args) or 0
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
