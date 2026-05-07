from ..utils import *
from .api import SklandAPI, SignInResult
import asyncio


config = Config('skland')
logger = get_logger("Skland")
file_db = get_file_db("data/skland/db.json", logger)
gbl = get_group_black_list(file_db, logger, 'skland')

AUTO_SIGN_TIME = config.get('auto_sign_time', [1, 0, 0], raise_exc=False)
MAX_RETRIES = config.get('max_retries', 3, raise_exc=False)
BIND_CD_SECONDS = config.get('bind_cd_seconds', 30, raise_exc=False)
SIGN_CD_SECONDS = config.get('sign_cd_seconds', 10, raise_exc=False)

bind_cd = ColdDown(file_db, logger, default_interval=BIND_CD_SECONDS, cold_down_name='skland_bind')
sign_cd = ColdDown(file_db, logger, default_interval=SIGN_CD_SECONDS, cold_down_name='skland_sign')
action_cd = ColdDown(file_db, logger, cold_down_name='skland_action')

_user_locks: dict[str, asyncio.Lock] = {}

TOKEN_TUTORIAL = (
    "如何获取 Token：\n"
    "1. 登录森空岛官网。\n"
    "2. 登录成功后，访问此链接：https://web-api.skland.com/account/info/hg\n"
    "3. 页面将返回一段 JSON 数据，请复制 content 字段中的长字符串。\n"
    "数据示例：{\"code\":0,\"data\":{\"content\":\"请复制这一长串字符\"}}"
)

GROUP_BIND_WARNING = "⚠️ 群聊绑定不会自动撤回消息，请自行注意 Token 安全；如需更稳妥请私聊机器人绑定。"


def _user_key(qid: int | str, suffix: str | None = None) -> str:
    base = f"users.{qid}"
    return base if suffix is None else f"{base}.{suffix}"


def _get_user_data(qid: int | str) -> dict:
    return file_db.get(_user_key(qid), {}) or {}


def _has_bound_token(qid: int | str) -> bool:
    return bool(file_db.get(_user_key(qid, 'token')))


def _today_str() -> str:
    return datetime.now().strftime('%Y-%m-%d')


def _get_user_lock(qid: int | str) -> asyncio.Lock:
    key = str(qid)
    if key not in _user_locks:
        _user_locks[key] = asyncio.Lock()
    return _user_locks[key]


def _is_signed_result(result: SignInResult) -> bool:
    return SklandAPI.is_signed_today(result)


def _all_results_signed(results: list[SignInResult]) -> bool:
    return bool(results) and all(_is_signed_result(result) for result in results)


def _serialize_results(results: list[SignInResult]) -> list[str]:
    lines = []
    for result in results:
        if result.success:
            status_text = "成功"
            icon = "✅"
            detail = f" ({', '.join(result.awards)})" if result.awards else ""
        elif _is_signed_result(result):
            status_text = "已签"
            icon = "✅"
            detail = ""
        else:
            status_text = "失败"
            icon = "❌"
            detail = f" ({result.error})" if result.error else ""
        role_name = f"({result.nickname})" if result.nickname else ""
        lines.append(f"{icon} {result.game}{role_name}: {status_text}{detail}")
    return lines


def _build_sign_message(qid: int | str, result_lines: list[str]) -> str:
    lines = ["📅 森空岛终末地签到", "", f"🌈 QQ({qid})"]
    lines.extend(result_lines or ["❌ 未找到终末地绑定角色"])
    return "\n".join(lines)


def _save_profile(qid: int | str, nickname: str, roles: list[dict]):
    file_db.set(_user_key(qid, 'skland_nickname'), nickname)
    file_db.set(_user_key(qid, 'roles'), roles)


def _save_last_result(qid: int | str, result_lines: list[str]):
    file_db.set(_user_key(qid, 'last_result'), result_lines)


async def _format_push_group(group_id: int | None) -> str:
    if not group_id:
        return "未订阅"
    try:
        bot = await aget_group_bot(group_id)
        if bot is None:
            return str(group_id)
        return f"{await get_group_name(bot, group_id)}({group_id})"
    except Exception:
        return str(group_id)


async def _with_api(func):
    api = SklandAPI(max_retries=MAX_RETRIES)
    try:
        return await func(api)
    finally:
        await api.close()


async def _validate_token(token: str) -> tuple[str, list[dict]]:
    async def runner(api: SklandAPI):
        return await api.get_endfield_profile(token)

    nickname, roles = await _with_api(runner)
    if not roles:
        raise ReplyException("该 Token 未绑定终末地角色")
    return nickname, roles


async def _run_sign(qid: int | str) -> tuple[list[SignInResult], str, list[str]]:
    token = file_db.get(_user_key(qid, 'token'))
    if not token:
        raise ReplyException("你还没有绑定森空岛 Token")

    async with _get_user_lock(qid):
        async def runner(api: SklandAPI):
            return await api.do_full_sign_in(token)

        results, nickname, roles = await _with_api(runner)
        if nickname:
            _save_profile(qid, nickname, roles)
        result_lines = _serialize_results(results)
        _save_last_result(qid, result_lines or ["❌ 未找到终末地绑定角色"])
        if _all_results_signed(results):
            file_db.set(_user_key(qid, 'last_sign_date'), _today_str())
        return results, nickname, result_lines


async def _build_status_text(qid: int | str) -> str:
    user_data = _get_user_data(qid)
    if not user_data or not user_data.get('token'):
        return "森空岛状态\n---\n未绑定 Token"

    roles = user_data.get('roles', [])
    last_result = user_data.get('last_result', []) or ["暂无"]
    push_group_desc = await _format_push_group(user_data.get('push_group_id'))

    lines = [
        "森空岛状态",
        "---",
        "绑定状态: 已绑定",
        f"森空岛昵称: {user_data.get('skland_nickname', '未知')}",
        f"推送群: {push_group_desc}",
        f"最近成功签到日期: {user_data.get('last_sign_date', '暂无')}",
        "终末地角色:",
    ]
    if roles:
        for role in roles:
            lines.append(f"- {role.get('nickname', '未知角色')} ({role.get('server_id', '-')})")
    else:
        lines.append("- 暂无缓存")
    lines.append("最近一次签到结果:")
    for item in last_result:
        lines.append(f"- {item}")
    return "\n".join(lines)


skland_bind = CmdHandler(['/森空岛绑定'], logger)
skland_bind.check_cdrate(bind_cd).check_wblist(gbl)
@skland_bind.handle()
async def _(ctx: HandlerContext):
    token = ctx.get_args().strip()
    is_group = is_group_msg(ctx.event)
    if not token:
        usage_lines = ["用法：/森空岛绑定 <token>", "", TOKEN_TUTORIAL]
        if is_group:
            usage_lines.insert(0, GROUP_BIND_WARNING)
            return await ctx.asend_at_msg("\n".join(usage_lines))
        return await ctx.asend_reply_msg("\n".join(usage_lines))

    try:
        nickname, roles = await _validate_token(token)
        file_db.set(_user_key(ctx.user_id, 'token'), token)
        _save_profile(ctx.user_id, nickname, roles)
        file_db.set(_user_key(ctx.user_id, 'last_result'), ["暂无"])

        msg = f"绑定成功，已校验到 {len(roles)} 个终末地角色"
        if is_group:
            return await ctx.asend_at_msg(f"{msg}\n{GROUP_BIND_WARNING}")
        return await ctx.asend_reply_msg(msg)
    except Exception as exc:
        error_msg = get_exc_desc(exc)
        if is_group:
            return await ctx.asend_at_msg(f"绑定失败: {error_msg}\n{GROUP_BIND_WARNING}")
        return await ctx.asend_reply_msg(f"绑定失败: {error_msg}")


skland_unbind = CmdHandler(['/森空岛解绑'], logger)
skland_unbind.check_cdrate(bind_cd).check_wblist(gbl)
@skland_unbind.handle()
async def _(ctx: HandlerContext):
    if not _has_bound_token(ctx.user_id):
        return await ctx.asend_reply_msg('你还没有绑定森空岛 Token')
    file_db.delete(_user_key(ctx.user_id))
    return await ctx.asend_reply_msg('解绑成功')


skland_status = CmdHandler(['/森空岛状态'], logger)
skland_status.check_cdrate(action_cd).check_wblist(gbl)
@skland_status.handle()
async def _(ctx: HandlerContext):
    return await ctx.asend_fold_msg_adaptive(await _build_status_text(ctx.user_id))


skland_sub = CmdHandler(['/森空岛订阅'], logger)
skland_sub.check_cdrate(action_cd).check_wblist(gbl).check_group()
@skland_sub.handle()
async def _(ctx: HandlerContext):
    if not _has_bound_token(ctx.user_id):
        return await ctx.asend_reply_msg('请先绑定森空岛 Token')
    old_group_id = file_db.get(_user_key(ctx.user_id, 'push_group_id'))
    file_db.set(_user_key(ctx.user_id, 'push_group_id'), ctx.group_id)
    if old_group_id and int(old_group_id) != int(ctx.group_id):
        return await ctx.asend_reply_msg(f'订阅成功，已将自动推送群从 {old_group_id} 切换到当前群')
    if old_group_id and int(old_group_id) == int(ctx.group_id):
        return await ctx.asend_reply_msg('当前群已经是你的自动推送群')
    return await ctx.asend_reply_msg('订阅成功，当前群已设为自动推送群')


skland_unsub = CmdHandler(['/森空岛取消订阅'], logger)
skland_unsub.check_cdrate(action_cd).check_wblist(gbl).check_group()
@skland_unsub.handle()
async def _(ctx: HandlerContext):
    push_group_id = file_db.get(_user_key(ctx.user_id, 'push_group_id'))
    if not push_group_id:
        return await ctx.asend_reply_msg('你当前没有订阅任何自动推送群')
    if int(push_group_id) != int(ctx.group_id):
        return await ctx.asend_reply_msg(f'当前群不是你的自动推送群，你的自动推送群是 {push_group_id}')
    file_db.delete(_user_key(ctx.user_id, 'push_group_id'))
    return await ctx.asend_reply_msg('已取消当前群的自动推送订阅')


skland_sign = CmdHandler(['/森空岛签到'], logger)
skland_sign.check_cdrate(sign_cd).check_wblist(gbl)
@skland_sign.handle()
async def _(ctx: HandlerContext):
    try:
        results, _, result_lines = await _run_sign(ctx.user_id)
        if not results:
            result_lines = ["❌ 未找到终末地绑定角色"]
            _save_last_result(ctx.user_id, result_lines)
        return await ctx.asend_fold_msg_adaptive(_build_sign_message(ctx.user_id, result_lines), need_reply=True)
    except Exception as exc:
        error_line = f"❌ 系统错误: {get_exc_desc(exc)}"
        _save_last_result(ctx.user_id, [error_line])
        return await ctx.asend_reply_msg(error_line)


@scheduler.scheduled_job("cron", hour=AUTO_SIGN_TIME[0], minute=AUTO_SIGN_TIME[1], second=AUTO_SIGN_TIME[2])
async def _skland_auto_sign():
    users = file_db.get('users', {}) or {}
    today = _today_str()

    for qid, user_data in users.items():
        try:
            group_id = user_data.get('push_group_id')
            if not user_data.get('token') or not group_id:
                continue
            if not gbl.check_id(int(group_id)):
                continue
            if user_data.get('last_sign_date') == today:
                continue

            results, _, result_lines = await _run_sign(qid)
            if not results:
                result_lines = ["❌ 未找到终末地绑定角色"]
                _save_last_result(qid, result_lines)

            message = f"[CQ:at,qq={qid}]\n{_build_sign_message(qid, result_lines)}"
            try:
                await send_group_msg_by_bot(int(group_id), message)
            except Exception as exc:
                logger.print_exc(f"自动推送用户 {qid} 的签到结果失败: {get_exc_desc(exc)}")
        except Exception as exc:
            logger.print_exc(f"自动签到用户 {qid} 失败: {get_exc_desc(exc)}")
            _save_last_result(qid, [f"❌ 系统错误: {get_exc_desc(exc)}"])
