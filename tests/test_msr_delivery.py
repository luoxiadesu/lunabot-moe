import asyncio
import ast
from datetime import datetime
import importlib.util
from pathlib import Path
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('msr_delivery', ROOT / 'src/plugins/sekai/msr_delivery.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def event(**changes):
    now = int(time.time() * 1000)
    return dict(version=1, event_id='test-event', region='cn', uid='7488916117617056521', upload_time=now, received_at=now, **changes)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / 'queue.sqlite3')
        self.store = mod.DeliveryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def enqueue(self, ts=1100, context='latest:', cycle=1000):
        return self.store.enqueue('cn', '123', 12, 34, cycle, ts, context)

    def test_duplicate_events_and_durable_restart(self):
        e = event()
        self.assertTrue(self.store.receive(e))
        self.assertFalse(self.store.receive(e))
        self.enqueue()
        self.store.claim(1)
        self.store.close()
        self.store = mod.DeliveryStore(self.path)
        self.assertEqual(self.store.events(), [e])
        self.assertEqual(self.store.claim(1)[0]['attempts'], 2)
        self.store.handled(e['event_id'])
        self.assertFalse(self.store.events())

    def test_webhook_and_poll_share_key_and_two_cycles(self):
        self.assertTrue(self.enqueue())
        self.assertFalse(self.enqueue(ts=1200))
        job = self.store.claim(1)[0]
        self.store.finish(job)
        self.assertFalse(self.enqueue(ts=1300))
        self.assertTrue(self.enqueue(ts=2100, cycle=2000))
        self.assertEqual(len(self.store.claim(4)), 1)

    def test_terminal_retry_limit_and_new_upload(self):
        self.enqueue()
        for attempt in range(1, 6):
            job = self.store.claim(1, now=10**12)[0]
            self.assertEqual(job['attempts'], attempt)
            self.assertEqual(self.store.fail(job, 'network', now=0), attempt < 5)
        self.assertFalse(self.enqueue())
        self.assertFalse(self.store.claim(1, now=10**12))
        self.assertTrue(self.enqueue(ts=1200))
        job = self.store.claim(1)[0]
        self.assertEqual(job['attempts'], 1)
        self.store.fail(job, 'incomplete', terminal=True)
        self.assertFalse(self.enqueue(ts=1200))
        self.assertTrue(self.enqueue(ts=1200, context='local:'))

    def test_legacy_completion_is_preserved(self):
        self.store.enqueue('cn', '123', 12, 34, 1000, 1200, 'latest:', completed=True)
        self.assertFalse(self.enqueue(ts=1300))
        self.assertFalse(self.store.claim(4))

    def test_idle_worker_sleeps_until_event_or_due_retry(self):
        self.assertEqual(self.store.next_delay(), 3600)
        self.store.receive(event())
        self.assertEqual(self.store.next_delay(), 0)
        self.store.handled('test-event')
        self.enqueue()
        self.assertEqual(self.store.next_delay(), 0)
        job = self.store.claim(1)[0]
        self.store.fail(job, 'network')
        self.assertTrue(14 <= self.store.next_delay() <= 15)

    def test_old_data_is_rejected(self):
        self.assertFalse(self.enqueue(ts=900))
        self.assertFalse(self.store.claim(1))

    def test_conflicting_id_is_rejected(self):
        e = event()
        self.store.receive(e)
        with self.assertRaises(ValueError):
            self.store.receive(dict(e, uid='1'))


class HTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = mod.DeliveryStore(str(Path(self.tmp.name) / 'q.sqlite3'))
        self.wake = asyncio.Event()
        self.client = TestClient(TestServer(mod.create_webhook_app(self.store, 'secret', self.wake)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.store.close()
        self.tmp.cleanup()

    async def test_auth_validation_duplicate_and_size(self):
        url = '/internal/mysekai/uploaded'
        headers = {'Authorization': 'Bearer secret'}
        e = event()
        r = await self.client.post(url, json=e)
        self.assertEqual(r.status, 401)
        r = await self.client.post(url, json=dict(e, uid=123), headers=headers)
        self.assertEqual(r.status, 400)
        r = await self.client.post(url, json=e, headers=headers)
        self.assertEqual(r.status, 200)
        self.assertEqual((await r.json())['status'], 'accepted')
        self.assertTrue(self.wake.is_set())
        r = await self.client.post(url, json=e, headers=headers)
        self.assertEqual((await r.json())['status'], 'duplicate')
        r = await self.client.post(url, data='x' * 17000, headers=headers)
        self.assertEqual(r.status, 413)

    async def test_persistence_failure_does_not_acknowledge(self):
        def unavailable(_event):
            raise mod.sqlite3.OperationalError('disk unavailable')
        self.store.receive = unavailable
        response = await self.client.post('/internal/mysekai/uploaded', json=event(),
                                          headers={'Authorization': 'Bearer secret'})
        self.assertEqual(response.status, 503)
        self.assertFalse(self.wake.is_set())

    async def test_invalid_or_future_timestamp(self):
        for invalid in (True, -1, int(time.time() * 1000) + 120000):
            with self.assertRaises(ValueError):
                mod.validate_event(dict(event(), upload_time=invalid), int(time.time() * 1000))


# Execute the actual delivery functions without importing the bot's full plugin
# tree, network schedulers, production config, fonts, or NoneBot adapters.
def runtime_functions():
    tree = ast.parse((ROOT / 'src/plugins/sekai/modules/mysekai.py').read_text())
    names = {'_msr_push', '_msr_enqueue', 'msr_auto_push', 'get_mysekai_last_refresh_time_and_reason'}
    nodes = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
    ns = {'datetime': datetime, 'Tuple': tuple, 'SekaiHandlerContext': object}
    from datetime import timedelta
    ns['timedelta'] = timedelta
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'mysekai-delivery-test', 'exec'), ns)
    return ns


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = mod.DeliveryStore(str(Path(self.tmp.name) / 'q.sqlite3'))
        self.ns = runtime_functions()
        self.cycle = int(time.time() * 1000) - 3600000
        self.target = dict(region='cn', uid='123', qid=12, gid=34, mode='latest', context='latest:')
        self.store.enqueue('cn', '123', 12, 34, self.cycle, self.cycle + 100, 'latest:')
        self.job = self.store.claim(1)[0]
        class ReplyException(Exception): pass
        class MsrIdNotMatchException(ReplyException): pass
        class DB:
            def get(self, *args): return {}
            def set(self, *args): pass
        self.ns.update(_msr_store=self.store, _msr_current_target=lambda j: self.target,
            _msr_cycle=lambda *args: self.cycle, time=time, ReplyException=ReplyException,
            MsrIdNotMatchException=MsrIdNotMatchException,
            SekaiHandlerContext=types.SimpleNamespace(from_region=lambda r: types.SimpleNamespace()),
            get_player_bind_id_index=lambda *a: 0,
            get_mysekai_info=AsyncMock(return_value=({'upload_time': self.cycle + 100}, '')),
            compose_mysekai_res_image=AsyncMock(return_value=['image']), get_image_cq=AsyncMock(return_value='cq'),
            get_region_name=lambda r: r, send_group_msg_by_bot=AsyncMock(return_value={'message_id': 1}),
            file_db=DB(), get_exc_desc=str,
            logger=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None))

    async def asyncTearDown(self):
        self.store.close()
        self.tmp.cleanup()

    async def test_success_and_none_send_result(self):
        self.ns['send_group_msg_by_bot'].return_value = None
        await self.ns['_msr_push'](self.job)
        self.assertEqual(self.store.state('cn', '123', 12, self.cycle), 'pending')
        self.ns['send_group_msg_by_bot'].return_value = {'message_id': 42}
        job = self.store.claim(1, now=10**12)[0]
        await self.ns['_msr_push'](job)
        self.assertEqual(self.store.state('cn', '123', 12, self.cycle), 'done')

    async def test_legacy_mirror_failure_does_not_retry_successful_send(self):
        def failed_mirror(*args):
            raise OSError('legacy DB unavailable')
        self.ns['file_db'].set = failed_mirror
        self.ns['logger'].print_exc = lambda *args: None
        await self.ns['_msr_push'](self.job)
        self.assertEqual(self.store.state('cn', '123', 12, self.cycle), 'done')
        self.assertFalse(self.store.claim(4, now=10**12))

    async def test_unsubscribe_or_refresh_during_render_does_not_send(self):
        async def render(*args):
            self.ns['_msr_current_target'] = lambda j: None
            return ['image']
        self.ns['compose_mysekai_res_image'] = render
        await self.ns['_msr_push'](self.job)
        self.ns['send_group_msg_by_bot'].assert_not_awaited()
        self.assertEqual(self.store.state('cn', '123', 12, self.cycle), 'cancelled')

    async def test_retry_keeps_original_cycle_after_send(self):
        old = self.cycle
        async def send(*args):
            self.cycle += 12 * 3600000
            return {'message_id': 42}
        self.ns['send_group_msg_by_bot'] = send
        await self.ns['_msr_push'](self.job)
        self.assertEqual(self.store.state('cn', '123', 12, old), 'done')
        self.assertIsNone(self.store.state('cn', '123', 12, self.cycle))

    async def test_shutdown_cancellation_is_recovered_after_restart(self):
        self.ns['compose_mysekai_res_image'].side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.ns['_msr_push'](self.job)
        self.ns['send_group_msg_by_bot'].assert_not_awaited()
        self.store.close()
        self.store = mod.DeliveryStore(str(Path(self.tmp.name) / 'q.sqlite3'))
        recovered = self.store.claim(1)
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0]['cycle'], self.job['cycle'])

    async def test_incomplete_data_waits_for_new_upload(self):
        self.ns['compose_mysekai_res_image'].side_effect = self.ns['ReplyException']('incomplete')
        await self.ns['_msr_push'](self.job)
        self.assertEqual(self.store.state('cn', '123', 12, self.cycle), 'failed')
        self.ns['send_group_msg_by_bot'].assert_not_awaited()

    async def test_reconcile_deduplicates_and_skips_completed_users(self):
        targets = [self.target, dict(self.target, qid=13), dict(self.target, uid='456', qid=14)]
        self.store.enqueue('cn', '456', 14, 34, self.cycle, self.cycle + 100, 'latest:', completed=True)
        # Existing user 12 is running; user 13 still needs the same game account.
        queued = []
        from types import SimpleNamespace
        self.ns.update(msr_sub=SimpleNamespace(regions=['cn']),
            _msr_targets=lambda r: targets, _msr_import_legacy=lambda *args: None,
            _msr_enqueue=lambda *args: queued.append(args),
            get_gameapi_config=lambda ctx: SimpleNamespace(mysekai_upload_time_api_url='http://upload/api/cn/mysekai/upload_time'),
            request_gameapi=AsyncMock(return_value=[self.cycle + 100]),
            aiohttp=__import__('aiohttp'), _msr_wake=asyncio.Event())
        self.ns['logger'].print_exc = lambda *args: self.fail('reconcile raised unexpectedly')
        await self.ns['msr_auto_push']()
        call = self.ns['request_gameapi'].await_args
        self.assertEqual(call.kwargs['json'], [('123', 'latest')])
        self.assertEqual(call.kwargs['method'], 'POST')
        self.assertEqual(queued, [('cn', '123', self.cycle + 100)])

    async def test_current_cycle_older_than_ten_minutes_can_enqueue(self):
        self.ns.update(_msr_targets=lambda r: [self.target], _msr_import_legacy=lambda *a: None)
        self.ns['_msr_enqueue']('cn', '123', self.cycle - 1)
        self.ns['_msr_enqueue']('cn', '456', self.cycle + 100)
        # Remove fixture job to test a fresh current-cycle upload.
        with self.store.db:
            self.store.db.execute('DELETE FROM jobs')
        self.ns['_msr_enqueue']('cn', '123', self.cycle + 100)
        self.assertEqual(len(self.store.claim(4)), 1)

    async def test_multi_region_refresh_boundaries(self):
        self.ns['is_fifth_anniversary'] = lambda r: False
        self.ns['get_mysekai_refresh_hours'] = lambda ctx: {'cn': (5, 17), 'jp': (4, 16), 'en': (21, 9)}[ctx.region]
        fn = self.ns['get_mysekai_last_refresh_time_and_reason']
        for region, now, expected in [
            ('cn', '2026-10-01T04:59:59', '2026-09-30T17:00:00'),
            ('cn', '2026-10-01T05:00:00', '2026-10-01T05:00:00'),
            ('jp', '2026-10-01T16:00:00', '2026-10-01T16:00:00'),
            ('en', '2026-10-01T08:00:00', '2026-09-30T21:00:00')]:
            value, reason = fn(types.SimpleNamespace(region=region), datetime.fromisoformat(now))
            self.assertEqual(value, datetime.fromisoformat(expected))
            self.assertEqual(reason, 'natural')


if __name__ == '__main__':
    unittest.main()
