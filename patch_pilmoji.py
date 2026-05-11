from pathlib import Path
import site

for site_dir in site.getsitepackages():
    path = Path(site_dir) / "pilmoji" / "helpers.py"
    if path.exists():
        break
else:
    raise SystemExit("pilmoji helpers.py not found")

text = path.read_text()
text = text.replace("from emoji import EMOJI_UNICODE", "import emoji")
text = text.replace(
    "_UNICODE_EMOJI_REGEX = '|'.join(map(re.escape, sorted(EMOJI_UNICODE['en'].values(), key=len, reverse=True)))",
    "_UNICODE_EMOJI_REGEX = '|'.join(map(re.escape, sorted((data['en'] for data in emoji.EMOJI_DATA.values() if 'en' in data), key=len, reverse=True)))",
)
path.write_text(text)
