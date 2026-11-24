"""Uniform sampler, actual-state restriction, and complete pipeline checks."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import baseline
import baseline_inventory as inventory
from uniform_sampling import UNIFORM_SAMPLING, make_uniform_automaton


class UniformTests(unittest.TestCase):
    def test_matches_previously_delivered_ten_uniform_tables(self):
        # Measured from the FULL .g transition/output tables in the earlier ZIP.
        expected = [
            '54ff3513af909ce8e5024cbf797a1051436ecad12b399ab813da97a29beee700',
            'e81d3ce14bafddef74fcef34bc68ba38781f7ae654cad972ebcdc447d4e50549',
            '9a29ab826eb2e440da8b06aefa9baf2b9ea08ae65c90431fa45e0e5528e03ab1',
            '113cb394598c87166863406a743abc869bf0b685ca82ed6bb971f8e7d4ac59a8',
            '7e3ce3836ab3ccff5b56c26b4a3ad408fbad5ef0335590f99564109813d7ccd0',
            'c25c93c9312597aa17258a04540ddd08ce898737b1ad2fa4b2c43aaf026bbbd0',
            '1b439d5ab1ad532fe7b935d30e3f71253dc7b6af48dc954d773f05f2d0e12d3b',
            '274425d4fd642bfd22347578d957c1765b0ab2c7d9b0d7b80b90d61a97efccdd',
            'edff998e98e3c7be9ea32fa0ac3730092c34c7f0c4f65c7347236982339f8510',
            'bd85433cc7a6a694ce6541a5f4760f5574d0fba2943589744bc7c59ebfce6e1a',
        ]
        framework = baseline.load_framework(Path(baseline.__file__).with_name('ES-Automata-Fogel.py'))
        initials, subsets = set(), set()
        for seed, digest in enumerate(expected):
            a = make_uniform_automaton(framework, seed)
            tables = [[a.transitions[q,s], a.outputs[q,s]] for q in range(15) for s in a.input_alphabet]
            self.assertEqual(hashlib.sha256(json.dumps(tables).encode()).hexdigest(), digest)
            states = a.get_reachable_states()
            self.assertEqual(len(states), 9)
            self.assertIn(a.initial_state, states)
            self.assertTrue(all(a.transitions[q,s] in states for q in states for s in a.input_alphabet))
            initials.add(a.initial_state)
            subsets.add(tuple(states))
        self.assertGreater(len(initials), 1)
        self.assertGreater(len(subsets), 1)

    def test_restricts_from_actual_initial_state(self):
        data = dict(initial_state=3, transitions=[[0],[3],[2],[1]])
        self.assertEqual(baseline.reachable_generators(data, 2), [[2,1]])
        with self.assertRaises(ValueError):
            baseline.reachable_generators(data, 3)

    def test_spooled_collector_loads_frozen_sampler(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'uniform'
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.generate(argparse.Namespace(run_dir=root, count=1, seed_start=0, sampling='uniform'))
            spool = Path(directory) / 'slurm-spool'
            spool.mkdir()
            script = spool / 'slurm_script'
            shutil.copy2(root / 'source/baseline_uniform.sh', script)
            env = dict(os.environ, PYTHON=sys.executable, PYTHONPATH='',
                       AUTOMATA_ENV=str(Path(directory) / 'no-environment'))
            result = subprocess.run(['bash', str(script), 'collect', str(root)],
                                    cwd=root, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertEqual(json.loads(result.stdout)['sampling'], UNIFORM_SAMPLING)
            self.assertEqual(baseline.read_json(root / 'summary.json')['statuses'], {'pending': 1})

    def test_named_uniform_entry_point_and_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'uniform'
            env = dict(os.environ, COUNT='2', PYTHON='python3')
            script = Path(baseline.__file__).with_name('baseline_uniform.sh')
            p = subprocess.run(['bash', str(script), 'generate', str(root)], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)
            manifest = baseline.read_manifest(root)
            self.assertEqual(manifest['sampling'], UNIFORM_SAMPLING)
            meta = baseline.metadata_rows(root)
            for row in meta:
                data = baseline.read_automaton(root, row)
                states, gens = inventory.reachable_action(data)
                self.assertEqual(baseline.reachable_generators(data, 9), gens)
                self.assertIn(data['initial_state'], states)
            # Collection gets its label from the manifest, not the legacy constant.
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.collect(argparse.Namespace(run_dir=root, csv_only=False))
            self.assertEqual(baseline.read_json(root / 'summary.json')['sampling'], UNIFORM_SAMPLING)
            from openpyxl import load_workbook
            book = load_workbook(root / 'baseline_results.xlsx', read_only=True)
            self.assertEqual(book['Distribution']['B6'].value, UNIFORM_SAMPLING)
            book.close()
            # Do not silently process a Hamiltonian directory through this entry point.
            legacy = Path(d) / 'legacy'
            with contextlib.redirect_stdout(io.StringIO()):
                baseline.generate(argparse.Namespace(run_dir=legacy, count=1, seed_start=0, sampling='hamiltonian'))
            p = subprocess.run(['bash', str(script), 'collect', str(legacy)], env=env, capture_output=True, text=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('not labelled as the uniform sampler', p.stderr)


@unittest.skipUnless(os.environ.get('SGPDEC_TEST_GAP'), 'Set SGPDEC_TEST_GAP for live integration')
class UniformPipelineTests(unittest.TestCase):
    def test_uniform_bounds_groups_and_export(self):
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()):
            root = Path(d) / 'uniform'
            baseline.generate(argparse.Namespace(run_dir=root, count=1, seed_start=0, sampling='uniform'))
            baseline.preflight(argparse.Namespace(run_dir=root, gap=os.environ['SGPDEC_TEST_GAP'],
                sgpdec_dir=Path(os.environ['SGPDEC_TEST_DIR']), sgpdec_commit=baseline.SGPDEC_COMMIT,
                gap_memory='1g', timeout=5))
            status = baseline.analyze(argparse.Namespace(run_dir=root, task_id=0, batch_size=1))
            self.assertIn(status, (0,1))  # A certified partial bound after timeout is allowed.
            boundfile = root / 'cases/00001/result.json'
            result = baseline.read_json(boundfile)
            self.assertIn(result['status'], ('complete','timeout'))
            self.assertEqual(result['reachable_states'], 9)
            baseline.validate_bounds(result)
            original = boundfile.read_bytes()
            inventory.prepare(argparse.Namespace(run_dir=root, timeout=120))
            self.assertEqual(inventory.analyze(argparse.Namespace(run_dir=root, task_id=0, batch_size=1)), 0)
            self.assertEqual(inventory.collect(argparse.Namespace(run_dir=root, csv_only=False)), 0)
            self.assertEqual(boundfile.read_bytes(), original)
            with (root / 'inventory/baseline_inventory_results.csv').open() as f:
                row = next(csv.DictReader(f))
            self.assertEqual(row['sampling'], UNIFORM_SAMPLING)
            self.assertEqual(row['inventory_status'], 'completed')
            self.assertEqual(int(row['U']), min(int(row['holonomy_group_bearing_levels']), 8))
            self.assertNotEqual(row['non_solvable_group_occurrences'], '')
            self.assertNotEqual(row['non_solvable_permutator_occurrences'], '')


if __name__ == '__main__':
    unittest.main()
