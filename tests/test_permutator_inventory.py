"""Run with python -m unittest discover -s tests -v.

Set SGPDEC_TEST_GAP to a GAP executable with SgpDec for the algebra smoke test.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import EvolutionaryTimeline as timeline


def snapshot():
    # Reachable states are 0,2; state 1 is unreachable. Input a swaps 0 and 2.
    s = {k: 0 for k in timeline.METRICS}
    s.update(run=1, generation=0, best_reachable_states=2, init_seed=1,
             evolution_seed=2, snapshot_kind='population_best', reasons=['scheduled'],
             automaton=dict(num_states=3, initial_state=0, input_alphabet=['a'],
                            output_alphabet=['0'], transitions=[[0,'a',2],[1,'a',1],[2,'a',0]],
                            outputs=[[i,'a','0'] for i in range(3)]))
    return s


HOLO_LOG = '''URA_GROUP:1|1|[ true, true ]|2|C2|[ (1,2) ]|true
URA_N:2
URA_HOLO:1
URA_DEPTH:1
URA_GROUP_COUNT:1
URA_LB:1
URA_DONE
'''
PERM_LOG = '''URA_PERMUTATOR:1|1|[ true, true ]|[ 1, 2 ]|2|2|C2|[ (1,2) ]|true
URA_N:2
URA_DEPTH:1
URA_GROUP_COUNT:1
URA_PERMUTATORS_DONE
'''


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.holonomy, self.depth = timeline.parse_groups(HOLO_LOG, 1)

    def test_pairing_and_coordinate_domain(self):
        groups = timeline.parse_permutators(PERM_LOG, 2, self.holonomy, self.depth)
        self.assertEqual(groups[0]['domain'], '[ 1, 2 ]')
        self.assertEqual(groups[0]['generators'], '[ (1,2) ]')
        self.assertTrue(groups[0]['solvable'])
        code = timeline.permutator_program(snapshot())
        self.assertIn('Transformation([2,1])', code)
        self.assertNotIn('MaxChainOfEssentialDependency(URA_SK)', code)
        self.assertNotIn('DisplayHolonomyComponents', code)

    def test_invalid_inventories_are_rejected(self):
        bad_logs = [
            PERM_LOG.replace('URA_PERMUTATORS_DONE', ''),
            PERM_LOG.replace('URA_GROUP_COUNT:1', 'URA_GROUP_COUNT:2'),
            PERM_LOG.replace('URA_N:2', 'URA_N:3'),
            PERM_LOG.replace('URA_DEPTH:1', 'URA_DEPTH:2'),
            PERM_LOG.replace('[ true, true ]', '[ true, false ]'),
            PERM_LOG.replace('|[ 1, 2 ]|2|', '|[ 1, 1 ]|2|'),
            PERM_LOG.replace('|[ 1, 2 ]|2|', '|[ 1, 3 ]|2|'),
            PERM_LOG.replace('|2|2|C2|', '|2|3|C3|'),  # H must be a quotient of P
            PERM_LOG.replace('|true\n', '|unknown\n'),
            PERM_LOG.splitlines()[0] + '\n' + PERM_LOG,
            '\n'.join(PERM_LOG.splitlines()[1:]),
        ]
        for text in bad_logs:
            with self.subTest(text=text), self.assertRaises(ValueError):
                timeline.parse_permutators(text, 2, self.holonomy, self.depth)

    def test_nonsolvable_quotient_cannot_have_solvable_parent(self):
        h = [dict(self.holonomy[0], solvable=False)]
        with self.assertRaises(ValueError):
            timeline.parse_permutators(PERM_LOG, 2, h, self.depth)

    def test_one_state_has_empty_inventory(self):
        s = snapshot()
        s['automaton']['transitions'][0][2] = 0
        s['best_reachable_states'] = 1
        code = timeline.permutator_program(s)
        self.assertEqual(code.count('QUIT_GAP(0)'), 1)
        self.assertNotIn('MaxChainOfEssentialDependency(URA_SK)', code)
        text = 'URA_N:1\nURA_DEPTH:0\nURA_GROUP_COUNT:0\nURA_PERMUTATORS_DONE\n'
        self.assertEqual(timeline.parse_permutators(text, 1, [], 0), [])

    def test_backfill_reuses_bounds_and_caches_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            path = out / 'snapshots/run_001/gen_000000.json'
            timeline.atomic_json(path, snapshot())
            timeline.atomic_json(out / 'evolution_complete.json', {})
            cfg = dict(runs=1, record_generations=[0])
            software = dict(gap_executable='test-gap')
            software_key = hashlib.sha256(json.dumps(software, sort_keys=True).encode()).hexdigest()
            bounds = {k: snapshot()[k] for k in timeline.METRICS + ['init_seed', 'evolution_seed']}
            bounds.update(timeline.parse_bounds(HOLO_LOG, 2), status='completed',
                          holonomy_number=1, holonomy_depth=1, non_solvable_group_occurrences=0,
                          holonomy_groups=json.dumps(self.holonomy), snapshot_kind='population_best',
                          snapshot=str(path.relative_to(out)))
            key = hashlib.sha256((timeline.digest(path) + timeline.gap_program(snapshot()) + software_key).encode()).hexdigest()
            result = out / 'gap/run_001/gen_000000.result.json'
            timeline.atomic_json(result, dict(cache_key=key, row=bounds))
            original_cache = result.read_bytes()
            with patch.object(timeline, 'gap_run', return_value=PERM_LOG) as gap:
                rows, failed = timeline.analyze(out, cfg, software, 1, False)
                self.assertEqual(gap.call_count, 1)
                self.assertTrue(str(gap.call_args.args[1]).endswith('.permutators.g'))
                self.assertEqual(failed, 0)
                self.assertEqual(rows[0]['non_solvable_permutator_occurrences'], 0)
                timeline.analyze(out, cfg, software, 1, False)
                self.assertEqual(gap.call_count, 1)
            self.assertEqual(result.read_bytes(), original_cache)
            with (out / 'permutator_groups.csv').open() as f:
                self.assertEqual(len(list(csv.DictReader(f))), 1)
            timeline.export_spreadsheet(out, cfg)
            from openpyxl import load_workbook
            book = load_workbook(out / 'experiment_results.xlsx')
            self.assertEqual(book['Permutator groups'].max_row, 2)
            headers = [c.value for c in book['Checkpoints'][1]]
            values = [c.value for c in book['Checkpoints'][2]]
            self.assertEqual(dict(zip(headers, values))['permutator_status'], 'completed')
            book.close()
            # A failed backfill must still expose the previously validated bounds.
            (out / 'gap/run_001/gen_000000.permutators.result.json').unlink()
            with patch.object(timeline, 'gap_run', return_value=PERM_LOG.replace('URA_PERMUTATORS_DONE', '')):
                rows, failed = timeline.analyze(out, cfg, software, 1, False)
            self.assertEqual(failed, 1)
            self.assertEqual(rows[0]['status'], 'completed')
            self.assertEqual(rows[0]['complexity_lower'], 1)
            self.assertEqual(rows[0]['permutator_status'], 'failed')
            self.assertEqual(rows[0]['non_solvable_permutator_occurrences'], '')
            self.assertEqual(result.read_bytes(), original_cache)

    def test_failed_inventory_preserves_bounds_and_has_no_zero_count(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            timeline.atomic_json(path, snapshot())
            stem = Path(directory) / 'gen_000000'
            bounds = dict(holonomy_groups=json.dumps(self.holonomy), holonomy_depth=self.depth)
            with patch.object(timeline, 'gap_run', return_value=PERM_LOG.replace('URA_PERMUTATORS_DONE', '')):
                row = timeline.record_permutators(snapshot(), path, stem, {'gap_executable':'gap'}, '', bounds, 1)
            self.assertEqual(row['permutator_status'], 'failed')
            self.assertEqual(row['non_solvable_permutator_occurrences'], '')
            with patch.object(timeline, 'gap_run', return_value=PERM_LOG) as gap:
                row = timeline.record_permutators(snapshot(), path, stem, {'gap_executable':'gap'}, '', bounds, 1)
            self.assertEqual(gap.call_count, 1)
            self.assertEqual(row['permutator_status'], 'completed')


@unittest.skipUnless(os.environ.get('SGPDEC_TEST_GAP'), 'Set SGPDEC_TEST_GAP for GAP/SgpDec integration')
class AlgebraSmokeTests(unittest.TestCase):
    def test_cyclic_and_nonsolvable_actions(self):
        # A cyclic group and A5 in their natural actions: skeleton has a single
        # non-singleton representative, and P=H has known order/solvability.
        examples = [([[2,3,1]], 3, True),
                    ([[2,3,4,5,1], [2,3,1,4,5]], 60, False)]
        for gens, order, solvable in examples:
            n = len(gens[0])
            s = snapshot()
            s['best_reachable_states'] = n
            s['automaton'].update(num_states=n, input_alphabet=list(range(len(gens))),
                transitions=[[q,i,g[q]-1] for i,g in enumerate(gens) for q in range(n)])
            # Inventory needs only standard SgpDec, not the progress extension.
            with patch.object(timeline, 'GAP_HEADER', 'SizeScreen([4096,100000]);;\nif LoadPackage("SgpDec") <> true then QUIT_GAP(1); fi;\n'):
                code = timeline.permutator_program(s)
            with tempfile.TemporaryDirectory() as directory:
                script = Path(directory) / 'groups.g'
                script.write_text(code)
                text = timeline.gap_run(os.environ['SGPDEC_TEST_GAP'], script, Path(directory) / 'groups.log', 120)
            representative = '[ ' + ', '.join(['true'] * n) + ' ]'
            h = [dict(level=1, representative_index=1, representative_set=representative, order=order, solvable=solvable)]
            groups = timeline.parse_permutators(text, n, h, 1)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]['order'], order)
            self.assertEqual(groups[0]['solvable'], solvable)

    def test_permutator_is_larger_than_holonomy_quotient(self):
        # Two blocks, with independent internal swaps and maps between blocks.
        # The top P is C2 x C2, acting trivially on its two tiles, so top H=1.
        gens = [[2,1,3,4], [1,2,4,3], [1,2,1,2], [3,4,3,4]]
        s = snapshot()
        s['best_reachable_states'] = 4
        s['automaton'].update(num_states=4, input_alphabet=list(range(4)),
            transitions=[[q,i,g[q]-1] for i,g in enumerate(gens) for q in range(4)])
        header = 'SizeScreen([4096,100000]);;\nif LoadPackage("SgpDec") <> true then QUIT_GAP(1); fi;\n'
        with patch.object(timeline, 'GAP_HEADER', header):
            programs = [timeline.gap_program(s), timeline.permutator_program(s)]
        logs = []
        with tempfile.TemporaryDirectory() as directory:
            for i, code in enumerate(programs):
                script = Path(directory) / f'groups_{i}.g'
                script.write_text(code)
                logs.append(timeline.gap_run(os.environ['SGPDEC_TEST_GAP'], script,
                                            script.with_suffix('.log'), 120))
        h, depth = timeline.parse_groups(logs[0], 1)
        p = timeline.parse_permutators(logs[1], 4, h, depth)
        top_h = next(g for g in h if g['level'] == 1)
        top_p = next(g for g in p if g['level'] == 1)
        self.assertEqual(top_h['order'], 1)
        self.assertEqual(top_p['order'], 4)


if __name__ == '__main__':
    unittest.main()
