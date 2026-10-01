import asyncio
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
def load(name):
 spec=importlib.util.spec_from_file_location(name,ROOT/'src/plugins/sekai'/f'{name}.py')
 m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
suite=load('suite');constants=load('music_constants')
BASE='Song,,Constant,Level,Note Count,Difficulty,Song ID,Notes\nBase,,30.5,30,1000,Master,74,\nAppend,,31.5,31,1000,Append,1,\n'
OVERRIDE='Song,,Constant,Level,Note Count,Difficulty,Song ID,Notes\nNote,,,,,,,header\nOverride,,30.8,30,1000,Master,74,\nUnused,,20.1,20,100,Hard,,\n'

class SuiteTests(unittest.TestCase):
 def test_numeric_enums_and_zero_easy(self):
  p={'userMusicResults':[{'musicId':1,'musicDifficultyType':0,'playResult':0}, {'musicId':'74','musicDifficultyType':4,'fullComboFlg':True,'fullPerfectFlg':False,'playResult':1}]}
  normalized,diag=suite.normalize_music_results(p)
  self.assertEqual(normalized['userMusicResults'][0]['musicDifficultyType'],'easy')
  self.assertTrue(normalized['userMusicResults'][0]['fullPerfectFlg'])
  self.assertEqual(normalized['userMusicResults'][1]['musicDifficultyType'],'master')
  self.assertEqual(p['userMusicResults'][1]['musicDifficultyType'],4)
  self.assertEqual(diag['valid_rows'],2)
 def test_compact_enums_and_nested_records(self):
  p={'compactUserMusicResults':{'__ENUM__':{'musicDifficulty':['append'],'playResult':['full_perfect']},'musicId':[74],'musicDifficulty':[0],'playResult':[0]}}
  rows,diag=suite.best_chart_results(p)
  self.assertTrue(rows[(74,'append')]['fullPerfectFlg'])
  nested={'userMusics':[{'musicId':74,'userMusicDifficultyStatuses':[{'musicDifficultyType':'master','userMusicResults':[{'playResult':'full_combo'}]}]}]}
  rows,_=suite.best_chart_results(nested);self.assertTrue(rows[(74,'master')]['fullComboFlg'])
 def test_best_solo_multi_deduplicates_chart(self):
  rows,_=suite.best_chart_results({'userMusicResults':[{'musicId':74,'musicDifficulty':'expert','playResult':'full_combo','playType':'solo'}, {'musicId':74,'musicDifficultyType':'expert','playResult':'full_perfect','playType':'multi'}]})
  self.assertEqual(len(rows),1);self.assertTrue(rows[(74,'expert')]['fullPerfectFlg'])
 def test_missing_empty_and_bad_data_distinguishable(self):
  self.assertFalse(suite.normalize_music_results({})[1]['present'])
  self.assertTrue(suite.normalize_music_results({'userMusicResults':[]})[1]['present'])
  self.assertEqual(suite.normalize_music_results({'userMusicResults':[{'musicId':1,'musicDifficulty':99}]})[1]['invalid_rows'],1)
 def test_string_false_is_not_true(self):
  rows,_=suite.best_chart_results({'userMusicResults':[{'musicId':74,'musicDifficulty':'master','playResult':'clear','fullComboFlg':'false','fullPerfectFlg':'false'}]})
  self.assertFalse(rows[(74,'master')]['fullComboFlg'])

class ConstantsTests(unittest.IsolatedAsyncioTestCase):
 async def test_override_cache_and_failed_refresh_keep_valid_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'cache.json';cache=constants.ConstantsCache(path,['base','override']);calls=[]
   async def fetch(url):calls.append(url);return BASE if url=='base' else OVERRIDE
   data=await cache.get(fetch);self.assertEqual(data[(74,'master')],30.8);self.assertEqual(len(data),2)
   await cache.get(fetch);self.assertEqual(len(calls),2)
   saved=path.read_bytes()
   async def broken(url):raise OSError('offline')
   cache.updated_at=0
   self.assertEqual((await cache.get(broken))[(74,'master')],30.8)
   self.assertEqual(path.read_bytes(),saved)
   restored=constants.ConstantsCache(path,['base','override']);self.assertEqual(restored.data,data)
 async def test_invalid_second_sheet_does_not_publish_partial(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'cache.json';cache=constants.ConstantsCache(path,['base','override'])
   async def fetch(url):return BASE if url=='base' else '<html>login</html>'
   with self.assertRaises(ValueError):await cache.get(fetch)
   self.assertFalse(path.exists());self.assertFalse(cache.data)
 async def test_unknown_columns_and_invalid_constant_rejected(self):
  for raw in ['<html>error</html>',BASE.replace('30.5','NaN')]:
   with self.assertRaises(ValueError):constants.parse_constants_csv(raw)


class B30CalculationTests(unittest.IsolatedAsyncioTestCase):
 async def asyncSetUp(self):
  import ast, types
  from unittest.mock import AsyncMock
  class ReplyException(Exception):pass
  self.ReplyException=ReplyException
  def check(condition,message):
   if not condition:raise ReplyException(message)
  ns={'best_chart_results':suite.best_chart_results,'assert_and_reply':check,
      'is_valid_music':AsyncMock(side_effect=lambda ctx,mid,**kw:mid!=999),
      'get_music_diff_info':AsyncMock(side_effect=lambda ctx,mid:types.SimpleNamespace(level={'master':33 if mid==1 else 32}))}
  tree=ast.parse((ROOT/'src/plugins/sekai/modules/music.py').read_text())
  nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='get_best30_data']
  mod=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+nodes,type_ignores=[])
  exec(compile(ast.fix_missing_locations(mod),'b30-calculation','exec'),ns)
  self.calculate=ns['get_best30_data']
  self.ctx=types.SimpleNamespace(md=types.SimpleNamespace(musics=types.SimpleNamespace(find_by_id=AsyncMock(return_value={'title':'test'}))))
 async def test_numeric_results_best_status_region_filter_and_existing_formula(self):
  rows=[{'musicId':mid,'musicDifficultyType':4,'playResult':play} for mid,play in [(1,1),(2,1),(3,1),(3,0),(4,0),(999,0)]]
  data=await self.calculate(self.ctx,{'userMusicResults':rows},{(1,'master'):33.3,(2,'master'):32.4,(3,'master'):32.2,(999,'master'):40})
  self.assertEqual([r['mid'] for r in data['results']],[1,3,2])
  self.assertAlmostEqual(data['rating'],(32.3+30.9+32.2)/30)
  self.assertEqual(data['missing_constants'],1)
 async def test_bad_missing_empty_and_uncovered_data_never_report_zero(self):
  for p in [{},{'userMusicResults':[]},{'userMusicResults':[{'musicId':1,'musicDifficultyType':99}]},{'userMusicResults':[{'musicId':1,'musicDifficultyType':4,'playResult':0}]}]:
   with self.assertRaises(self.ReplyException):await self.calculate(self.ctx,p,{})
 async def test_normalization_diagnostics_survive_profile_layer(self):
  p,diag=suite.normalize_music_results({'userMusicResults':[{'musicId':1,'musicDifficultyType':99}]})
  p['_music_results_diagnostics']=diag
  with self.assertRaisesRegex(self.ReplyException,'格式无法识别'):await self.calculate(self.ctx,p,{})

if __name__=='__main__':unittest.main()
