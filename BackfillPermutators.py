#!/usr/bin/env python3
"""Add permutators using validated saved bounds only; never rerun evolution or bounds.

Reports and new caches go in EXPERIMENT/permutator_backfill. Original results
are read only. Run --check_only first to check the transferred experiment.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import EvolutionaryTimeline as t

VERSION_KEYS = ('gap_version', 'semigroups_version', 'sgpdec_sha',
                'sgpdec_diff_sha256', 'untracked_sha256')


def same_software(a, b):
    return all(k in a and k in b and a[k] == b[k] for k in VERSION_KEYS)


def sha_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def baseline(snap, rel):
    row = {k: snap[k] for k in t.METRICS + ['init_seed', 'evolution_seed']}
    row.update(snapshot_kind=snap.get('snapshot_kind', 'population_best'),
               checkpoint_reasons=';'.join(snap.get('reasons', [])), snapshot=rel,
               status='pending', error='No matching validated bounds log.', gap_log='',
               state_ceiling=snap['best_reachable_states'] - 1)
    for key in ('complexity_lower', 'complexity_upper', 'holonomy_upper', 'holonomy_number',
                'holonomy_depth', 'holonomy_groups', 'non_solvable_group_occurrences',
                'exact_complexity', 'gap_to_ceiling_min', 'gap_to_ceiling_max',
                'normalized_lower', 'normalized_upper'):
        row[key] = ''
    row.update(permutator_status='pending', permutator_error='', permutator_groups='',
               non_solvable_permutator_occurrences='', permutator_log='')
    return row


def parse_saved(row, text):
    text = t.normalize_gap(text)
    bounds = t.parse_bounds(text, row['best_reachable_states'])
    groups, depth = t.parse_groups(text, bounds['holonomy_upper'])
    return dict(row, **bounds, status='completed', error='',
                holonomy_number=bounds['holonomy_upper'], holonomy_depth=depth,
                holonomy_groups=json.dumps(groups),
                non_solvable_group_occurrences=sum(not g['solvable'] for g in groups))


def index_nibi(root):
    index = {}
    for path in sorted(root.glob('nibi_analysis/batch*/jobs/*/result.json')):
        try:
            result = t.read_json(path)
            if result['row']['status'] == 'completed':
                index.setdefault(result['signature'], []).append((path, result))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return index


def recover_bounds(root, path, expected, candidates):
    snap = t.read_json(path)
    rel = str(path.relative_to(root))
    base = baseline(snap, rel)
    code = t.gap_program(snap)
    snap_sha = t.digest(path)
    signature = sha_text(snap_sha + code)
    # A local log is tied to its inputs by the original cache key and script.
    stem = root / 'gap' / path.parent.name / path.stem
    try:
        result = t.read_json(stem.with_suffix('.result.json'))
        key = sha_text(snap_sha + code + sha_text(json.dumps(expected, sort_keys=True)))
        if result.get('cache_key') == key and stem.with_suffix('.g').read_text() == code:
            log = stem.with_suffix('.log')
            row = parse_saved(base, log.read_text())
            row['gap_log'] = str(log.relative_to(root))
            return row, dict(source='original local log', log=row['gap_log'],
                             log_sha256=t.digest(log), software=expected)
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Nibi task outputs remain in their original locations and are reparsed.
    for result_path, result in reversed(candidates.get(signature, [])):
        try:
            if result['snapshot_sha256'] != snap_sha or not same_software(result['software'], expected):
                continue
            log = result_path.parent / 'analysis.log'
            if t.digest(log) != result['log_sha256'] or (result_path.parent / 'analysis.g').read_text() != code:
                continue
            row = parse_saved(base, log.read_text())
            row['gap_log'] = str(log.relative_to(root))
            return row, dict(source='Nibi task log', log=row['gap_log'],
                             log_sha256=t.digest(log), software=result['software'])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return base, None


def cached_permutators(stem, key, snap, bounds):
    try:
        result = t.read_json(stem.with_suffix('.permutators.result.json'))
        log = stem.with_suffix('.permutators.log')
        if (result.get('cache_key') != key or result.get('status') != 'completed'
                or result.get('log_sha256') != t.digest(log)
                or stem.with_suffix('.permutators.g').read_text() != t.permutator_program(snap)):
            return None
        return t.parse_permutators(log.read_text(), snap['best_reachable_states'],
                                  json.loads(bounds['holonomy_groups']), bounds['holonomy_depth'])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_reports(out, cfg, rows, provenance):
    t.save_csv(out / 'timeline.csv', rows)
    for name, key, status, fields in [
        ('holonomy_groups', 'holonomy_groups', 'status',
         ['order', 'structure', 'generators', 'trivial', 'solvable']),
        ('permutator_groups', 'permutator_groups', 'permutator_status',
         ['domain', 'degree', 'order', 'structure', 'generators', 'trivial', 'solvable'])]:
        groups = [dict(run=r['run'], generation=r['generation'], snapshot_kind=r['snapshot_kind'], **g)
                  for r in rows if r[status] == 'completed' for g in json.loads(r[key])]
        t.save_csv(out / (name + '.csv'), groups,
                   ['run', 'generation', 'snapshot_kind', 'level', 'representative_index', 'representative_set'] + fields)
    t.atomic_json(out / 'bounds_provenance.json', provenance)
    t.export_spreadsheet(out, cfg)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('experiment', type=Path)
    p.add_argument('--gap', default='gap')
    p.add_argument('--check_only', action='store_true', help='Validate saved bounds without starting GAP or writing reports')
    p.add_argument('--limit', type=int, help='Maximum new permutator calculations this invocation (for a smoke test)')
    p.add_argument('--gap_timeout', type=int, default=0, help='Seconds per permutator calculation; 0 means no limit')
    args = p.parse_args()
    if args.gap_timeout < 0 or (args.limit is not None and args.limit < 1):
        p.error('Timeout must be nonnegative; limit must be positive')
    root = args.experiment.resolve()
    if not (root / 'evolution_complete.json').is_file():
        p.error('Use the complete saved experiment directory, including snapshots and GAP results')
    cfg = t.read_json(root / 'config.json')
    expected = t.read_json(root / 'software/software.json')
    paths = t.snapshots_for(root, cfg)
    candidates = index_nibi(root)
    rows, provenance = [], []
    for path in paths:
        row, source = recover_bounds(root, path, expected, candidates)
        rows.append(row)
        provenance.append(dict(snapshot=row['snapshot'], snapshot_sha256=t.digest(path), source=source))
    count = sum(r['status'] == 'completed' for r in rows)
    print(f'Validated saved bounds: {count}/{len(rows)}. No bounds calculations will be run.', flush=True)
    for row in rows:
        if row['status'] != 'completed':
            print(f"Missing bounds: run {row['run']}, generation {row['generation']}, {row['snapshot_kind']}", flush=True)
    if args.check_only:
        return 0 if count else 1
    if not count:
        raise ValueError('No validated bounds found. Check that the raw Nibi jobs and original software metadata were transferred.')
    out = root / 'permutator_backfill'
    out.mkdir(exist_ok=True)
    with (out / 'backfill.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        snapshots = out / 'snapshots'
        if not snapshots.exists():
            snapshots.symlink_to('../snapshots', target_is_directory=True)
        if snapshots.resolve() != root / 'snapshots':
            raise ValueError('Backfill snapshots path points to a different experiment')
        actual = t.software_probe(out / 'software', args.gap)
        if not same_software(actual, expected):
            raise ValueError('Software differs from the original experiment; inspect both software/software.json files')
        runner_sha, helper_sha = t.digest(t.__file__), t.digest(__file__)
        try:
            commit = subprocess.check_output(['git', '-C', str(Path(__file__).parent), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = 'unavailable (source hashes recorded)'
        for source in (Path(t.__file__), Path(__file__)):
            shutil.copy2(source, out / source.name)
        report_cfg = dict(cfg, analysis_execution='Validated saved bounds plus separate permutator backfill',
                          analysis_source_directory=str(root), analysis_provenance='bounds_provenance.json',
                          analysis_commit=commit, analysis_runner_sha256=runner_sha, analysis_helper_sha256=helper_sha)
        t.atomic_json(out / 'backfill_config.json', report_cfg)
        software_key = sha_text(json.dumps(actual, sort_keys=True))
        started = 0
        try:
            for i, (path, row) in enumerate(zip(paths, rows), 1):
                if row['status'] != 'completed':
                    row['permutator_error'] = 'Skipped because validated bounds/holonomy inventory are missing.'
                    continue
                snap = t.read_json(path)
                if t.digest(path) != provenance[i-1]['snapshot_sha256']:
                    raise ValueError(f'Snapshot changed during backfill: {path}')
                stem = out / 'gap' / path.parent.name / path.stem
                stem.parent.mkdir(parents=True, exist_ok=True)
                code = t.permutator_program(snap)
                key = sha_text(t.digest(path) + code + software_key)
                row['permutator_log'] = str(stem.with_suffix('.permutators.log').relative_to(out))
                groups = cached_permutators(stem, key, snap, row)
                if groups is None:
                    if args.limit is not None and started >= args.limit:
                        continue
                    started += 1
                    print(f"PERMUTATORS {i}/{len(rows)}: run {row['run']}, generation {row['generation']}", flush=True)
                    # Preserve earlier failed/interrupted attempts before replacing their files.
                    for suffix in ('.permutators.g', '.permutators.log', '.permutators.result.json'):
                        old = stem.with_suffix(suffix)
                        if old.exists():
                            backup = old.with_name(old.name + '.previous-' + t.digest(old)[:16])
                            if not backup.exists():
                                shutil.copy2(old, backup)
                    stem.with_suffix('.permutators.g').write_text(code)
                    try:
                        text = t.gap_run(actual['gap_executable'], stem.with_suffix('.permutators.g'),
                                         stem.with_suffix('.permutators.log'), args.gap_timeout)
                        groups = t.parse_permutators(text, snap['best_reachable_states'],
                                                     json.loads(row['holonomy_groups']), row['holonomy_depth'])
                    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                        row.update(permutator_status='failed', permutator_error=str(error))
                        t.atomic_json(stem.with_suffix('.permutators.result.json'),
                                      dict(cache_key=key, status='failed', error=str(error)))
                        print(f'  FAILED: {error}', flush=True)
                        continue
                    t.atomic_json(stem.with_suffix('.permutators.result.json'),
                                  dict(cache_key=key, status='completed',
                                       log_sha256=t.digest(stem.with_suffix('.permutators.log')),
                                       software=actual, runner_sha256=runner_sha))
                row.update(permutator_status='completed', permutator_error='',
                           permutator_groups=json.dumps(groups),
                           non_solvable_permutator_occurrences=sum(not g['solvable'] for g in groups))
        finally:
            save_reports(out, report_cfg, rows, provenance)
        done = sum(r['permutator_status'] == 'completed' for r in rows)
        print(f'Permutator inventories: {done}/{len(rows)}; saved bounds: {count}/{len(rows)}', flush=True)
        print(f'Reports: {out}', flush=True)
        return 0 if done == len(rows) else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Interrupted. Rerun the same command to reuse validated completed inventories.', file=sys.stderr)
        raise SystemExit(130)
