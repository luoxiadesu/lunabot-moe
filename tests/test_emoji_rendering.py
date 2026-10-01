"""Run with bot requirements; image assertions use an offline emoji source."""
import ast
import inspect
import io
from pathlib import Path
import unittest
from unittest.mock import patch

import emoji
from PIL import Image, ImageFont
from pilmoji import Pilmoji
import pilmoji.core as core
import pilmoji.helpers as helpers
from pilmoji.source import BaseSource

from patch_pilmoji import patch_helpers

ROOT = Path(__file__).resolve().parents[1]


def patched_helpers():
    namespace = {}
    exec(compile(patch_helpers(inspect.getsource(helpers)), 'patched-helpers', 'exec'), namespace)
    return namespace


class EmojiRenderingTests(unittest.TestCase):
    def test_original_and_broken_patch_are_repaired_idempotently(self):
        declarations = [
            "from emoji import EMOJI_UNICODE\n_UNICODE_EMOJI_REGEX = '|'.join(map(re.escape, sorted(EMOJI_UNICODE['en'].values(), key=len, reverse=True)))",
            "import emoji\n_UNICODE_EMOJI_REGEX = '|'.join(map(re.escape, sorted((data['en'] for data in emoji.EMOJI_DATA.values() if 'en' in data), key=len, reverse=True)))",
        ]
        for declaration in declarations:
            text = patch_helpers('import re\n' + declaration)
            self.assertEqual(patch_helpers(text), text)
            ns = {}
            exec(text, ns)
            import re
            self.assertIsNotNone(re.fullmatch(ns['_UNICODE_EMOJI_REGEX'], '😀'))
            self.assertIsNone(re.fullmatch(ns['_UNICODE_EMOJI_REGEX'], ':grinning_face:'))

    def test_unicode_sequences_remain_single_emoji_nodes(self):
        ns = patched_helpers()
        for value in ['😀', '🎉', '❤️', '🇨🇳', '👨‍👩‍👧‍👦', '👍🏽', '1️⃣', '🫠']:
            nodes = ns['to_nodes'](value)[0]
            self.assertEqual([(node.type.name, node.content) for node in nodes], [('emoji', value)])
        self.assertEqual(ns['to_nodes'](':grinning_face:')[0][0].type.name, 'text')

    def test_painter_detects_multicodepoint_only_emoji(self):
        tree = ast.parse((ROOT/'src/plugins/draw/painter.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'has_emoji')
        ns = {'emoji': emoji}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'painter-has-emoji', 'exec'), ns)
        for value in ['🇨🇳', '1️⃣', '你好 👨‍👩‍👧‍👦', '👍🏽']:
            self.assertTrue(ns['has_emoji'](value))
        for value in ['中文 English 123', ':grinning_face:', '']:
            self.assertFalse(ns['has_emoji'](value))

    def test_pilmoji_pastes_assets_instead_of_font_boxes(self):
        class Source(BaseSource):
            def __init__(self): self.requested = []
            def get_emoji(self, value):
                self.requested.append(value)
                stream = io.BytesIO()
                Image.new('RGBA', (16, 16), (255, 0, 0, 255)).save(stream, format='PNG')
                stream.seek(0)
                return stream
            def get_discord_emoji(self, value): return None

        font_paths = [ROOT/'data/utils/fonts/SourceHanSansCN-Regular.otf',
                      Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
        font_path = next((p for p in font_paths if p.exists()), None)
        if font_path is None: self.skipTest('a TrueType/OpenType test font is required')
        font = ImageFont.truetype(str(font_path), 32)
        ns = patched_helpers()
        source = Source()
        target = Image.new('RGB', (400, 64), 'white')
        with patch.object(core, 'to_nodes', ns['to_nodes']), patch.object(core, 'NodeType', ns['NodeType']):
            with Pilmoji(target, source=source) as painter:
                painter.text((0, 0), '😀🇨🇳👍🏽👨‍👩‍👧‍👦', font=font)
        self.assertEqual(source.requested, ['😀', '🇨🇳', '👍🏽', '👨‍👩‍👧‍👦'])
        self.assertGreater(sum(pixel == (255, 0, 0) for pixel in target.getdata()), 1000)


class EmojiAssetTests(unittest.TestCase):
    def test_fallback_then_disk_cache_work_without_network(self):
        import importlib.util, tempfile
        spec = importlib.util.spec_from_file_location('emoji_source', ROOT/'src/plugins/draw/emoji_source.py')
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        image = io.BytesIO()
        Image.new('RGBA', (16, 16), 'red').save(image, format='PNG')
        payload = image.getvalue()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(source, '_download', side_effect=[TimeoutError(), payload]) as download:
                self.assertEqual(source._load_asset('❤️', directory, 1), payload)
                self.assertEqual(download.call_count, 2)
                self.assertIn('/2764/128.png', download.call_args.args[0])
            source._load_asset.cache_clear()
            with patch.object(source, '_download', side_effect=AssertionError('must be offline')):
                self.assertEqual(source._load_asset('❤️', directory, 2), payload)

    def test_corrupt_file_replaced_and_failures_back_off(self):
        import importlib.util, tempfile
        spec = importlib.util.spec_from_file_location('emoji_source', ROOT/'src/plugins/draw/emoji_source.py')
        source = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(source)
        image = io.BytesIO()
        Image.new('RGBA', (16, 16), 'red').save(image, format='PNG')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'1f600.png'
            path.write_bytes(b'<html>error</html>')
            with patch.object(source, '_download', return_value=image.getvalue()):
                self.assertEqual(source._load_asset('😀', directory, 1), image.getvalue())
            self.assertEqual(path.read_bytes(), image.getvalue())
            with patch.object(source, '_download', side_effect=TimeoutError()) as download:
                self.assertIsNone(source._load_asset('🫠', directory, 1))
                self.assertIsNone(source._load_asset('🫠', directory, 1))
                self.assertEqual(download.call_count, 2)
                self.assertIsNone(source._load_asset('🫠', directory, 2))
                self.assertEqual(download.call_count, 4)


if __name__ == '__main__':
    unittest.main()
