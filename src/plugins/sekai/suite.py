"""Normalize Suite music-result formats without importing the bot runtime."""

DIFFICULTIES = ('easy', 'normal', 'hard', 'expert', 'master', 'append')
PLAY_RESULTS = ('full_perfect', 'full_combo', 'clear', 'not_clear')


def normalize_difficulty(value):
    if isinstance(value, str):
        value = value.strip().lower()
        if value in DIFFICULTIES:
            return value
        if value.isdigit():
            value = int(value)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(DIFFICULTIES):
        return DIFFICULTIES[value]
    return None


def _flag(value):
    return value is True or value == 1 or (isinstance(value, str) and value.lower() in ('true', '1'))


def expand_compact_results(compact):
    if not isinstance(compact, dict):
        return []
    columns = {key: value for key, value in compact.items() if key != '__ENUM__' and isinstance(value, list)}
    if not columns:
        return []
    enums = compact.get('__ENUM__', {})
    enums = enums if isinstance(enums, dict) else {}
    rows = []
    for index in range(max(map(len, columns.values()))):
        row = {}
        for key, column in columns.items():
            if index >= len(column):
                continue
            value = column[index]
            mapping = enums.get(key)
            if isinstance(mapping, list) and type(value) is int and 0 <= value < len(mapping):
                value = mapping[value]
            row[key] = value
        rows.append(row)
    return rows


def normalize_music_results(profile):
    """Canonicalize rows from direct, compact, or nested userMusics captures.

    Missing data stays distinguishable from a present but empty result list.
    Duplicate solo/multi records remain available; B30 takes each chart's best.
    """
    raw = []
    present = isinstance(profile.get('userMusicResults'), list)
    if present:
        raw.extend(profile['userMusicResults'])
    if isinstance(profile.get('compactUserMusicResults'), dict):
        raw.extend(expand_compact_results(profile['compactUserMusicResults']))
        present = True
    for music in profile.get('userMusics') or []:
        if not isinstance(music, dict):
            continue
        for status in music.get('userMusicDifficultyStatuses') or []:
            if not isinstance(status, dict) or not isinstance(status.get('userMusicResults'), list):
                continue
            present = True
            for result in status['userMusicResults']:
                if isinstance(result, dict):
                    raw.append(dict(result, musicId=result.get('musicId', music.get('musicId')),
                                    musicDifficultyType=result.get('musicDifficultyType',
                                        result.get('musicDifficulty', status.get('musicDifficultyType', status.get('musicDifficulty'))))))
    normalized = []
    seen = set()
    invalid = 0
    for item in raw:
        if not isinstance(item, dict):
            invalid += 1
            continue
        try:
            mid = int(item['musicId'])
        except (KeyError, TypeError, ValueError):
            invalid += 1
            continue
        diff = normalize_difficulty(item.get('musicDifficultyType'))
        if diff is None:
            diff = normalize_difficulty(item.get('musicDifficulty'))
        if mid <= 0 or diff is None:
            invalid += 1
            continue
        play = item.get('playResult')
        if type(play) is int and 0 <= play < len(PLAY_RESULTS):
            play = PLAY_RESULTS[play]
        if isinstance(play, str):
            play = play.lower()
        ap = _flag(item.get('fullPerfectFlg')) or play in ('full_perfect', 'all_perfect', 'ap')
        fc = ap or _flag(item.get('fullComboFlg')) or play in ('full_combo', 'fc')
        play = 'full_perfect' if ap else 'full_combo' if fc else 'clear' if play == 'clear' else 'not_clear'
        row = dict(item, musicId=mid, musicDifficultyType=diff, musicDifficulty=diff,
                   playResult=play, fullComboFlg=fc, fullPerfectFlg=ap)
        key = (mid, diff, str(row.get('playType')), play, str(row.get('highScore')))
        if key not in seen:
            normalized.append(row)
            seen.add(key)
    result = dict(profile)
    if present:
        result['userMusicResults'] = normalized
    return result, {'present': present, 'input_rows': len(raw), 'valid_rows': len(normalized), 'invalid_rows': invalid}


def best_chart_results(profile):
    normalized, diagnostics = normalize_music_results(profile)
    ranks = {'not_clear': 0, 'clear': 1, 'full_combo': 2, 'full_perfect': 3}
    best = {}
    for row in normalized.get('userMusicResults', []):
        key = (row['musicId'], row['musicDifficultyType'])
        old = best.get(key)
        if old is None or ranks[row['playResult']] > ranks[old['playResult']]:
            best[key] = row
    return best, profile.get('_music_results_diagnostics', diagnostics)
