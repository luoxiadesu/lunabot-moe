import ast
import asyncio
from datetime import datetime
import io
from pathlib import Path
import types
import unittest
from unittest.mock import AsyncMock

ROOT=Path(__file__).resolve().parents[1]
class ReplyException(Exception):pass
class HttpError(Exception):
    def __init__(self,status_code):self.status_code=status_code

def extract(file,names,ns):
    tree=ast.parse((ROOT/file).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in names]
    for n in nodes:n.decorator_list=[]
    module=ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)]+nodes,type_ignores=[]))
    exec(compile(module,file,'exec'),ns)
    return ns

def assert_reply(condition,msg):
    if not condition:raise ReplyException(msg)

class PhotoTests(unittest.IsolatedAsyncioTestCase):
    def setup_namespace(self,photos):
        ns=dict(assert_and_reply=assert_reply,ReplyException=ReplyException,HttpError=HttpError,datetime=datetime,io=io,
                get_mysekai_info=AsyncMock(return_value=({'updatedResources':{'userMysekaiPhotos':photos}},'')),
                get_gameapi_config=lambda ctx:types.SimpleNamespace(mysekai_photo_api_url='http://test/photo'),
                request_gameapi=AsyncMock(return_value=b'img'),Image=types.SimpleNamespace(open=lambda value:'image'))
        return extract('src/plugins/sekai/modules/mysekai.py',['get_mysekai_photo_and_time'],ns)

    async def test_negative_indices_and_bounds(self):
        photos=[{'obtainedAt':1000,'seq':1},{'obtainedAt':2000,'seq':2}]
        ns=self.setup_namespace(photos);ctx=types.SimpleNamespace(region='cn')
        await ns['get_mysekai_photo_and_time'](ctx,1,-1)
        self.assertEqual(ns['request_gameapi'].await_args.kwargs['json']['seq'],2)
        for seq in [0,-3,3]:
            with self.assertRaises(ReplyException):await ns['get_mysekai_photo_and_time'](ctx,1,seq)
        self.assertEqual(ns['request_gameapi'].await_count,1)

    async def test_missing_photos_and_upstream_errors_are_readable(self):
        ns=self.setup_namespace(None)
        with self.assertRaisesRegex(ReplyException,'没有MySekai照片'):
            await ns['get_mysekai_photo_and_time'](types.SimpleNamespace(region='cn'),1,1)
        ns=self.setup_namespace([{'obtainedAt':1000}]);ns['request_gameapi'].side_effect=HttpError(502)
        with self.assertRaisesRegex(ReplyException,'HTTP 502'):
            await ns['get_mysekai_photo_and_time'](types.SimpleNamespace(region='cn'),1,1)

class AliasSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_failed_song_does_not_break_sync_summary(self):
        class DB:
            def backup(self):pass
            def update(self,*args,**kwargs):return ([],[])
        async def download(url):
            if url.endswith('/2'):raise RuntimeError('upstream unavailable')
            return {'music_id':1,'aliases':['test']}
        async def gather(*tasks,**kwargs):return await asyncio.gather(*tasks)
        ns=dict(SyncMusicAliasConfig=types.SimpleNamespace(get=lambda:types.SimpleNamespace(regions=['jp'],url='http://test/{mid}',sync_batch_interval=0,sync_batch_size=2)),
                SekaiHandlerContext=types.SimpleNamespace(from_region=lambda r:types.SimpleNamespace(md=types.SimpleNamespace(musics=types.SimpleNamespace(get=AsyncMock(return_value=[{'id':1},{'id':2}]))))),
                MusicAliasDB=types.SimpleNamespace(get_instance=lambda:DB()),asyncio=asyncio,download_json=download,batch_gather=gather,
                logger=types.SimpleNamespace(info=lambda *a:None,warning=lambda *a:None),get_exc_desc=str)
        extract('src/plugins/sekai/modules/music.py',['sync_music_alias','parse_music_alias_response'],ns)
        await ns['sync_music_alias']()

class WinrateTests(unittest.IsolatedAsyncioTestCase):
    async def test_http_challenge_is_reported_without_html(self):
        ns=dict(download_json=AsyncMock(side_effect=HttpError(403)),HttpError=HttpError,ReplyException=ReplyException)
        extract('src/plugins/sekai/modules/sk.py',['get_winrate_predict_data'],ns)
        with self.assertRaisesRegex(ReplyException,'HTTP 403'):
            await ns['get_winrate_predict_data'](types.SimpleNamespace(region='jp'))


class MusicMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_incomplete_song_does_not_break_other_song_rankings(self):
        from src.services.deck_recommender.compat import is_complete_musicmeta
        good=dict(music_id=74,difficulty='master',music_time=100,event_rate=100,
                  base_score=1,base_score_auto=1,fever_score=.1,fever_end_time=80,
                  tap_count=100,skill_score_solo=[.1]*6,skill_score_auto=[.1]*6,
                  skill_score_multi=[.1]*6)
        bad=dict(good,music_id=707,event_rate=None)
        ns=dict(get_musicmetas_json=lambda r:types.SimpleNamespace(get=AsyncMock(return_value=[good,bad])),
                is_complete_musicmeta=is_complete_musicmeta,
                LEADERBOARD_TARGET_KEYS={'score':'{live_type}_score'},
                LEADERBOARD_ALL_LIVE_TYPES=['solo'],LEADERBOARD_DIFF_PRIORITY={'master':4})
        extract('src/plugins/sekai/modules/music.py',['get_music_leaderboard_data'],ns)
        rows=await ns['get_music_leaderboard_data']('kr',[1]*5,'avg',100,20,100000,True,False,'score','solo')
        self.assertEqual([r['music_id'] for r in rows],[74])
        self.assertEqual(rows[0]['solo_score_rank'],1)
        self.assertFalse(is_complete_musicmeta(dict(good,music_time=0)))

class CaptureStatisticsTests(unittest.TestCase):
    def test_plain_json_and_legacy_zstd(self):
        import json,tempfile,zstandard
        ns=dict(loads_json=json.loads,zstandard=zstandard)
        extract('src/plugins/sekai/modules/profile.py',['load_capture_for_statistics'],ns)
        payload=json.dumps({'local_source':'script'}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            for name,content in [('plain.json',payload),('legacy',zstandard.ZstdCompressor().compress(payload))]:
                path=Path(tmp)/name;path.write_bytes(content)
                self.assertEqual(ns['load_capture_for_statistics'](str(path))['local_source'],'script')


class AliasProtocolTests(unittest.TestCase):
    def test_old_and_new_payloads_and_errors(self):
        ns=extract('src/plugins/sekai/modules/music.py',['parse_music_alias_response'],{})
        parse=ns['parse_music_alias_response']
        self.assertEqual(parse({'music_id':74,'aliases':['test']},74),['test'])
        self.assertEqual(parse({'status':200,'data':{'aliases':['test']}},74),['test'])
        for payload in [{'status':404,'data':{'aliases':[]}}, {'music_id':75,'aliases':[]},
                        {'data':{}}, {'data':{'aliases':[None]}}]:
            with self.assertRaises(ValueError):parse(payload,74)


if __name__ == '__main__':
    unittest.main()
