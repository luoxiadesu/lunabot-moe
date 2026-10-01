"""Cached Unicode emoji assets for Pilmoji, with bounded network waits."""
from functools import lru_cache
from io import BytesIO
import logging
import os
from pathlib import Path
import tempfile
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image
from pilmoji.source import BaseSource

logger = logging.getLogger(__name__)
CACHE_DIR = Path('data/utils/emoji_cache')
MAX_BYTES = 1024 * 1024


def _validated(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError('invalid emoji image size')
    with Image.open(BytesIO(data)) as image:
        if image.format != 'PNG' or max(image.size) > 512:
            raise ValueError('invalid emoji image')
        image.verify()
    return data


def _download(url):
    request = Request(url, headers={'User-Agent': 'LunaBot emoji renderer'})
    with urlopen(request, timeout=3) as response:
        return _validated(response.read(MAX_BYTES + 1))


@lru_cache(maxsize=256)
def _load_asset(value, directory, retry_window):
    # retry_window bounds negative caching; successful files survive restarts.
    key = '-'.join(f'{ord(char):x}' for char in value)
    path = Path(directory) / (key + '.png')
    try:
        return _validated(path.read_bytes())
    except (OSError, ValueError, SyntaxError):
        pass
    noto_key = '_'.join(f'{ord(char):04x}' for char in value if ord(char) != 0xfe0f)
    urls = [
        'https://emojicdn.elk.sh/' + quote(value, safe='') + '?style=google',
        f'https://fonts.gstatic.com/s/e/notoemoji/latest/{noto_key}/128.png',
    ]
    for url in urls:
        try:
            data = _download(url)
        except (OSError, ValueError, SyntaxError):
            continue
        # Concurrent drawing workers may fetch the same asset. Atomic replacement
        # prevents partial files; cache failures must not discard a valid image.
        temp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp = tempfile.mkstemp(prefix='.emoji-', dir=path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
            os.replace(temp, path)
        except OSError:
            logger.warning('Could not persist emoji image %s', key)
        finally:
            if temp and os.path.exists(temp):
                os.unlink(temp)
        return data
    logger.warning('Emoji image temporarily unavailable: %s', key)
    return None


class CachedGoogleEmojiSource(BaseSource):
    def get_emoji(self, value, /):
        data = _load_asset(value, str(CACHE_DIR), int(time.monotonic() // 300))
        return BytesIO(data) if data else None

    def get_discord_emoji(self, emoji_id, /):
        # The bot accepts Unicode emoji; QQ messages do not need Discord assets.
        return None
