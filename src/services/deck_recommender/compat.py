"""Shared wire/data contract for the Haruki engine adapter (no bot imports)."""
import math

ENGINE_PACKAGE = "haruki-sekai-deck-recommend-cpp"
ENGINE_VERSION = "0.4.2"
DATA_SCHEMA_VERSION = 2
OPTIONAL_MASTERDATA = (
    "eventCardBonusLimits", "eventHonorBonuses",
    "eventMysekaiFixtureGameCharacterPerformanceBonusLimits",
    "eventSkillScoreUpLimits", "ingameCombos", "ingameNotes",
)
OMAKASE_MUSIC_ID = 10000
SCALAR_FIELDS = (
    "music_time", "event_rate", "base_score", "base_score_auto",
    "fever_score", "fever_end_time", "tap_count",
)
SKILL_FIELDS = ("skill_score_solo", "skill_score_auto", "skill_score_multi")
DIFFICULTIES = ("easy", "normal", "hard", "expert", "master", "append")


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_complete_musicmeta(row):
    return (
        isinstance(row.get("music_id"), int)
        and row.get("difficulty") in DIFFICULTIES
        and all(finite_number(row.get(k)) for k in SCALAR_FIELDS)
        and row["music_time"] > 0
        and all(isinstance(row.get(k), list) and len(row[k]) == 6
                and all(finite_number(v) for v in row[k]) for k in SKILL_FIELDS)
    )


def prepare_musicmetas(rows):
    """Exclude incomplete scoring rows instead of fabricating zero values.

    Rebuild the synthetic random song from complete hard/expert/master rows.
    Returns (valid rows including synthetic songs, skipped (music ID, diff)).
    The caller logs skipped rows once per source revision.
    """
    valid, skipped = [], []
    for row in rows:
        if row.get("music_id") == OMAKASE_MUSIC_ID:
            continue
        if not is_complete_musicmeta(row):
            skipped.append((row.get("music_id"), row.get("difficulty")))
        else:
            valid.append(row)
    averaged = [row for row in valid if row["difficulty"] in ("hard", "expert", "master")]
    if not averaged:
        raise ValueError("没有完整的歌曲计分数据，无法更新组卡服务")
    count = len(averaged)
    synthetic = {k: sum(row[k] for row in averaged) / count for k in SCALAR_FIELDS}
    for k in ("event_rate", "tap_count"):
        synthetic[k] = int(synthetic[k])  # Preserve LunaBot's existing averaging.
    for k in SKILL_FIELDS:
        synthetic[k] = [sum(row[k][i] for row in averaged) / count for i in range(6)]
    for diff in DIFFICULTIES:
        valid.append(dict(synthetic, music_id=OMAKASE_MUSIC_ID, difficulty=diff))
    return valid, skipped


class InsufficientCards(ValueError):
    pass


def validate_candidate_pool(options, userdata, master_cards):
    """Guard native searches against empty/undersized candidate pools.

    Some native search paths crash rather than raising for empty challenge
    pools. Do not silently change deck member count or allow disabled cards.
    """
    member = options.get("member") or 5
    if not isinstance(member, int) or not 2 <= member <= 5:
        raise ValueError("组卡人数必须在 2 到 5 之间")
    challenge = options.get("live_type") in ("challenge", "challenge_auto")
    character = options.get("challenge_live_character_id")
    if challenge and not character:
        raise ValueError("挑战组卡需要指定角色")
    singles = {c["card_id"]: c for c in options.get("single_card_configs", [])}
    candidates = {}
    for uc in userdata.get("userCards", []):
        card = master_cards.get(uc.get("cardId"))
        if not card:
            continue
        rarity = card.get("cardRarityType", "")
        rarity_key = "rarity_birthday_config" if rarity == "rarity_birthday" else rarity + "_config"
        disabled = (options.get(rarity_key) or {}).get("disable", False)
        override = singles.get(card["id"], {}).get("disable")
        if override is not None:
            disabled = override
        if disabled or (challenge and card["characterId"] != character):
            continue
        candidates[card["id"]] = card["characterId"]
    # Explicit fixed cards may be virtual cards synthesized by the native engine.
    for cid in options.get("fixed_cards") or []:
        card = master_cards.get(cid)
        if card and (not challenge or card["characterId"] == character):
            candidates[cid] = card["characterId"]
    available = len(candidates) if challenge else len(set(candidates.values()))
    if available < member:
        label = "该角色可用卡牌" if challenge else "可用角色"
        raise InsufficientCards(f"{label}不足：需要 {member}，当前 {available}；请检查抓包和禁用设置")
