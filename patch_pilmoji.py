"""Make the pinned Pilmoji 2.0.0 recognize emoji>=2 Unicode sequences.

Run with the same Python interpreter used by the bot after installing its
requirements. Safe to rerun on either the original package or our older patch.
"""
from pathlib import Path
import re
import site


def patch_helpers(text: str) -> str:
    # EMOJI_DATA keys are actual Unicode emoji (😀); values['en'] are names
    # (:grinning_face:), which must never be used as the Unicode matcher.
    text = text.replace("from emoji import EMOJI_UNICODE", "import emoji")
    if not re.search(r"^import emoji\s*$", text, re.MULTILINE):
        raise ValueError("Unsupported Pilmoji helpers: emoji import missing")
    text, count = re.subn(
        r"^_UNICODE_EMOJI_REGEX = .*?$",
        "_UNICODE_EMOJI_REGEX = '|'.join(map(re.escape, sorted(emoji.EMOJI_DATA, key=len, reverse=True)))",
        text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ValueError("Unsupported Pilmoji helpers: expected one emoji regex")
    compile(text, "pilmoji/helpers.py", "exec")
    return text


def main():
    for site_dir in site.getsitepackages():
        path = Path(site_dir) / "pilmoji" / "helpers.py"
        if path.exists():
            original = path.read_text(encoding="utf-8")
            patched = patch_helpers(original)
            if patched != original:
                path.write_text(patched, encoding="utf-8")
            print(f"Pilmoji Unicode emoji compatibility ready: {path}")
            return
    raise SystemExit("pilmoji helpers.py not found; use the bot's Python interpreter")


if __name__ == "__main__":
    main()
