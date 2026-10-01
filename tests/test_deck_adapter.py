"""Run with the service requirements installed, without importing bot plugins."""
import ast
import asyncio
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / 'src/services/deck_recommender'
sys.path.insert(0, str(SERVICE))
from compat import prepare_musicmetas, validate_candidate_pool, OPTIONAL_MASTERDATA, DATA_SCHEMA_VERSION


def meta(mid=1, diff='master'):
    return dict(music_id=mid, difficulty=diff, music_time=100., event_rate=100.,
                base_score=100., base_score_auto=100., fever_score=100., fever_end_time=60.,
                tap_count=500, skill_score_solo=[1.] * 6, skill_score_auto=[2.] * 6,
                skill_score_multi=[3.] * 6)


class MetadataTests(unittest.TestCase):
    def test_incomplete_rows_excluded_and_average_not_corrupted(self):
        good=meta();bad=dict(meta(707),event_rate=None);rows=[good,bad]
        before=deepcopy(rows)
        out,skipped=prepare_musicmetas(rows)
        self.assertEqual(rows,before)
        self.assertEqual(skipped,[(707,'master')])
        synthetic=[m for m in out if m['music_id']==10000]
        self.assertEqual(len(synthetic),6)
        self.assertTrue(all(m['event_rate']==100 for m in synthetic))
        self.assertEqual(prepare_musicmetas(out)[0],out)

    def test_invalid_arrays_and_nonfinite_numbers_are_rejected(self):
        for changes in [dict(base_score=float('nan')),dict(skill_score_solo=[1]),dict(event_rate=True)]:
            out,skipped=prepare_musicmetas([meta(),dict(meta(2),**changes)])
            self.assertEqual(len(skipped),1)
        with self.assertRaises(ValueError):prepare_musicmetas([dict(meta(),event_rate=None)])

    def test_empty_challenge_rejected_before_native_call(self):
        cards={1:dict(id=1,characterId=17,cardRarityType='rarity_1')}
        u={'userCards':[{'cardId':1}]}
        with self.assertRaisesRegex(ValueError,'可用卡牌不足'):
            validate_candidate_pool({'live_type':'challenge','challenge_live_character_id':1},u,cards)
        cards[2]=dict(id=2,characterId=17,cardRarityType='rarity_1')
        u['userCards'].append({'cardId':2})
        validate_candidate_pool({'live_type':'challenge','challenge_live_character_id':17,'member':2},u,cards)

    def test_disabled_rarity_and_fixed_virtual_card(self):
        cards={i:dict(id=i,characterId=i,cardRarityType='rarity_1') for i in range(1,6)}
        u={'userCards':[{'cardId':i} for i in cards]}
        validate_candidate_pool({'live_type':'multi'},u,cards)
        with self.assertRaises(ValueError):
            validate_candidate_pool({'live_type':'multi','rarity_1_config':{'disable':True}},u,cards)
        validate_candidate_pool({'live_type':'multi','fixed_cards':[5]}, {'userCards':[{'cardId':i} for i in range(1,5)]},cards)


try:
    import sekai_deck_recommend_cpp as engine
    import serve
    import worker
    from fastapi import HTTPException
    HAS_ENGINE=True
except ImportError:
    HAS_ENGINE=False


@unittest.skipUnless(HAS_ENGINE,'install deck service requirements to test Haruki binding')
class EngineContractTests(unittest.TestCase):
    def test_options_and_result_fields_used_by_bot(self):
        o=engine.DeckRecommendOptions.from_dict({'region':'cn','live_type':'multi','music_id':74,'music_diff':'expert','algorithm':'dfs_ga','limit':8,'rarity_4_config':{'skill_max':True},'single_card_configs':[{'card_id':1,'level_max':True}]})
        self.assertEqual(engine.DeckRecommendOptions(o).to_dict(),o.to_dict())
        for algorithm in ['dfs','ga','dfs_ga','rl','sa']:
            o.algorithm=algorithm
            self.assertEqual(engine.DeckRecommendOptions.from_dict(o.to_dict()).algorithm,algorithm)
        for field in ['score','live_score','mysekai_event_point','total_power','event_bonus_rate','support_deck_bonus_rate','cards']:
            self.assertTrue(hasattr(engine.RecommendDeck(),field),field)

    def test_schema_change_forces_master_and_music_resync_and_stable_update_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'deckrec.json';db.write_text(json.dumps({'masterdata_version':{'cn':'180'},'musicmetas_update_ts':{'cn':100}}))
            with patch.object(serve,'DB_PATH',str(db)),patch.object(serve,'DATA_DIR',tmp):
                with self.assertRaises(HTTPException) as e:
                    serve.update_data('cn','180',{},100,None,DATA_SCHEMA_VERSION)
                self.assertEqual(set(e.exception.detail['missing_data']),{'masterdata','musicmetas'})
                serve.update_data('cn','180',{name+'.json':b'[]' for name in OPTIONAL_MASTERDATA},100,b'[]',DATA_SCHEMA_VERSION)
                previous=db.stat().st_mtime_ns
                serve.update_data('cn','180',{},100,None,DATA_SCHEMA_VERSION)
                self.assertEqual(previous,db.stat().st_mtime_ns)



@unittest.skipUnless(HAS_ENGINE, 'install deck service requirements for result aggregation')
class BotAggregationTests(unittest.IsolatedAsyncioTestCase):
    async def test_mixed_batch_uses_individual_sort_target_and_limit(self):
        import types
        from contextlib import nullcontext
        tree = ast.parse((ROOT / 'src/plugins/sekai/modules/deck.py').read_text())
        names = {'do_deck_recommend_batch', 'get_deck_hash'}
        nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        module = ast.fix_missing_locations(ast.Module(body=[future] + nodes, type_ignores=[]))
        def deck(score, power, cid):
            d = engine.RecommendDeck()
            d.score, d.total_power = score, power
            c = engine.RecommendCard(); c.card_id = cid
            d.cards = [c]
            return d.to_dict()
        rows = [dict(result={'decks': [deck(200, 100, 1), deck(100, 200, 2)]},
                     alg='dfs', cost_time=0.1, wait_time=0) for _ in range(2)]
        responses = iter([{'userdata_hash': 'test'}, rows])
        class Response:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def json(self): return next(responses)
        session = types.SimpleNamespace(post=lambda *a, **k: Response())
        namespace = dict(RECOMMEND_SERVERS_CFG=types.SimpleNamespace(get=lambda: [{'url':'http://local','weight':1}]),
                         _deckrec_request_id=0, get_client_session=lambda: session,
                         add_payload_segment=lambda parts, data: parts.append(data),
                         build_multiparts_payload=lambda parts: b''.join(parts),
                         dumps_json=lambda obj, **kwargs: json.dumps(obj),
                         ProfileTimer=lambda *a: nullcontext(), ReplyException=ValueError,
                         DeckRecommendResult=engine.DeckRecommendResult,
                         logger=types.SimpleNamespace(warning=lambda *a: None))
        exec(compile(module, 'bot-aggregation', 'exec'), namespace)
        score = engine.DeckRecommendOptions.from_dict(dict(region='cn',live_type='multi',music_id=74,music_diff='expert',target='score',algorithm='dfs',limit=1))
        power = engine.DeckRecommendOptions(score); power.target='power'
        result = await namespace['do_deck_recommend_batch'](types.SimpleNamespace(region='cn'), [score,power], b'{}')
        self.assertEqual(result[0][0].decks[0].score, 200)
        self.assertEqual(result[1][0].decks[0].total_power, 200)
        self.assertEqual([len(x[0].decks) for x in result], [1,1])


@unittest.skipUnless(HAS_ENGINE,'install deck service requirements to test workers')
class WorkerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        worker.WorkerContext.init_workers(1)
        self.data=json.dumps({'userGamedata':{},'userAreas':[],'userCards':[], 'userCharacters':[], 'userHonors':[], 'userMysekaiCanvases':[], 'userMysekaiFixtureGameCharacterPerformanceBonuses':[], 'userMysekaiGates':[]}).encode()

    async def asyncTearDown(self):
        worker.WorkerContext.shutdown()

    async def test_crashed_process_is_rebuilt_and_accepts_next_request(self):
        async with worker.WorkerContext() as ctx:
            first=await ctx.cache_userdata(self.data)
            self.assertEqual(first['status'],'success')
            old=worker.WorkerContext.all_processes[0]
            old.kill();await asyncio.to_thread(old.join,2)
            second=await ctx.cache_userdata(self.data)
            self.assertEqual(second['userdata_hash'],first['userdata_hash'])
            self.assertNotEqual(old.pid,worker.WorkerContext.all_processes[0].pid)

    async def test_concurrent_rpc_responses_do_not_cross(self):
        ctx=next(worker.WorkerContext.workers())
        data2=json.loads(self.data);data2['userGamedata']={'userId':2}
        b=json.dumps(data2).encode()
        a1,a2=await asyncio.gather(ctx.cache_userdata(self.data),ctx.cache_userdata(b))
        from hashlib import md5
        self.assertEqual(a1['userdata_hash'],md5(self.data).hexdigest())
        self.assertEqual(a2['userdata_hash'],md5(b).hexdigest())

    async def test_timeout_rebuilds_process_not_only_queues(self):
        async with worker.WorkerContext() as ctx:
            await ctx.cache_userdata(self.data)
            old=worker.WorkerContext.all_processes[0]
            import os,signal
            os.kill(old.pid,signal.SIGSTOP)
            ctx.task_timeout=.3
            with self.assertRaises(TimeoutError):await ctx.cache_userdata(self.data)
            self.assertNotEqual(old.pid,worker.WorkerContext.all_processes[0].pid)
            ctx.task_timeout=10
            self.assertEqual((await ctx.cache_userdata(self.data))['status'],'success')

if __name__=='__main__':unittest.main()
