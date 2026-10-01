"""Chart constants from pjskb30's base sheet plus override sheet.

The upstream region selector changes song names, not constants. Region-specific
sources can be configured when available; otherwise the same chart IDs are used.
"""
import asyncio
import csv
import io
import json
import math
import os
from pathlib import Path
import tempfile
import time

DEFAULT_SOURCES = (
    'https://docs.google.com/spreadsheets/d/1B8tX9VL2PcSJKyuHFVd2UT_8kYlY4ZdwHwg9MfWOPug/export?format=csv&gid=1855810409',
    'https://docs.google.com/spreadsheets/d/1Yv3GXnCIgEIbHL72EuZ-d5q_l-auPgddWi4Efa14jq0/export?format=csv&gid=182216',
)
SUPPORTED_DIFFICULTIES = {'expert', 'master', 'append'}


def parse_constants_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip('\ufeff')))
    headers = set(reader.fieldnames or [])
    if {'Song ID', 'Difficulty', 'Constant'} <= headers:
        id_key, diff_key, value_key = 'Song ID', 'Difficulty', 'Constant'
    elif {'id', 'difficulty', 'constant'} <= headers:
        id_key, diff_key, value_key = 'id', 'difficulty', 'constant'
    else:
        raise ValueError('定数表缺少歌曲ID、难度或定数列')
    result = {}
    for row in reader:
        id_text, diff, value_text = (row.get(id_key) or '').strip(), (row.get(diff_key) or '').strip().lower(), (row.get(value_key) or '').strip()
        # Notes, blank rows and unsupported charts are present in the override sheet.
        if not id_text or not value_text or diff not in SUPPORTED_DIFFICULTIES:
            continue
        try:
            numeric_id = float(id_text)
            value = float(value_text)
        except ValueError as exc:
            raise ValueError('定数表存在无效数值') from exc
        if not numeric_id.is_integer() or numeric_id <= 0 or not math.isfinite(value) or not 0 < value < 50:
            raise ValueError('定数表存在超出范围的ID或定数')
        result[(int(numeric_id), diff)] = value
    if not result:
        raise ValueError('定数表没有可用谱面，保留旧缓存')
    return result


class ConstantsCache:
    def __init__(self, path, sources=DEFAULT_SOURCES):
        self.path = Path(path)
        self.sources = tuple(sources)
        self.data = {}
        self.updated_at = 0
        self.retry_after = 0
        self.last_error = None
        self.lock = asyncio.Lock()
        try:
            stored = json.loads(self.path.read_text())
            if stored['sources'] == list(self.sources):
                data = {(int(mid), diff): float(value) for mid, diff, value in stored['charts']}
                if data and all(diff in SUPPORTED_DIFFICULTIES and math.isfinite(v) and 0 < v < 50 for (_, diff), v in data.items()):
                    self.data = data
                    self.updated_at = stored['updated_at']
        except (OSError, ValueError, TypeError, KeyError):
            pass

    async def get(self, fetch_text, ttl=21600):
        async with self.lock:
            now = time.time()
            if self.data and (now - self.updated_at < ttl or now < self.retry_after):
                return self.data
            if now < self.retry_after:
                raise ValueError(self.last_error or '定数数据源暂不可用')
            try:
                merged = {}
                for source in self.sources:
                    merged.update(parse_constants_csv(await fetch_text(source)))
                if not merged:
                    raise ValueError('没有配置可用的定数来源')
                payload = {'sources': list(self.sources), 'updated_at': now,
                           'charts': [[mid, diff, value] for (mid, diff), value in sorted(merged.items())]}
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd, temp = tempfile.mkstemp(prefix='.constants-', dir=self.path.parent)
                try:
                    with os.fdopen(fd, 'w') as stream:
                        json.dump(payload, stream, ensure_ascii=False)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, self.path)
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
                self.data, self.updated_at = merged, now
                self.last_error = None
                self.retry_after = 0
            except Exception as exc:
                self.last_error = str(exc)
                self.retry_after = now + 300
                if not self.data:
                    raise
            return self.data
