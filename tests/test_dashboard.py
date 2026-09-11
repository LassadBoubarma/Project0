"""Offline fixtures: verify display accounting without model calls or real results."""
import csv
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from src import dashboard as dash, run

class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=dash.ROOT.parent)
        self.root = Path(self.temp.name)/'project'
        self.root.mkdir()
        for folder in ('src', 'data', 'results'):
            shutil.copytree(dash.ROOT/folder, self.root/folder, ignore=shutil.ignore_patterns('__pycache__','runs'))
        shutil.copyfile(dash.ROOT/'config.json', self.root/'config.json')
        self.patches = [patch.object(dash, 'ROOT', self.root), patch.object(run, 'ROOT', self.root)]
        for p in self.patches: p.start()
        self.cfg = run.read_json(self.root/'config.json')
        self.items, _ = run.load_data('test')
    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()
    def fixture(self, complete=True, split='test', missing=False):
        path=self.root/'results/runs/test-fixture';path.mkdir(parents=True)
        metadata={'settings':self.cfg,'split':split,'complete':complete,
                  'item_ids':[i['id'] for i in self.items]}
        (path/'metadata.json').write_text(json.dumps(metadata))
        (path/'items.json').write_text(json.dumps(self.items))
        with (path/'per_item.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=run.FIELDS);w.writeheader()
            for m in self.cfg['models']:
                for index,item in enumerate(self.items):
                    if missing and m['role']=='local' and index==49:continue
                    r={key:'' for key in run.FIELDS}
                    r.update(role=m['role'],model=m['model'],item_id=item['id'],expected=item['expected'],
                             abbreviation=item['abbreviation'],output=item['expected'],correct='1',status='correct',latency_ms='100')
                    if index==0 and m['role']=='local':r.update(correct='0',status='timeout',output='')
                    if m['provider']=='gemini':r['api_cost_usd']='0.001'
                    w.writerow(r)
        return path
    def test_empty_is_not_zero_accuracy(self):
        data=dash.dashboard_data()
        self.assertFalse(data['comparable'])
        self.assertEqual(len(data['models']),3)
        self.assertTrue(all(m['accuracy'] is None for m in data['models']))
    def test_completed_comparison_ties_and_errors(self):
        self.fixture();data=dash.dashboard_data()
        self.assertTrue(data['comparable'])
        self.assertEqual(data['winners'],['top_api','cheap_api'])
        local=data['models'][2]
        self.assertEqual(local['correct'],49)
        self.assertEqual(local['accuracy'],.98)
        self.assertIsNone(local['cost'])
        self.assertAlmostEqual(data['models'][0]['cost'],1.0)
    def test_incomplete_and_dev_never_declare_winner(self):
        path=self.fixture(complete=False)
        self.assertFalse(dash.dashboard_data()['comparable'])
        meta=json.loads((path/'metadata.json').read_text());meta.update(complete=True,split='dev')
        (path/'metadata.json').write_text(json.dumps(meta))
        self.assertFalse(dash.dashboard_data()['comparable'])
    def test_missing_row_and_path_traversal_rejected(self):
        self.fixture(missing=True)
        self.assertFalse(dash.dashboard_data()['comparable'])
        with self.assertRaises(ValueError):dash.selected_path('../../config.json')
    def test_missing_usage_not_treated_as_free(self):
        self.fixture();data=dash.dashboard_data()
        rows=data['rows'];rows[0]['api_cost_usd']=''
        self.assertIsNone(dash.metrics(rows,self.cfg,50)[0]['cost'])
    def test_local_practice_uses_real_scorer_and_separate_dev_run(self):
        self.cfg['pause_seconds']=0;(self.root/'config.json').write_text(json.dumps(self.cfg))
        items,vocab=run.load_data('dev');prompts=[]
        def fake(model,prompt,cfg):
            index=len(prompts);prompts.append(prompt)
            return {'model':model['model'],'message':{'content':'systolic blood pressure' if index==0 else items[index]['expected']},
                    'eval_count':5,'eval_duration':1000000000,'done_reason':'stop'}
        original=(self.root/'results/per_item.csv').read_bytes()
        with patch.object(run,'request_json',return_value={'models':[{'name':'qwen2.5:1.5b'}]}),patch.object(run,'call_model',side_effect=fake),redirect_stdout(io.StringIO()):dash.local_practice()
        data=dash.dashboard_data()
        self.assertEqual(len(prompts),10)
        self.assertEqual(prompts,[run.prompt_for(i,vocab) for i in items])
        self.assertEqual(data['models'][0]['correct'],9)
        self.assertEqual(data['rows'][0]['status'],'parse_error')
        self.assertFalse(data['comparable'])
        self.assertTrue(data['complete'])
        self.assertEqual(data['scope'],'local_practice')
        self.assertEqual((self.root/'results/per_item.csv').read_bytes(),original)

if __name__=='__main__':unittest.main()
