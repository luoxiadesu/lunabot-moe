import ast
import math
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
tree=ast.parse((ROOT/'src/plugins/sekai/modules/event.py').read_text())
ns={'math':math}
nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ['event_record_rank','sort_event_records']]
exec(compile(ast.Module(body=nodes,type_ignores=[]),'event-history','exec'),ns)

class EventHistoryTests(unittest.TestCase):
    def test_null_ranks_sort_after_valid_ranks(self):
        rows=[{'eventId':1,'rank':None,'eventPoint':100}, {'eventId':2,'rank':10,'eventPoint':None}, {'eventId':3,'eventPoint':200}, {'eventId':4,'rank':1,'eventPoint':50}]
        sorted_rows,has_rank=ns['sort_event_records'](rows)
        self.assertTrue(has_rank)
        self.assertEqual([x['eventId'] for x in sorted_rows],[4,2,3,1])
        self.assertEqual(rows[0]['eventId'],1)
        self.assertIsNone(rows[0]['rank'])

    def test_all_unranked_uses_points(self):
        rows=[{'eventId':1,'rank':None,'eventPoint':None}, {'eventId':2,'rank':0,'eventPoint':200}, {'eventId':3,'eventPoint':50}]
        sorted_rows,has_rank=ns['sort_event_records'](rows)
        self.assertFalse(has_rank)
        self.assertEqual([x['eventId'] for x in sorted_rows],[2,3,1])

    def test_nonfinite_and_invalid_ranks_are_unknown(self):
        for value in [None,0,-1,float('nan'),float('inf'),'10',True]:
            self.assertIsNone(ns['event_record_rank']({'rank':value}))
        self.assertEqual(ns['event_record_rank']({'rank':10}),10)

if __name__=='__main__':unittest.main()
