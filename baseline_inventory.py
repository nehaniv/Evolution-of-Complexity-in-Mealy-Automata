#!/usr/bin/env python3
"""Backfill performance and group inventories without changing baseline bounds.

Run prepare once, analyze locally or in array batches, then collect.
Existing automata.jsonl, source/, cases/ and bound results are read-only.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

import baseline

SOURCE_FILES = ('baseline_inventory.py', 'baseline_inventory.g', 'baseline_inventory.sh', 'baseline.py', 'uniform_sampling.py')
GROUP_FIELDS = ('level', 'representative_index', 'representative_set', 'order', 'structure',
                'generators', 'trivial', 'solvable')
PERMUTATOR_FIELDS = GROUP_FIELDS[:3] + ('domain', 'degree') + GROUP_FIELDS[3:]
PREFIX = ('automaton_id', 'seed')
RESULT_FIELDS = PREFIX + ('sampling', 'num_states', 'N', 'initial_state',
    'unpenalized_performance', 'fitness', 'state_cost', 'perfect_traversal',
    'transitions_per_start', 'performance_status', 'L', 'U', 'holonomy_upper_bound',
    'gap_status', 'bounds_error', 'exact', 'search_exhausted', 'edge_tests', 'lower_bound_elapsed_ms',
    'bounds_attempt', 'bounds_elapsed_seconds', 'state_ceiling', 'gap_to_ceiling_min', 'gap_to_ceiling_max',
    'normalized_lower', 'normalized_upper', 'holonomy_group_bearing_levels', 'holonomy_depth',
    'non_solvable_group_occurrences', 'non_solvable_permutator_occurrences',
    'inventory_status', 'inventory_error', 'automaton_sha256', 'input_offset', 'input_bytes',
    'reachable_states_original_labels', 'inventory_result', 'gap_version', 'semigroups_version',
    'sgpdec_commit', 'timeout_seconds', 'elapsed_seconds')


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def inventory_key(metadata, config):
    # A longer retry limit changes execution, not a completed group's validity.
    semantic = {k: v for k, v in config.items() if k != 'timeout_seconds'}
    return checksum({'automaton_sha256': metadata['automaton_sha256'], 'config': semantic})


def saved_config(root, check_runner=True):
    manifest = baseline.read_manifest(root)
    destination = root / 'inventory'
    config = baseline.read_json(destination / 'config.json')
    if (config['manifest_sha256'] != baseline.digest(root / 'manifest.json') or
            config['automata_sha256'] != manifest['automata_sha256']):
        raise ValueError('Inventory belongs to a different baseline dataset')
    for name, sha in config['source_sha256'].items():
        if baseline.digest(destination / 'source' / name) != sha:
            raise ValueError(f'Frozen inventory source changed: {name}')
    if check_runner and (baseline.digest(__file__) != config['source_sha256']['baseline_inventory.py'] or
                         baseline.digest(baseline.__file__) != config['source_sha256']['baseline.py']):
        raise ValueError('Use the frozen runner in RUN_DIRECTORY/inventory/source')
    return destination, manifest, config


def prepare(args):
    root = args.run_dir.resolve()
    manifest = baseline.read_manifest(root)
    if manifest.get('fitness') != 'MultiTraversal' or manifest.get('environment') != 'SimpleHardestEnvironment':
        raise ValueError('This inventory evaluates MultiTraversal in SimpleHardestEnvironment')
    if baseline.digest(root / 'automata.jsonl') != manifest['automata_sha256']:
        raise ValueError('Automaton archive checksum changed')
    config = baseline.read_json(root / 'analysis.json')
    baseline.check_sgpdec(Path(config['sgpdec_dir']), config['sgpdec_commit'])
    destination = root / 'inventory'
    destination.mkdir(exist_ok=True)
    with baseline.exclusive_lock(destination / 'prepare.lock'):
        if (destination / 'config.json').exists():
            _, _, previous = saved_config(root, check_runner=False)
            if args.timeout is not None and previous['timeout_seconds'] != args.timeout:
                previous['timeout_seconds'] = args.timeout
                baseline.save_json(destination / 'config.json', previous)
            print(f'Existing inventory source retained: {destination}')
            return
        source = destination / 'source'
        source.mkdir(exist_ok=True)
        for name in SOURCE_FILES:
            shutil.copy2(Path(__file__).with_name(name), source / name)
        probe = destination / 'software.g'
        probe.write_text(baseline.gap_prelude(config) + '''
Print("INVENTORY_GAP_VERSION:", GAPInfo.Version, "\\n");
Print("INVENTORY_SEMIGROUPS_VERSION:", PackageInfo("Semigroups")[1].Version, "\\n");
Print("INVENTORY_SOFTWARE_DONE\\n");
QUIT;
''')
        log = destination / 'software.log'
        returncode, timeout = baseline.run_gap(config, probe, log, 180)
        text = log.read_text()
        if returncode or timeout or 'INVENTORY_SOFTWARE_DONE' not in text.splitlines():
            raise ValueError(f'Inventory software check failed; inspect {log}')
        versions = {}
        for name, marker in [('gap_version', 'INVENTORY_GAP_VERSION:'),
                             ('semigroups_version', 'INVENTORY_SEMIGROUPS_VERSION:')]:
            hits = [line[len(marker):].strip() for line in text.splitlines() if line.startswith(marker)]
            if len(hits) != 1:
                raise ValueError(f'Missing or repeated {name}')
            versions[name] = hits[0]
        baseline.save_json(destination / 'config.json', {
            **config, **versions, 'timeout_seconds': args.timeout or 300,
            'schema_version': 1, 'created_at': baseline.now(), 'python_version': sys.version,
            'manifest_sha256': baseline.digest(root / 'manifest.json'),
            'automata_sha256': manifest['automata_sha256'],
            'source_sha256': {name: baseline.digest(source / name) for name in SOURCE_FILES},
            'convention': 'One occurrence per representative per non-singleton skeleton level; duplicates retained',
            'coordinates': 'GAP point j corresponds to jth sorted original reachable state',
            'software_scope': 'GAP/Semigroups versions describe the supplemental inventory pass; original bounds are matched by automaton provenance and SgpDec commit',
        })
    print(f'Prepared supplementary inventory: {destination}')


def reachable_action(data):
    """Validate and reindex the actual reachable part, including nonconsecutive labels."""
    n, alphabet = data['num_states'], data['input_alphabet']
    transitions, outputs = data['transitions'], data['outputs']
    if (type(n) is not int or n < 1 or not alphabet or len(set(alphabet)) != len(alphabet) or
            len(transitions) != n or len(outputs) != n or
            any(len(row) != len(alphabet) for row in transitions + outputs) or
            any(type(t) is not int or not 0 <= t < n for row in transitions for t in row) or
            any(o not in data['output_alphabet'] for row in outputs for o in row)):
        raise ValueError('Malformed transition/output tables')
    initial = data['initial_state']
    if type(initial) is not int or not 0 <= initial < n:
        raise ValueError('Invalid initial state')
    seen, todo = set(), [initial]
    while todo:
        q = todo.pop()
        if q not in seen:
            seen.add(q)
            todo.extend(transitions[q])
    states = sorted(seen)
    if len(states) != data['reachable_states']:
        raise ValueError('Recorded reachable-state count is inconsistent')
    index = {q: j + 1 for j, q in enumerate(states)}
    generators = [[index[transitions[q][i]] for q in states] for i in range(len(alphabet))]
    return states, generators


def performance(data, framework, environment):
    automaton = framework.MealyAutomaton.__new__(framework.MealyAutomaton)
    for name in ('num_states', 'input_alphabet', 'output_alphabet', 'initial_state'):
        setattr(automaton, name, data[name])
    automaton.transitions = {(q, a): data['transitions'][q][i]
                            for q in range(data['num_states']) for i, a in enumerate(data['input_alphabet'])}
    automaton.outputs = {(q, a): data['outputs'][q][i]
                        for q in range(data['num_states']) for i, a in enumerate(data['input_alphabet'])}
    fitness, details = framework.multitraversal_fitness(automaton, environment)
    counts = [int(r['run_fitness']) for r in details['per_start']]
    if not math.isclose(fitness, data['fitness'], rel_tol=0, abs_tol=1e-9):
        raise ValueError('Recomputed fitness differs from saved baseline fitness')
    target = environment.num_states * len(environment.input_alphabet)
    return dict(unpenalized_performance=sum(counts), fitness=float(fitness),
                state_cost=float(sum(counts) - fitness), transitions_per_start=counts,
                perfect_traversal=len(counts) == environment.num_states and all(v == target for v in counts),
                performance_status='completed')


def parse_inventory(path, n):
    records, summary = [], {}
    with path.open() as stream:
        lines = list(csv.reader(stream, delimiter='\t'))
    for fields in lines:
        if fields and fields[0] == 'group':
            if len(fields) != 14:
                raise ValueError('Malformed paired group record')
            records.append(fields[1:])
        elif len(fields) == 2 and fields[0] not in summary:
            summary[fields[0]] = fields[1]
        else:
            raise ValueError('Malformed or duplicate inventory summary')
    required = {'reachable_states', 'holonomy_depth', 'holonomy_group_bearing_levels', 'group_count', 'inventory_complete'}
    if set(summary) != required or summary['inventory_complete'] != 'true':
        raise ValueError('Incomplete inventory')
    summary = {key: int(value) for key, value in summary.items() if key != 'inventory_complete'}
    if summary['reachable_states'] != n or summary['holonomy_depth'] < 0:
        raise ValueError('Inventory state count/depth mismatch')
    holonomy, permutators, identities = [], [], set()
    for fields in records:
        level, rep, representative, ho, hs, hg, hv, domain, degree, po, ps, pg, pv = fields
        level, rep, ho, degree, po = map(int, (level, rep, ho, degree, po))
        key = (level, rep)
        if (key in identities or not 1 <= level <= summary['holonomy_depth'] or rep < 1 or
                min(ho, po) < 1 or hv not in ('true', 'false') or pv not in ('true', 'false')):
            raise ValueError('Invalid or duplicate group')
        points = json.loads(domain)
        blist = json.loads(representative)
        if (not isinstance(points, list) or any(type(q) is not int for q in points) or
                len(points) != degree or degree < 2 or points != sorted(set(points)) or
                not all(1 <= q <= n for q in points) or not isinstance(blist, list) or
                len(blist) != n or any(type(b) is not bool for b in blist) or
                points != [i + 1 for i, b in enumerate(blist) if b]):
            raise ValueError('Invalid representative action domain')
        if po % ho or (pv == 'true' and hv == 'false'):
            raise ValueError('Invalid permutator/holonomy quotient relationship')
        identities.add(key)
        shared = dict(level=level, representative_index=rep, representative_set=representative)
        holonomy.append(dict(shared, order=ho, structure=hs, generators=hg, trivial=ho == 1, solvable=hv == 'true'))
        permutators.append(dict(shared, domain=domain, degree=degree, order=po, structure=ps,
                                generators=pg, trivial=po == 1, solvable=pv == 'true'))
    if (len(records) != summary.pop('group_count') or
            len({g['level'] for g in holonomy if not g['trivial']}) != summary['holonomy_group_bearing_levels']):
        raise ValueError('Incomplete group inventory or inconsistent holonomy upper bound')
    return dict(summary, holonomy_groups=holonomy, permutator_groups=permutators,
                non_solvable_group_occurrences=sum(not g['solvable'] for g in holonomy),
                non_solvable_permutator_occurrences=sum(not g['solvable'] for g in permutators))


def analyze_one(root, destination, metadata, config, framework, environment):
    identifier = metadata['automaton_id']
    case = destination / 'cases' / f'{identifier:05d}'
    case.mkdir(parents=True, exist_ok=True)
    key = inventory_key(metadata, config)
    with baseline.exclusive_lock(case / 'worker.lock'):
        resultfile = case / 'result.json'
        if resultfile.exists():
            cached = baseline.read_json(resultfile)
            if cached.get('cache_key') == key and cached.get('inventory_status') == 'completed':
                return True
        number = 1
        while (case / f'attempt-{number:04d}').exists():
            number += 1
        attempt = case / f'attempt-{number:04d}'
        attempt.mkdir()
        row = dict(metadata, cache_key=key, inventory_status='failed', performance_status='pending',
                   inventory_error='', attempt=str(attempt.relative_to(root)), started_at=baseline.now(),
                   timeout_seconds=config['timeout_seconds'])
        started = time.monotonic()
        try:
            data = baseline.read_automaton(root, metadata)
            states, gens = reachable_action(data)
            row.update(performance(data, framework, environment), reachable_states_original_labels=states,
                       initial_state=data['initial_state'])
            generators = ','.join('Transformation(' + json.dumps(g) + ')' for g in gens)
            script = attempt / 'inventory.g'
            script.write_text(baseline.gap_prelude(config) +
                f'Read({json.dumps(str(destination / "source/baseline_inventory.g"))});\n' +
                f'BaselineInventory([{generators}], {len(states)}, {json.dumps(str(attempt / "groups.tsv"))});\nQUIT;\n')
            code, timeout = baseline.run_gap(config, script, attempt / 'gap.log', config['timeout_seconds'])
            if timeout:
                row['inventory_status'] = 'timeout'
                raise RuntimeError(f'Inventory exceeded {config["timeout_seconds"]} seconds')
            if code:
                raise RuntimeError(f'Inventory GAP exited with status {code}; inspect {attempt / "gap.log"}')
            row.update(parse_inventory(attempt / 'groups.tsv', len(states)), inventory_status='completed')
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
            row['inventory_error'] = str(error)
        row.update(elapsed_seconds=round(time.monotonic() - started, 3), finished_at=baseline.now())
        baseline.save_json(resultfile, row)
        print(f'Inventory {identifier}: {row["inventory_status"]}', flush=True)
        return row['inventory_status'] == 'completed'


def analyze(args):
    root = args.run_dir.resolve()
    destination, manifest, config = saved_config(root)
    baseline.check_sgpdec(Path(config['sgpdec_dir']), config['sgpdec_commit'])
    start = args.task_id * args.batch_size
    if start >= manifest['count']:
        raise ValueError('Task index is outside this run')
    framework = baseline.load_framework(root / 'source/ES-Automata-Fogel.py')
    environment = framework.EnvironmentDFA(8, ['0', '1'], variant='SimpleHardestEnvironment')
    successes = [analyze_one(root, destination, row, config, framework, environment)
                 for row in baseline.metadata_rows(root)[start:start + args.batch_size]]
    return 0 if all(successes) else 1


def bounds_for(root, metadata, config):
    path = root / 'cases' / f'{metadata["automaton_id"]:05d}' / 'result.json'
    if not path.exists():
        return dict(gap_status='pending')
    try:
        result = baseline.read_json(path)
        if (any(result.get(k) != v for k, v in metadata.items()) or
                result.get('sgpdec_commit') != config['sgpdec_commit']):
            raise ValueError('Bounds provenance differs from inventory provenance')
        baseline.validate_bounds(result if 'holonomy_upper_bound' in result else {})
        if result['status'] == 'complete' and any(k not in result for k in baseline.BOUND_FIELDS):
            raise ValueError('Completed bounds result lacks required fields')
        if 'holonomy_upper_bound' in result:
            # The old runner assumed states 0..8. A uniform generator added to
            # that runner alone can therefore leave numerically plausible but
            # unrelated bounds. Audit the saved GAP input before reusing them.
            if not result.get('attempt'):
                raise ValueError('Saved GAP input unavailable; bounds require validation before reuse')
            text = (root / result['attempt'] / 'analyze.g').read_text()
            recorded = [json.loads(value) for value in
                        re.findall(r'Transformation\(\s*(\[[\d,\s]*\])\s*\)', text)]
            data = baseline.read_automaton(root, metadata)
            expected = baseline.reachable_generators(data, metadata['reachable_states'])
            if recorded != expected:
                raise ValueError('Saved bounds GAP input differs from the actual reachable action; recompute bounds from the saved automaton')
        row = dict(gap_status='completed' if result['status'] == 'complete' else result['status'],
                   bounds_error=result.get('error', ''))
        for target, source in [('L', 'lower_bound'), ('U', 'certified_upper_bound'),
                               ('holonomy_upper_bound', 'holonomy_upper_bound'),
                               ('exact', 'exact'), ('search_exhausted', 'search_exhausted'),
                               ('edge_tests', 'edge_tests'), ('lower_bound_elapsed_ms', 'lower_bound_elapsed_ms'),
                               ('bounds_attempt', 'attempt'), ('bounds_elapsed_seconds', 'elapsed_seconds')]:
            if source in result:
                row[target] = result[source]
        return row
    except (ValueError, KeyError, OSError) as error:
        return dict(gap_status='invalid', bounds_error=str(error))


def export_workbook(destination, parameters):
    """Stream group tables: 10,000 automata can produce hundreds of thousands of rows."""
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font, PatternFill
    book = Workbook(write_only=True)
    numbers = set(('automaton_id', 'seed', 'num_states', 'N', 'initial_state', 'unpenalized_performance',
        'fitness', 'state_cost', 'L', 'U', 'holonomy_upper_bound', 'state_ceiling', 'gap_to_ceiling_min',
        'gap_to_ceiling_max', 'normalized_lower', 'normalized_upper', 'holonomy_group_bearing_levels',
        'holonomy_depth', 'non_solvable_group_occurrences', 'non_solvable_permutator_occurrences',
        'input_offset', 'input_bytes', 'elapsed_seconds', 'level', 'representative_index', 'degree',
        'order', 'count', 'fraction_of_all', 'fraction_of_completed', 'timeout_seconds',
        'edge_tests', 'lower_bound_elapsed_ms', 'bounds_elapsed_seconds'))
    booleans = {'perfect_traversal', 'trivial', 'solvable', 'exact', 'search_exhausted'}
    for title, filename in [('Automata', 'baseline_inventory_results.csv'),
                            ('Holonomy groups', 'holonomy_groups.csv'),
                            ('Permutator groups', 'permutator_groups.csv'),
                            ('Group distribution', 'group_distribution.csv')]:
        with (destination / filename).open(newline='') as stream:
            reader = csv.reader(stream)
            header = next(reader)
            part, count = 0, 1048576
            for values in reader:
                if count == 1048576:
                    part += 1
                    sheet = book.create_sheet(title if part == 1 else f'{title} {part}')
                    sheet.freeze_panes = 'C2'
                    cells = []
                    for name in header:
                        cell = WriteOnlyCell(sheet, name)
                        cell.font = Font(bold=True, color='FFFFFF')
                        cell.fill = PatternFill('solid', fgColor='243B53')
                        cells.append(cell)
                    sheet.append(cells)
                    count = 1
                converted = []
                for name, value in zip(header, values):
                    if name in booleans and value in ('True', 'False'):
                        value = value == 'True'
                    elif name in numbers and value:
                        try:
                            value = int(value)
                        except ValueError:
                            try:
                                value = float(value)
                            except ValueError:
                                pass
                    converted.append(value if value != '' else None)
                sheet.append(converted)
                count += 1
            if part == 0:
                sheet = book.create_sheet(title)
                sheet.append(header)
    sheet = book.create_sheet('Parameters')
    sheet.append(['parameter', 'value'])
    for key, value in parameters.items():
        sheet.append([key, json.dumps(value) if isinstance(value, (list, dict)) else value])
    temporary = destination / 'baseline_inventory_results.tmp.xlsx'
    book.save(temporary)
    temporary.replace(destination / 'baseline_inventory_results.xlsx')


def collect(args):
    root = args.run_dir.resolve()
    destination, manifest, config = saved_config(root)
    rows, paths = [], []
    for metadata in baseline.metadata_rows(root):
        path = destination / 'cases' / f'{metadata["automaton_id"]:05d}' / 'result.json'
        row = dict(metadata, sampling=manifest['sampling'], N=metadata['reachable_states'],
                   inventory_status='pending', performance_status='pending', **bounds_for(root, metadata, config))
        if path.exists():
            result = baseline.read_json(path)
            if (any(result.get(k) != v for k, v in metadata.items()) or
                    result.get('cache_key') != inventory_key(metadata, config)):
                row.update(inventory_status='invalid', inventory_error='Inventory provenance mismatch')
            else:
                row.update({k: v for k, v in result.items() if k not in ('holonomy_groups', 'permutator_groups')})
                if (row['inventory_status'] == 'completed' and 'holonomy_upper_bound' in row and
                        row['holonomy_upper_bound'] != result['holonomy_group_bearing_levels']):
                    row.update(gap_status='invalid', bounds_error='Bounds and inventory holonomy upper bounds differ')
                    row.pop('L', None); row.pop('U', None)
                if row['inventory_status'] == 'completed':
                    # This upper bound needs no dependency search, even if Nina's
                    # lower-bound calculation is still pending or timed out.
                    row.setdefault('U', min(result['holonomy_group_bearing_levels'], row['N'] - 1))
        ceiling = row['N'] - 1
        row.update(state_ceiling=ceiling, inventory_result=str(path.relative_to(root)),
                   gap_version=config['gap_version'], semigroups_version=config['semigroups_version'],
                   sgpdec_commit=config['sgpdec_commit'])
        if 'U' in row:
            row.update(gap_to_ceiling_min=ceiling - row['U'], normalized_upper=row['U']/ceiling if ceiling else '')
        if 'L' in row:
            row.update(gap_to_ceiling_max=ceiling - row['L'], normalized_lower=row['L']/ceiling if ceiling else '')
        for key in ('transitions_per_start', 'reachable_states_original_labels'):
            if key in row:
                row[key] = json.dumps(row[key])
        rows.append(row)
        paths.append(path)
    if len(rows) != manifest['count'] or [r['automaton_id'] for r in rows] != list(range(1, manifest['count'] + 1)):
        raise ValueError('Missing or duplicate automaton metadata')
    counts = Counter(r['inventory_status'] for r in rows)
    distribution = Counter((r['non_solvable_group_occurrences'], r['non_solvable_permutator_occurrences'])
                           for r in rows if r['inventory_status'] == 'completed')
    frequencies = [dict(non_solvable_group_occurrences=h, non_solvable_permutator_occurrences=p,
                        count=count, fraction_of_all=count/len(rows),
                        fraction_of_completed=count/counts['completed']) for (h, p), count in sorted(distribution.items())]
    summary = dict(expected=len(rows), inventory_statuses=dict(counts),
                   bounds_statuses=dict(Counter(r['gap_status'] for r in rows)),
                   performance_statuses=dict(Counter(r['performance_status'] for r in rows)),
                   sampling=manifest['sampling'], collected_at=baseline.now())
    def groups(kind):
        for row, path in zip(rows, paths):
            if row['inventory_status'] == 'completed':
                for group in baseline.read_json(path)[kind]:
                    yield dict(automaton_id=row['automaton_id'], seed=row['seed'], **group)
    with baseline.exclusive_lock(destination / 'collect.lock'):
        baseline.write_csv(destination / 'baseline_inventory_results.csv', RESULT_FIELDS, rows)
        baseline.write_csv(destination / 'holonomy_groups.csv', PREFIX + GROUP_FIELDS, groups('holonomy_groups'))
        baseline.write_csv(destination / 'permutator_groups.csv', PREFIX + PERMUTATOR_FIELDS, groups('permutator_groups'))
        baseline.write_csv(destination / 'group_distribution.csv',
            ('non_solvable_group_occurrences', 'non_solvable_permutator_occurrences', 'count',
             'fraction_of_all', 'fraction_of_completed'), frequencies)
        baseline.save_json(destination / 'summary.json', summary)
        if not args.csv_only:
            export_workbook(destination, dict(config, sampling=manifest['sampling'],
                baseline_generation_parameters=manifest, baseline_scope='Independent automata; generation/events/population checkpoints are not applicable',
                count_definition='Non-solvable representative group occurrences, not SNAG composition-factor multiplicities',
                original_automata='Full tables in ../automata.jsonl; byte offsets/hashes and original reachable labels in Automata',
                summary=summary))
    print(json.dumps(summary, indent=2))
    return 0 if counts['completed'] == manifest['count'] else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command, handler in [('prepare', prepare), ('analyze', analyze), ('collect', collect)]:
        p = commands.add_parser(command)
        p.add_argument('--run-dir', type=Path, required=True)
        p.set_defaults(handler=handler)
        if command == 'prepare':
            p.add_argument('--timeout', type=baseline.positive, help='Seconds per inventory; new default 300, existing limit retained unless explicitly changed')
        elif command == 'analyze':
            p.add_argument('--task-id', type=baseline.nonnegative, default=0)
            p.add_argument('--batch-size', type=baseline.positive, default=100)
        else:
            p.add_argument('--csv-only', action='store_true')
    args = parser.parse_args()
    try:
        return args.handler(args) or 0
    except (ValueError, RuntimeError, OSError, KeyError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
