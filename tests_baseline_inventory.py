"""Supplementary inventories; set SGPDEC_TEST_GAP for live GAP integration."""
import argparse
import contextlib
import csv
import io
import json
import os
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

import baseline
import baseline_inventory as inventory


PAIR_LOG = '''group\t1\t1\t[ true, true, true, true ]\t1\t1\t[ () ]\ttrue\t[ 1, 2, 3, 4 ]\t4\t4\tC2 x C2\t[ (1,2), (3,4) ]\ttrue
group\t2\t1\t[ true, true, false, false ]\t2\tC2\t[ (1,2) ]\ttrue\t[ 1, 2 ]\t2\t2\tC2\t[ (1,2) ]\ttrue
reachable_states\t4
holonomy_depth\t2
holonomy_group_bearing_levels\t1
group_count\t2
inventory_complete\ttrue
'''


class InventoryUnitTests(unittest.TestCase):
    def parse(self, text, n=4):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'groups.tsv'
            path.write_text(text)
            return inventory.parse_inventory(path, n)

    def test_paired_groups_and_strict_quotient(self):
        result = self.parse(PAIR_LOG)
        self.assertEqual(result['holonomy_groups'][0]['order'], 1)
        self.assertEqual(result['holonomy_groups'][0]['structure'], '1')
        self.assertEqual(result['permutator_groups'][0]['order'], 4)
        self.assertEqual(result['non_solvable_group_occurrences'], 0)
        self.assertEqual(result['non_solvable_permutator_occurrences'], 0)

    def test_incomplete_or_inconsistent_groups_are_rejected(self):
        bad = [PAIR_LOG.replace('inventory_complete\ttrue', ''),
               PAIR_LOG.replace('group_count\t2', 'group_count\t3'),
               PAIR_LOG.replace('reachable_states\t4', 'reachable_states\t5'),
               PAIR_LOG.replace('[ 1, 2 ]\t2', '[ 1, 3 ]\t2'),
               PAIR_LOG.replace('\t4\tC2 x C2', '\t0\tC2 x C2'),
               PAIR_LOG.replace('\t2\tC2\t[ (1,2) ]\ttrue\n', '\t3\tC3\t[ (1,2,3) ]\ttrue\n'),
               PAIR_LOG + PAIR_LOG.splitlines()[0] + '\n',
               PAIR_LOG.replace('\ttrue\t[ 1, 2 ]', '\tfalse\t[ 1, 2 ]')]
        for text in bad:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_one_state_empty_inventory(self):
        text = ('reachable_states\t1\nholonomy_depth\t0\nholonomy_group_bearing_levels\t0\n'
                'group_count\t0\ninventory_complete\ttrue\n')
        self.assertEqual(self.parse(text, 1)['permutator_groups'], [])

    def test_retry_timeout_preserves_completed_cache_key(self):
        metadata = dict(automaton_sha256='abcdef')
        before = inventory.inventory_key(metadata, dict(timeout_seconds=10, gap_version='4.16.1'))
        after = inventory.inventory_key(metadata, dict(timeout_seconds=100, gap_version='4.16.1'))
        self.assertEqual(before, after)
        self.assertNotEqual(before, inventory.inventory_key(metadata, dict(timeout_seconds=10, gap_version='4.17')))

    def test_reachability_uses_actual_initial_state_and_labels(self):
        data = dict(num_states=4, initial_state=3, reachable_states=2,
                    input_alphabet=['a'], output_alphabet=['0'],
                    transitions=[[0],[3],[2],[1]], outputs=[['0']] * 4)
        states, gens = inventory.reachable_action(data)
        self.assertEqual(states, [1,3])
        self.assertEqual(gens, [[2,1]])
        data['reachable_states'] = 3
        with self.assertRaises(ValueError):
            inventory.reachable_action(data)

    def test_performance_does_not_consume_randomness(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'run'
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.generate(argparse.Namespace(run_dir=root, count=1, seed_start=0))
            data = baseline.read_automaton(root, baseline.metadata_rows(root)[0])
            framework = baseline.load_framework(root / 'source/ES-Automata-Fogel.py')
            env = framework.EnvironmentDFA(8, ['0', '1'], variant='SimpleHardestEnvironment')
            before = random.getstate()
            result = inventory.performance(data, framework, env)
            self.assertEqual(before, random.getstate())
            self.assertAlmostEqual(result['state_cost'], 7.2)
            self.assertEqual(result['unpenalized_performance'], sum(result['transitions_per_start']))
            self.assertEqual(len(result['transitions_per_start']), 8)

    def test_timeout_preserves_performance_and_retries_without_zero_counts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'run'
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.generate(argparse.Namespace(run_dir=root, count=1, seed_start=0))
            destination = root / 'inventory'
            (destination / 'source').mkdir(parents=True)
            metadata = baseline.metadata_rows(root)[0]
            framework = baseline.load_framework(root / 'source/ES-Automata-Fogel.py')
            env = framework.EnvironmentDFA(8, ['0', '1'], variant='SimpleHardestEnvironment')
            config = dict(gap='unused', sgpdec_dir='unused', gap_memory='1g', timeout_seconds=1)
            with patch.object(baseline, 'run_gap', return_value=(-9, True)) as gap, contextlib.redirect_stdout(io.StringIO()):
                for _ in range(2):
                    self.assertFalse(inventory.analyze_one(root, destination, metadata, config, framework, env))
                self.assertEqual(gap.call_count, 2)
            result = baseline.read_json(destination / 'cases/00001/result.json')
            self.assertEqual(result['inventory_status'], 'timeout')
            self.assertEqual(result['performance_status'], 'completed')
            self.assertNotIn('non_solvable_group_occurrences', result)
            self.assertNotIn('non_solvable_permutator_occurrences', result)
            self.assertTrue((destination / 'cases/00001/attempt-0001/inventory.g').exists())
            self.assertTrue((destination / 'cases/00001/attempt-0002/inventory.g').exists())


@unittest.skipUnless(os.environ.get('SGPDEC_TEST_GAP'), 'Set SGPDEC_TEST_GAP for live GAP/SgpDec integration')
class InventoryIntegrationTests(unittest.TestCase):
    def test_existing_run_backfill_export_and_cache(self):
        # This is a small temporary fixture, not an experimental sample.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'run'
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.generate(argparse.Namespace(run_dir=root, count=3, seed_start=0))
            config = dict(gap=os.environ['SGPDEC_TEST_GAP'], gap_memory='1g',
                          sgpdec_dir=os.environ['SGPDEC_TEST_DIR'],
                          sgpdec_commit=baseline.SGPDEC_COMMIT, timeout_seconds=120)
            baseline.save_json(root / 'analysis.json', config)
            before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with contextlib.redirect_stdout(io.StringIO()):
                inventory.prepare(argparse.Namespace(run_dir=root, timeout=120))
                # No lower-bound calculation is authorized by this supplementary pass.
                with patch.object(baseline, 'analyze_one', side_effect=AssertionError('Unexpected bounds search')):
                    self.assertEqual(inventory.analyze(argparse.Namespace(run_dir=root, task_id=0, batch_size=2)), 0)
                with patch.object(baseline, 'run_gap', side_effect=AssertionError('Unexpected inventory cache miss')):
                    self.assertEqual(inventory.analyze(argparse.Namespace(run_dir=root, task_id=0, batch_size=2)), 0)
                    inventory.prepare(argparse.Namespace(run_dir=root, timeout=240))
                    self.assertEqual(inventory.analyze(argparse.Namespace(run_dir=root, task_id=0, batch_size=2)), 0)
                self.assertEqual(inventory.collect(argparse.Namespace(run_dir=root, csv_only=False)), 2)
            for path, contents in before.items():
                self.assertEqual((root / path).read_bytes(), contents)
            out = root / 'inventory'
            with (out / 'baseline_inventory_results.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 3)
            self.assertEqual([r['inventory_status'] for r in rows], ['completed', 'completed', 'pending'])
            self.assertEqual([r['gap_status'] for r in rows], ['pending'] * 3)
            self.assertNotEqual(rows[0]['U'], '')
            self.assertEqual(rows[2]['non_solvable_group_occurrences'], '')
            self.assertIn('Hamiltonian', rows[0]['sampling'])
            from openpyxl import load_workbook
            book = load_workbook(out / 'baseline_inventory_results.xlsx', read_only=True)
            self.assertEqual(set(book.sheetnames), {'Automata','Holonomy groups','Permutator groups','Group distribution','Parameters'})
            self.assertEqual(len(list(book['Automata'].values)), 4)
            book.close()

            # Simulate a completed numeric bounds record to test the join. The
            # lower bound 0 is universally valid and is only a test fixture here.
            metadata = baseline.metadata_rows(root)[0]
            upper = int(rows[0]['U'])
            result = dict(metadata, sgpdec_commit=config['sgpdec_commit'], status='complete',
                          holonomy_upper_bound=int(rows[0]['holonomy_group_bearing_levels']),
                          certified_upper_bound=upper, lower_bound=0, exact=upper == 0,
                          search_exhausted=False, edge_tests=0, lower_bound_elapsed_ms=0,
                          attempt='cases/00001/attempt-0001')
            case = root / 'cases/00001'
            (case / 'attempt-0001').mkdir(parents=True)
            data = baseline.read_automaton(root, metadata)
            gens = baseline.reachable_generators(data, 9)
            script = case / 'attempt-0001/analyze.g'
            script.write_text('AnalyzeBaseline([' + ','.join('Transformation('+json.dumps(g)+')' for g in gens) + '],9,"fixture");')
            baseline.save_json(case / 'result.json', result)
            bounds_bytes = (case / 'result.json').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                inventory.collect(argparse.Namespace(run_dir=root, csv_only=True))
            with (out / 'baseline_inventory_results.csv').open() as f:
                joined = next(csv.DictReader(f))
            self.assertEqual((joined['gap_status'], joined['L']), ('completed', '0'))
            self.assertEqual((case / 'result.json').read_bytes(), bounds_bytes)
            # A previous fixed-state analysis must not be reused for a different
            # reachable action, even if its numeric interval looks plausible.
            script.write_text('AnalyzeBaseline([Transformation([1,2,3,4,5,6,7,8,9])],9,"wrong");')
            invalid = inventory.bounds_for(root, metadata, config)
            self.assertEqual(invalid['gap_status'], 'invalid')
            self.assertIn('differs from the actual reachable action', invalid['bounds_error'])
            self.assertNotIn('L', invalid)

    def test_live_a5_and_strict_quotient(self):
        examples = [([[2,3,4,5,1],[2,3,1,4,5]], 60),
                    ([[2,1,3,4],[1,2,4,3],[1,2,1,2],[3,4,3,4]], 4)]
        config = dict(gap=os.environ['SGPDEC_TEST_GAP'], gap_memory='1g',
                      sgpdec_dir=os.environ['SGPDEC_TEST_DIR'])
        with tempfile.TemporaryDirectory() as d:
            for i, (gens, order) in enumerate(examples):
                n = len(gens[0])
                script, result, log = [Path(d) / f'case{i}.{ext}' for ext in ('g','tsv','log')]
                script.write_text(baseline.gap_prelude(config) +
                    f'Read({json.dumps(str(Path(inventory.__file__).with_suffix(".g")))});\n' +
                    'BaselineInventory([' + ','.join('Transformation('+json.dumps(g)+')' for g in gens) +
                    f'],{n},{json.dumps(str(result))});\nQUIT;\n')
                code, timeout = baseline.run_gap(config, script, log, 120)
                self.assertEqual((code, timeout), (0, False), log.read_text())
                groups = inventory.parse_inventory(result, n)
                self.assertEqual(groups['permutator_groups'][0]['order'], order)
                if order == 60:
                    self.assertEqual(groups['non_solvable_group_occurrences'], 1)
                    self.assertEqual(groups['non_solvable_permutator_occurrences'], 1)
                else:
                    self.assertEqual(groups['holonomy_groups'][0]['order'], 1)


if __name__ == '__main__':
    unittest.main()
