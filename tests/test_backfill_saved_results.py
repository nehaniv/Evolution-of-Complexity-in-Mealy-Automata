import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import EvolutionaryTimeline as t
import BackfillPermutators as b
from test_permutator_inventory import snapshot, HOLO_LOG, PERM_LOG

SOFTWARE = dict(gap_version='4.16.1', semigroups_version='5.6.3', sgpdec_sha='commit',
                sgpdec_diff_sha256='clean', untracked_sha256={},
                gap_executable='/mac/gap', sgpdec_path='/mac/sgpdec')


def fixture(root):
    path = root / 'snapshots/run_001/gen_000000.json'
    t.atomic_json(path, snapshot())
    t.atomic_json(root / 'config.json', dict(runs=1, record_generations=[0]))
    t.atomic_json(root / 'evolution_complete.json', {})
    t.atomic_json(root / 'software/software.json', SOFTWARE)
    code = t.gap_program(snapshot())
    job = root / 'nibi_analysis/batch-test/jobs/123_00001'
    job.mkdir(parents=True)
    (job / 'analysis.g').write_text(code)
    (job / 'analysis.log').write_text(HOLO_LOG)
    t.atomic_json(job / 'result.json', dict(signature=b.sha_text(t.digest(path) + code),
                  snapshot_sha256=t.digest(path), row={'status':'completed'},
                  software=dict(SOFTWARE, gap_executable='/nibi/gap', sgpdec_path='/nibi/pkg/sgpdec'),
                  log_sha256=t.digest(job / 'analysis.log')))
    return path, job


class SavedBoundsTests(unittest.TestCase):
    def test_relocated_nibi_log_is_reparsed_not_row_trusted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path, job = fixture(root)
            result = t.read_json(job / 'result.json')
            result['row']['complexity_lower'] = 999
            t.atomic_json(job / 'result.json', result)
            row, source = b.recover_bounds(root, path, SOFTWARE, b.index_nibi(root))
            self.assertEqual(row['complexity_lower'], 1)
            self.assertEqual(source['source'], 'Nibi task log')

    def test_modified_evidence_is_rejected(self):
        for alteration in ('snapshot', 'log', 'script', 'software', 'snapshot_sha', 'marker'):
            with self.subTest(alteration=alteration), tempfile.TemporaryDirectory() as d:
                root = Path(d); path, job = fixture(root)
                result = t.read_json(job / 'result.json')
                if alteration == 'snapshot':
                    snap = t.read_json(path); snap['best_fitness'] = 10; t.atomic_json(path,snap)
                elif alteration == 'log': (job / 'analysis.log').write_text(HOLO_LOG+'changed')
                elif alteration == 'script': (job / 'analysis.g').write_text('different')
                elif alteration == 'software': result['software']['sgpdec_sha'] = 'different'
                elif alteration == 'snapshot_sha': result['snapshot_sha256'] = 'different'
                else:
                    (job / 'analysis.log').write_text(HOLO_LOG.replace('URA_DONE',''))
                    result['log_sha256'] = t.digest(job / 'analysis.log')
                t.atomic_json(job / 'result.json', result)
                row, source = b.recover_bounds(root, path, SOFTWARE, b.index_nibi(root))
                self.assertIsNone(source)
                self.assertEqual(row['complexity_lower'], '')

    def test_local_failed_parser_cache_can_recover_complete_log(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); path, _ = fixture(root)
            stem = root / 'gap/run_001/gen_000000'
            stem.parent.mkdir(parents=True)
            code = t.gap_program(snapshot())
            stem.with_suffix('.g').write_text(code)
            stem.with_suffix('.log').write_text(HOLO_LOG.replace('|2|C2|','|\n2\n|C2|'))
            key = b.sha_text(t.digest(path)+code+b.sha_text(json.dumps(SOFTWARE,sort_keys=True)))
            t.atomic_json(stem.with_suffix('.result.json'),dict(cache_key=key,row={'status':'failed'}))
            row, source = b.recover_bounds(root,path,SOFTWARE,{})
            self.assertEqual(row['status'],'completed')
            self.assertEqual(source['source'],'original local log')

    def test_check_only_does_not_call_gap_or_write(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with patch('sys.argv',['BackfillPermutators.py',str(root),'--check_only']), patch.object(t,'gap_run') as gap:
                self.assertEqual(b.main(),0); gap.assert_not_called()
            self.assertEqual(before,{str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_run_reuses_bounds_then_reuses_permutator_log(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); fixture(root)
            before = {str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
            def gap(executable,script,log,timeout):
                self.assertNotIn('MaxChainOfEssentialDependency(URA_SK)',script.read_text())
                log.write_text(PERM_LOG)
                return PERM_LOG
            def probe(out,executable):
                t.atomic_json(out/'software.json',SOFTWARE)
                return SOFTWARE
            with patch('sys.argv',['BackfillPermutators.py',str(root)]), patch.object(t,'software_probe',side_effect=probe), patch.object(t,'gap_run',side_effect=gap) as run:
                self.assertEqual(b.main(),0)
                self.assertEqual(b.main(),0)
                self.assertEqual(run.call_count,1)
            for name, contents in before.items(): self.assertEqual((root/name).read_bytes(),contents)
            import openpyxl
            book=openpyxl.load_workbook(root/'permutator_backfill/experiment_results.xlsx')
            self.assertEqual(book['Permutator groups'].max_row,2)
            book.close()
            # Corrupt the inventory log: it must be recalculated, not trusted.
            log=root/'permutator_backfill/gap/run_001/gen_000000.permutators.log'
            log.write_text('corrupt')
            with patch('sys.argv',['BackfillPermutators.py',str(root)]), patch.object(t,'software_probe',side_effect=probe), patch.object(t,'gap_run',side_effect=gap) as run:
                self.assertEqual(b.main(),0)
                self.assertEqual(run.call_count,1)

    def test_missing_bounds_are_skipped_without_search(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); fixture(root)
            snap=snapshot();snap['generation']=1
            t.atomic_json(root/'snapshots/run_001/gen_000001.json',snap)
            def gap(executable,script,log,timeout):
                log.write_text(PERM_LOG);return PERM_LOG
            with patch('sys.argv',['BackfillPermutators.py',str(root)]), patch.object(t,'software_probe',return_value=SOFTWARE), patch.object(t,'gap_run',side_effect=gap) as run:
                self.assertEqual(b.main(),1)
                self.assertEqual(run.call_count,1)
            import csv
            with (root/'permutator_backfill/timeline.csv').open() as f: rows=list(csv.DictReader(f))
            self.assertEqual(rows[1]['permutator_status'],'pending')
            self.assertEqual(rows[1]['non_solvable_permutator_occurrences'],'')


class WrappedGroupTests(unittest.TestCase):
    def test_wrapped_holonomy_and_permutators(self):
        h,depth=t.parse_groups(HOLO_LOG.replace('|2|C2|','|\n2\n|C2|'),1)
        for text in (PERM_LOG.replace('|2|2|C2|','|2|\n2\n|C2|'),
                     PERM_LOG.replace('(1,2)','(1,\\\n 2)')):
            groups=t.parse_permutators(text,2,h,depth)
            self.assertEqual(groups[0]['order'],2)

    def test_error_incomplete_and_duplicate_completion_rejected(self):
        h,depth=t.parse_groups(HOLO_LOG,1)
        for text in (PERM_LOG.replace('|true\n','|\n'),
                     PERM_LOG+'URA_PERMUTATORS_DONE\n', 'Error, failure\n'+PERM_LOG):
            with self.subTest(text=text),self.assertRaises(ValueError):t.parse_permutators(text,2,h,depth)
        with self.assertRaises(ValueError):t.parse_bounds(HOLO_LOG+'URA_DONE\n',2)


if __name__ == '__main__': unittest.main()
