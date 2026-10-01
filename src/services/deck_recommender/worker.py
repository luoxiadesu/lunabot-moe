from utils import *
from config import *
from compat import validate_candidate_pool, InsufficientCards
import queue
import time

from sekai_deck_recommend_cpp import (
    SekaiDeckRecommend, 
    DeckRecommendOptions, 
    DeckRecommendCardConfig, 
    DeckRecommendSingleCardConfig,
    DeckRecommendResult,
    DeckRecommendUserData,
)
from hashlib import md5
import multiprocessing as mp
import setproctitle


class Worker:
    def log(self, *args, **kwargs):
        log(f"[worker-{self.worker_id}]", *args, **kwargs)

    def error(self, *args, **kwargs):
        error(f"<{self.worker_id}>", *args, **kwargs)

    def __init__(self, worker_id: int, worker_num: int):
        self.worker_id = worker_id
        self.worker_num = worker_num
        self.deckrec_seq_top = worker_id
        self.inited = False

    def init(self):
        if self.inited:
            return
        self.recommender = SekaiDeckRecommend()
        self.masterdata_version: dict[str, str] = {}
        self.musicmetas_update_ts: dict[str, int] = {}
        self.userdata_cache: list[tuple[str, DeckRecommendUserData]] = []
        self.userdata_json = {}
        self.master_cards = {}
        self.music_keys = {}
        self.inited = True

    def _deckrec_options_to_str(self, userdata_hash: str, options: DeckRecommendOptions) -> str:
        def fmtbool(b: bool):
            return int(bool(b))
        def cardconfig2str(cfg: DeckRecommendCardConfig):
            return f"{fmtbool(cfg.disable)}{fmtbool(cfg.level_max)}{fmtbool(cfg.episode_read)}{fmtbool(cfg.master_max)}{fmtbool(cfg.skill_max)}"
        def singlecardcfg2str(cfg: List[DeckRecommendSingleCardConfig]):
            if not cfg:
                return "[]"
            return "[" + ", ".join(f"{c.card_id}:{cardconfig2str(c)}" for c in cfg) + "]"
        log = "("
        log += f"region={options.region}, "
        log += f"userdata_hash={userdata_hash}, "
        log += f"alg={options.algorithm}, "
        log += f"type={options.live_type}, "
        log += f"mid={options.music_id}, "
        log += f"mdiff={options.music_diff}, "
        log += f"eid={options.event_id}, "
        log += f"wl_cid={options.world_bloom_character_id}, "
        log += f"challenge_cid={options.challenge_live_character_id}, "
        log += f"limit={options.limit}, "
        # log += f"member={options.member}, "
        # log += f"rarity1={cardconfig2str(options.rarity_1_config)}, "
        # log += f"rarity2={cardconfig2str(options.rarity_2_config)}, "
        # log += f"rarity3={cardconfig2str(options.rarity_3_config)}, "
        # log += f"rarity4={cardconfig2str(options.rarity_4_config)}, "
        # log += f"rarity_bd={cardconfig2str(options.rarity_birthday_config)}, "
        # log += f"single_card_cfg={singlecardcfg2str(options.single_card_configs)}, "
        log += f"fixed_cards={options.fixed_cards})"
        return log

    def _update_data(self, region: str):
        db = load_json(DB_PATH, default={})
        if not db.get('masterdata_version', {}).get(region) or not db.get('musicmetas_update_ts', {}).get(region):
            raise ValueError('组卡数据未初始化完成，请稍后再试')

        masterdata_version = (db.get('masterdata_version', {}).get(region), db.get('data_schema_version', {}).get(region))
        if self.masterdata_version.get(region) != masterdata_version:
            local_md_dir = pjoin(DATA_DIR, 'masterdata', region)
            self.recommender.update_masterdata(local_md_dir, region)
            self.master_cards[region] = {c['id']: {k: c.get(k) for k in ('id', 'characterId', 'cardRarityType')}
                                         for c in load_json(pjoin(local_md_dir, 'cards.json'))}
            self.masterdata_version[region] = masterdata_version
            self.log(f"加载 {region} MasterData: v{masterdata_version}")

        musicmetas_update_ts = (db.get('musicmetas_update_ts', {}).get(region), db.get('data_schema_version', {}).get(region))
        if self.musicmetas_update_ts.get(region) != musicmetas_update_ts:
            local_mm_path = pjoin(DATA_DIR, f'musicmetas_{region}.json')
            self.recommender.update_musicmetas(local_mm_path, region)
            self.music_keys[region] = {(m['music_id'], m['difficulty']) for m in load_json(local_mm_path)}
            self.musicmetas_update_ts[region] = musicmetas_update_ts
            self.log(f"加载 {region} MusicMetas: {datetime.fromtimestamp(musicmetas_update_ts[0]).strftime('%Y-%m-%d %H:%M:%S')}")

    def cache_userdata(self, userdata_bytes: bytes) -> dict:
        self.init()
        try:
            hash = md5(userdata_bytes).hexdigest()
            for h, _ in self.userdata_cache:
                if h == hash:
                    return {
                        'status': 'success',
                        'userdata_hash': hash,
                    }
            raw = loads_json(userdata_bytes)
            if not isinstance(raw, dict) or not isinstance(raw.get('userCards'), list):
                raise ValueError('用户抓包必须是包含 userCards 的 JSON 对象')
            userdata = DeckRecommendUserData()
            userdata.load_from_bytes(userdata_bytes)
            self.userdata_json[hash] = {'userCards': [{'cardId': c['cardId']} for c in raw['userCards']]}
            self.userdata_cache.append((hash, userdata))
            # self.log(f"缓存用户数据: hash={hash}")
            while len(self.userdata_cache) > USERDATA_CACHE_NUM:
                h, _ = self.userdata_cache.pop(0)
                self.userdata_json.pop(h, None)
                # self.log(f"移除用户数据缓存: hash={h}")
            return {
                'status': 'success',
                'userdata_hash': hash,
            }
        except BaseException as e:
            self.error("缓存用户数据失败:", get_exc_desc(e))
            return {
                'status': 'error',
                'message': get_exc_desc(e),
            }
    
    def recommend(self, region: str, options: dict, userdata_hash: str, userdata_bytes: bytes | None = None) -> dict:
        self.init()
        seq = self.deckrec_seq_top
        self.deckrec_seq_top += self.worker_num
        
        try:
            self._update_data(region)

            if not self.masterdata_version.get(region) or not self.musicmetas_update_ts.get(region):
                return {
                    'status': 'error',
                    'message': '组卡服务端数据未初始化完成，请稍后再试'
                }
            
            user_data = None
            for h, data in self.userdata_cache:
                if h == userdata_hash:
                    user_data = data
                    break
            if user_data is None and userdata_bytes is not None:
                cached = self.cache_userdata(userdata_bytes)
                if cached['status'] != 'success':
                    return cached
                user_data = next(value for key, value in self.userdata_cache if key == userdata_hash)
            if user_data is None:
                return {'status': 'error', 'message': '组卡服务端找不到对应的用户数据缓存，请重新查询'}

            if options.get('region') != region:
                raise ValueError('组卡请求区服不匹配')
            try:
                validate_candidate_pool(options, self.userdata_json[userdata_hash], self.master_cards[region])
            except InsufficientCards:
                # A 26-character challenge batch must still return results for
                # owned characters instead of failing the entire request.
                return {'status': 'success', 'result': {'decks': []}, 'cost_time': 0.0}
            music_key = (options.get('music_id'), options.get('music_diff'))
            if music_key not in self.music_keys[region]:
                raise ValueError('该歌曲难度没有完整的计分数据，请选择其他歌曲')
            options = DeckRecommendOptions.from_dict(options)
            options.user_data = user_data
            self.log(f"组卡任务#{seq}: {self._deckrec_options_to_str(userdata_hash, options)}")

            start_time = datetime.now()
            res = self.recommender.recommend(options)
            cost_time = datetime.now() - start_time

            self.log(f"组卡任务#{seq}完成，耗时 {cost_time.total_seconds():.3f} 秒")

            return {
                'status': 'success',
                'result': res.to_dict(),
                'cost_time': cost_time.total_seconds(),
            }
        except BaseException as e:
            self.error(f"组卡任务#{seq}失败:", get_exc_desc(e))
            return {
                'status': 'error',
                'message': get_exc_desc(e),
            }


class WorkerContext:
    """One outstanding RPC per process; recover processes, not just queues."""
    all_workers = {}
    all_processes = {}
    task_queues = {}
    result_queues = {}
    locks = {}
    available_workers = None
    userdata_bytes = {}
    worker_num = 0

    @staticmethod
    def worker_loop(worker, task_queue, result_queue):
        setproctitle.setproctitle(f'lunabot-deckrec-worker-{worker.worker_id}')
        while True:
            method_name, args = task_queue.get()
            try:
                result = getattr(worker, method_name)(*args)
            except BaseException as e:
                result = {'status': 'error', 'message': get_exc_desc(e)}
            result_queue.put(result)

    @classmethod
    def _start_worker(cls, worker_id):
        ctx = mp.get_context('spawn')
        worker = Worker(worker_id, cls.worker_num)
        tq, rq = ctx.Queue(), ctx.Queue()
        process = ctx.Process(target=cls.worker_loop, args=(worker, tq, rq), daemon=True)
        process.start()
        cls.all_workers[worker_id] = worker
        cls.task_queues[worker_id], cls.result_queues[worker_id] = tq, rq
        cls.all_processes[worker_id] = process

    @classmethod
    def init_workers(cls, worker_num):
        if worker_num < 1:
            raise ValueError('worker_num must be positive')
        setproctitle.setproctitle('lunabot-deckrec-main')
        cls.worker_num = worker_num
        cls.available_workers = asyncio.Queue()
        for i in range(worker_num):
            cls.locks[i] = asyncio.Lock()
            cls._start_worker(i)
            cls.available_workers.put_nowait(i)

    @classmethod
    def _stop_worker(cls, i):
        process = cls.all_processes[i]
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=2)
        for q in (cls.task_queues[i], cls.result_queues[i]):
            q.cancel_join_thread()
            q.close()

    @classmethod
    def shutdown(cls):
        for i in list(cls.all_processes):
            cls._stop_worker(i)
        cls.all_processes.clear()

    def __init__(self, task_timeout=75):
        self.worker_id = None
        self.task_timeout = task_timeout

    async def __aenter__(self):
        if self.available_workers is None:
            raise RuntimeError('WorkerContext.init_workers must be called first')
        self.worker_id = await self.available_workers.get()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.available_workers.put_nowait(self.worker_id)

    @classmethod
    def workers(cls):
        for i in cls.all_workers:
            ctx = cls()
            ctx.worker_id = i
            yield ctx

    async def _request(self, method, *args):
        i = self.worker_id
        # Cache broadcasts and recommendations must never consume one another's
        # responses. Locks cover both submission and result collection.
        async with self.locks[i]:
            if not self.all_processes[i].is_alive():
                await asyncio.to_thread(self._stop_worker, i)
                self._start_worker(i)
            self.task_queues[i].put((method, args))
            deadline = time.monotonic() + self.task_timeout
            try:
                while time.monotonic() < deadline:
                    try:
                        return await asyncio.to_thread(self.result_queues[i].get, True, 0.25)
                    except queue.Empty:
                        if not self.all_processes[i].is_alive():
                            raise RuntimeError('组卡计算进程异常退出，已自动恢复，请重试')
                raise TimeoutError('组卡计算超时，计算进程已重建，请重试')
            except BaseException:
                await asyncio.to_thread(self._stop_worker, i)
                self._start_worker(i)
                raise

    async def cache_userdata(self, userdata_bytes):
        result = await self._request('cache_userdata', userdata_bytes)
        if result.get('status') == 'success':
            key = result['userdata_hash']
            self.userdata_bytes[key] = userdata_bytes
            while len(self.userdata_bytes) > USERDATA_CACHE_NUM:
                self.userdata_bytes.pop(next(iter(self.userdata_bytes)))
        return result

    async def recommend(self, region, options, userdata_hash):
        return await self._request('recommend', region, options, userdata_hash,
                                   self.userdata_bytes.get(userdata_hash))
