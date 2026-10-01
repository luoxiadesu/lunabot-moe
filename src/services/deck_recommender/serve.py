from hashlib import md5
from fastapi import FastAPI, HTTPException, Request, Response
import uvicorn
from contextlib import asynccontextmanager
from importlib.metadata import version
from compat import DATA_SCHEMA_VERSION, ENGINE_PACKAGE, ENGINE_VERSION, OPTIONAL_MASTERDATA
from sekai_deck_recommend_cpp import (
    SekaiDeckRecommend, 
    DeckRecommendOptions, 
    DeckRecommendCardConfig, 
    DeckRecommendSingleCardConfig,
    DeckRecommendResult,
    DeckRecommendUserData,
)
from utils import *
from worker import *
from config import *

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass



def update_data(
    region: str, 
    masterdata_version: str, 
    masterdata: dict[str, bytes] | None,
    musicmetas_update_ts: int,
    musicmetas: bytes | None,
    data_schema_version: int = 1,
):
    db = load_json(DB_PATH, default={})

    missing_data = set()

    current_masterdata_version = db.get('masterdata_version', {}).get(region)
    current_schema = db.get('data_schema_version', {}).get(region, 1)
    schema_changed = current_schema != data_schema_version
    if current_masterdata_version != masterdata_version or schema_changed:
        if not masterdata:
            missing_data.add('masterdata')
        else:
            if data_schema_version >= DATA_SCHEMA_VERSION:
                missing_tables = [name for name in OPTIONAL_MASTERDATA if name + '.json' not in masterdata]
                if missing_tables:
                    raise HTTPException(status_code=400, detail=f"缺少新版组卡数据表: {missing_tables}")
            local_md_dir = pjoin(DATA_DIR, 'masterdata', region)
            for name, md in masterdata.items():
                write_file(pjoin(local_md_dir, name), md)
            db.setdefault('masterdata_version', {})[region] = masterdata_version
            log(f"更新 {region} MasterData {current_masterdata_version} -> {masterdata_version}")

    current_musicmetas_update_ts = db.get('musicmetas_update_ts', {}).get(region)
    if current_musicmetas_update_ts != musicmetas_update_ts or schema_changed:
        if not musicmetas:
            missing_data.add('musicmetas')
        else:
            local_mm_path = pjoin(DATA_DIR, f'musicmetas_{region}.json')
            write_file(local_mm_path, musicmetas)
            db.setdefault('musicmetas_update_ts', {})[region] = musicmetas_update_ts
            current_ts_text = datetime.fromtimestamp(current_musicmetas_update_ts).strftime('%Y-%m-%d %H:%M:%S') if current_musicmetas_update_ts else 'None'
            local_ts_text = datetime.fromtimestamp(musicmetas_update_ts).strftime('%Y-%m-%d %H:%M:%S')
            log(f"更新 {region} MusicMetas {current_ts_text} -> {local_ts_text}")

    if not missing_data:
        db.setdefault('data_schema_version', {})[region] = data_schema_version
    if db != load_json(DB_PATH, default={}):
        dump_json(db, DB_PATH)
    if missing_data:
        log(f"{region} 检测到数据更新不完整，缺少：{', '.join(missing_data)}")
        raise HTTPException(status_code=426, detail={
            'missing_data': list(missing_data),
            "message": "缺少必要的数据，请上传完整数据",
        })
        
async def extract_decompressed_payload(request: Request) -> list[bytes]:
    payload = decompress_zstd(await request.body())
    segments = []
    index = 0
    while index < len(payload):
        if index + 4 > len(payload):
            raise HTTPException(status_code=400, detail="数据格式错误")
        segment_size = int.from_bytes(payload[index:index+4], 'big')
        index += 4
        if index + segment_size > len(payload):
            raise HTTPException(status_code=400, detail="数据格式错误")
        segment = payload[index:index+segment_size]
        segments.append(segment)
        index += segment_size
    return segments


# =========================== API =========================== #

@asynccontextmanager
async def lifespan(app):
    installed = version(ENGINE_PACKAGE)
    if installed != ENGINE_VERSION:
        raise RuntimeError(f'Expected {ENGINE_PACKAGE} {ENGINE_VERSION}, got {installed}')
    WorkerContext.init_workers(WORKER_NUM)
    log(f'组卡后端 {ENGINE_PACKAGE} {installed}, workers={WORKER_NUM}')
    try:
        yield
    finally:
        WorkerContext.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get('/health')
async def health():
    return {'status': 'ok', 'engine': ENGINE_PACKAGE, 'version': version(ENGINE_PACKAGE),
            'data_schema_version': DATA_SCHEMA_VERSION,
            'workers': len(WorkerContext.all_processes),
            'alive_workers': sum(p.is_alive() for p in WorkerContext.all_processes.values())}


@app.post("/update_data")
async def _(request: Request):
    try:
        segments = await extract_decompressed_payload(request)

        data = loads_json(segments[0])
        region = data['region']
        masterdata_version      = data['masterdata_version']
        musicmetas_update_ts    = data['musicmetas_update_ts']

        masterdatas: dict[str, bytes] = {}
        musicmetas: bytes = None
        for i in range(1, len(segments), 2):
            key = segments[i].decode('utf-8')
            value = segments[i+1]
            if key == 'musicmetas':
                musicmetas = value
            else:
                masterdatas[key] = value
            
        update_data(region, masterdata_version, masterdatas, musicmetas_update_ts, musicmetas,
                    data.get('data_schema_version', 1))

    except HTTPException as he:
        raise he

    except Exception as e:
        error("更新数据失败")
        raise HTTPException(
            status_code=500, 
            detail=get_exc_desc(e),
        )

@app.post("/cache_userdata")
async def _(request: Request):
    try:
        segments = await extract_decompressed_payload(request)
        userdata_bytes = segments[0]

        t = datetime.now()
        all_result = await asyncio.gather(*[ctx.cache_userdata(userdata_bytes) for ctx in WorkerContext.workers()])
        elapsed = (datetime.now() - t).total_seconds()
        
        for result in all_result:
            if result['status'] != 'success':
                raise HTTPException(
                    status_code=500, 
                    detail=result.get('message', '内部错误'),
                )
            
        userdata_hash = all_result[0]['userdata_hash']
        log(f"缓存用户数据 {userdata_hash} 成功，耗时 {elapsed:.3f} 秒")
        
        return { "userdata_hash": userdata_hash }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        error("缓存用户数据失败")
        raise HTTPException(
            status_code=500, 
            detail=get_exc_desc(e),
        )

@app.post("/recommend")
async def _(request: Request):
    try:
        segments = await extract_decompressed_payload(request)

        data = loads_json(segments[0])
        region = data['region']
        batch_options = data['batch_options']
        userdata_hash = data['userdata_hash']

        async def do_recommend(options):
            start_time = datetime.now()
            async with WorkerContext() as ctx:
                result = await ctx.recommend(region, options, userdata_hash)
        
            if result['status'] != 'success':
                raise HTTPException(
                    status_code=500, 
                    detail=result.get('message', '内部错误'),
                )

            total_time = (datetime.now() - start_time).total_seconds()
            wait_time = total_time - result['cost_time']

            return {
                "result": result['result'],
                "alg": options['algorithm'],
                "cost_time": result['cost_time'],
                "wait_time": wait_time,
            }
            
        return await asyncio.gather(*[do_recommend(options) for options in batch_options])

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        error("组卡请求处理失败")
        raise HTTPException(
            status_code=500, 
            detail=get_exc_desc(e),
        )


if __name__ == "__main__":
    uvicorn.run(
        "serve:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        workers=None,
        timeout_keep_alive=60,
    )
