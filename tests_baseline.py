"""Regression checks for generation, certified bounds, and incomplete results."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import baseline


class GenerationTests(unittest.TestCase):
    def test_original_ten_automata(self):
        # SHA-256 values measured from the generator in the alife-2026 tag.
        expected = [
            '90997a7634b6b588fa2695050165cba9529dedb35de78ba9d964b6f6cc745456',
            '134d90cdab36d30f3fd47455bac5e239d58a6f658b387a5c331fb2822b2ffeef',
            '35a6af5ec4b7d9e8335e5ea2818a6b5edb9c00d0da3068f6c9ebaa9122700302',
            'b322ddbf305dbc1ed2c31f39052aec05199f984e2b5d7d9e0f441ab96407936d',
            '8bf90b4fc0c25b1df5442ab4fbbdbc8d9aa6894a7c92f65f49f1ea94f8f6dd7c',
            '97883ddee30c8631c9d783c5c273f446f49ac2981881e199de82f1940feec65e',
            '3c1a04649b4f7cdc04a56c12f924f73adcb927ae64fb6cda1382f86256386274',
            'd3508538caa6a92e3a4f2c2d9123ffa608e1b455701fe1e02c439b5fe3ccda3f',
            'fae6b3503113819554faca7bdde61a6dda0fcb42d4fd7058779c3ab640df7197',
            'df15a61765fc825fad6fcbab8e949214046211d12a0cc2ca87ddf9a1585566a4',
        ]
        module = baseline.load_framework(Path(__file__).with_name('ES-Automata-Fogel.py'))
        for seed, checksum in enumerate(expected):
            automaton = baseline.make_automaton(module, seed)
            data = [[automaton.transitions[s, a], automaton.outputs[s, a]]
                    for s in range(15) for a in automaton.input_alphabet]
            self.assertEqual(hashlib.sha256(json.dumps(data).encode()).hexdigest(), checksum)
            self.assertEqual(automaton.get_reachable_states(), list(range(9)))


class BoundsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.upper = dict(reachable_states=9, holonomy_upper_bound=8, certified_upper_bound=8)

    def tearDown(self):
        self.tmp.cleanup()

    def test_zero_is_valid_but_missing_is_not_zero(self):
        path = self.root / 'bounds.tsv'
        self.assertEqual(baseline.read_fields(path), {})
        path.write_text('lower_bound\t0\nexact\ttrue\nsnapshot_complete\ttrue\n')
        self.assertEqual(baseline.read_fields(path)['lower_bound'], 0)
        path.write_text('lower_bound\t0\n')
        with self.assertRaises(ValueError):
            baseline.read_fields(path)

    def test_certified_progress_and_invalid_intervals(self):
        path = self.root / 'progress.txt'
        path.write_text('Start: degree=9, certified upper=8\n'
                        'NEW CERTIFIED LOWER BOUND 2/8 after 4 edge tests (20 ms)\n'
                        'Witness: {1,2,3} -> {1,2}\n')
        self.assertEqual(baseline.certified_progress(path, self.upper), 2)
        path.write_text(path.read_text().replace('2/8', '9/8'))
        with self.assertRaises(ValueError):
            baseline.certified_progress(path, self.upper)
        with self.assertRaises(ValueError):
            baseline.validate_bounds({**self.upper, 'lower_bound': 9, 'exact': False})
        with self.assertRaises(ValueError):
            baseline.validate_bounds({**self.upper, 'lower_bound': 2, 'exact': True})

    def make_case(self):
        (self.root / 'automata').mkdir()
        data = dict(transitions=[[min(s+1, 8)] * 8 for s in range(15)])
        path = self.root / 'automata' / '00001.json'
        baseline.save_json(path, data)
        metadata = dict(automaton_id=1, seed=0, num_states=15, reachable_states=9,
                        fitness=47.8, automaton_sha256=baseline.digest(path))
        return metadata, dict(gap='unused', gap_memory='1g', sgpdec_dir='unused',
                              sgpdec_commit=baseline.SGPDEC_COMMIT, timeout_seconds=1)

    def fields(self, path, values):
        path.write_text(''.join(f'{key}\t{str(value).lower()}\n' for key, value in values.items()) +
                        'snapshot_complete\ttrue\n')

    def test_completed_case_is_reused(self):
        metadata, config = self.make_case()
        def fake_gap(config, script, log, timeout):
            self.fields(script.parent / 'upper.tsv', self.upper)
            self.fields(script.parent / 'bounds.tsv', dict(lower_bound=2, certified_upper_bound=8,
                        exact=False, search_exhausted=True, edge_tests=4, lower_bound_elapsed_ms=20))
            return 0, False
        with patch.object(baseline, 'run_gap', side_effect=fake_gap) as call:
            self.assertTrue(baseline.analyze_one(self.root, metadata, config))
            self.assertTrue(baseline.analyze_one(self.root, metadata, config))
            self.assertEqual(call.call_count, 1)
        row = baseline.read_json(self.root / 'cases/00001/result.json')
        self.assertEqual(row['lower_bound'], 2)
        self.assertFalse(row['exact'])

    def test_timeout_keeps_certificate_and_retry_keeps_logs(self):
        metadata, config = self.make_case()
        def fake_gap(config, script, log, timeout):
            self.fields(script.parent / 'upper.tsv', self.upper)
            (script.parent / 'lower-progress.txt').write_text(
                'Start: degree=9, certified upper=8\n'
                'NEW CERTIFIED LOWER BOUND 2/8 after 4 edge tests (20 ms)\n')
            return -9, True
        with patch.object(baseline, 'run_gap', side_effect=fake_gap):
            self.assertFalse(baseline.analyze_one(self.root, metadata, config))
            self.assertFalse(baseline.analyze_one(self.root, metadata, config))
        row = baseline.read_json(self.root / 'cases/00001/result.json')
        self.assertEqual((row['status'], row['lower_bound']), ('timeout', 2))
        self.assertTrue((self.root / 'cases/00001/attempt-0001/lower-progress.txt').exists())
        self.assertTrue((self.root / 'cases/00001/attempt-0002').exists())

    def test_missing_result_is_failed_not_zero(self):
        metadata, config = self.make_case()
        with patch.object(baseline, 'run_gap', return_value=(0, False)):
            self.assertFalse(baseline.analyze_one(self.root, metadata, config))
        row = baseline.read_json(self.root / 'cases/00001/result.json')
        self.assertEqual(row['status'], 'failed')
        self.assertNotIn('lower_bound', row)

    def test_worker_ranges_cover_partial_last_batch(self):
        rows = [{'automaton_id': i} for i in range(1, 24)]
        seen = []
        with patch.object(baseline, 'read_manifest', return_value={'count': 23}), \
             patch.object(baseline, 'read_json', return_value={'sgpdec_dir': '.', 'sgpdec_commit': baseline.SGPDEC_COMMIT}), \
             patch.object(baseline, 'check_sgpdec'), \
             patch.object(baseline, 'metadata_rows', return_value=rows), \
             patch.object(baseline, 'analyze_one', side_effect=lambda root, row, config: seen.append(row['automaton_id']) or True):
            for index in range(3):
                baseline.analyze(argparse.Namespace(run_dir=self.root, task_id=index, batch_size=10))
        self.assertEqual(seen, list(range(1, 24)))

    def test_collect_preserves_pending_rows(self):
        metadata, config = self.make_case()
        rows = [metadata, {**metadata, 'automaton_id': 2, 'seed': 1}]
        baseline.save_json(self.root / 'analysis.json', config)
        with patch.object(baseline, 'read_manifest', return_value={'count': 2}), \
             patch.object(baseline, 'metadata_rows', return_value=rows), \
             contextlib.redirect_stdout(io.StringIO()):
            status = baseline.collect(argparse.Namespace(run_dir=self.root, csv_only=False))
        self.assertEqual(status, 2)
        summary = baseline.read_json(self.root / 'summary.json')
        self.assertEqual(summary['statuses'], {'pending': 2})
        self.assertEqual(summary['intervals'], 0)
        from openpyxl import load_workbook
        workbook = load_workbook(self.root / 'baseline_results.xlsx')
        self.assertEqual(workbook['Automata'].max_row, 3)
        self.assertEqual(workbook['Automata']['E2'].value, None)
        self.assertEqual(workbook['Automata'].tables['AutomataResults'].ref, 'A1:R3')


if __name__ == '__main__':
    unittest.main()
