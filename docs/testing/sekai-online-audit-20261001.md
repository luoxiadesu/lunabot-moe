# Sekai 命令在线排查记录（2026-10-01）

测试服务器：47.91.23.232；测试群：149473950；测试账号：27198599。

## 测试方法与覆盖范围

共覆盖 107 个命令处理入口，同义指令不重复计数。前 67 项以现有代码、真实资源和在线接口执行，查询回复通过 NapCat 实际发送到指定群，每 5 项合并一次。另 40 项在写时复制的隔离目录中验证，未向群发送绑定/订阅等状态变更提示。额外进行了跨区查询、故障回测和详细统计测试。

测试直接调用真实命令处理函数与区服参数解析，不伪造 QQ 用户发言；没有逐项经过正式 NoneBot 的入站匹配、冷却和权限包装。因此本报告验证功能处理/取数/绘图/发送链路，不等同于所有别名、权限分支和五区参数组合的穷举。

测试进程不运行 bot 定时任务，JSON 状态仅在内存修改，文件写入由 OverlayFS 隔离；真实账号绑定和订阅保持不变。绘图使用测试进程内线程并限额一个 CPU 核心，耗时不能直接当作正式多进程性能。

## 已修复并部署

- 后续 B30/Suite 修复：合并 pjskb30 两张定数表，兼容数字难度，国服实测 Rating 36.03；活动记录和打歌进度再次出图。upload 大整数精度已修复并自动部署，Webhook 配置改为持久保存。详见 [部署记录](../operations/b30-suite-20261001.md)。

- 活动记录中 `rank=null`/`eventPoint=null` 导致排序异常；现在未知排名排在后面，没有排名时按 PT 排序，并显示缺失值。国服实测重新出图。
- 韩服计分记录 `event_rate=null` 使任何查曲的排行榜阶段报错；跳过不完整计分记录，Meta 查询清楚提示数据缺失。正常歌曲 74 实测出图。
- 详细用户统计将普通 JSON 错当 zstd 文件；现在按文件头兼容普通 JSON 与旧压缩格式。群内详细统计回测通过。
- MySekai 照片缺少列表、负数索引过界的处理；上游错误转为简明业务提示。
- 歌曲别名接口已改为 `data.aliases`，旧代码仍要求顶层 `music_id`，导致逐条失败；现在兼容新旧协议，校验错误响应不覆盖本地别名，失败返回 False，并设置单次请求超时。用歌曲 1、74、707 的在线响应验证通过。
- 胜率上游 403 不再把 HTML 直接作为指令错误；自定义控分缺数据提示不再误称只影响 100 以下 PT。

## 仍需处理 / 验证边界

- MySekai 照片：game-api 内网也返回 502；Haruki 上游报 missing thumbnail in response，另一上游报 Server not initialized。照片获取本身尚未恢复。
- 5v5 胜率：3-3.dev 返回 Cloudflare 403，不能通过修改计算代码恢复数据源。
- 自定义房间控分：服务器缺少 `data/sekai/custom_room_pt.csv`。
- 表情底图：测试的 1 号底图不存在，制作/刷新需要资源或模型服务。
- 歌曲别名同步：725 首歌全量同步超出 70 秒测试窗口；新协议及失败汇总路径已修复并抽样验证，未在正式数据上强制完成全量同步。
- 剧情总结/批量抠图在调用模型边界停止，未产生模型费用；注册账号的外部写入被阻止；当前无 5v5 活动，送火未实际执行。
- 上传背景/卡牌提取没有图片输入，只覆盖参数检查；账号验证已有验证状态；MSR 换绑仅到确认提示。
- 猜图/猜歌执行真实素材准备与结束路径，但隔离队列等待被缩短，不代表群内互动流程完整验证。

## 验证和清理

新增 10 项排序、计分数据、别名协议/失败、照片边界、统计格式、上游提示的回归测试通过；MySekai 推送 19 项测试通过。正式 bot 重启后五区组卡数据同步正常、4 个组卡进程健康，Webhook 队列无失败任务。

本轮先清理本地 135.7 MiB、服务器 165.6 MiB 的旧临时产物（合计约 301.3 MiB），保留旧引擎、原配置和部署回退备份。测试结束又移除 90.8 MiB 的隔离写入和缓存，OverlayFS 已卸载；仅保留测试代码、脱敏清单、修改前代码备份及 12.5 MiB 的私有压缩证据。

服务器证据目录：`/bot/lunabot-command-audit-20261001`。原始回复包含账号查询数据，限制本机访问，不提交 Git；测试图像中暴露的 ID 精度问题按上传服务问题记录。修改前备份位于 `backup-before-fixes/`。

## 107 项主清单

| 模块 | 入口 | 测试指令 | 结果/限制 |
|---|---|---|---|
| misc | ngword | `/jppjsk ng 测试文字` | 查询/绘图及群内合并发送正常 |
| misc | upload_help | `/抓包帮助` | 查询/绘图及群内合并发送正常 |
| profile | pjsk_reg_time | `/cn注册时间` | 查询/绘图及群内合并发送正常 |
| profile | pjsk_check_service | `/cnpcs` | 查询/绘图及群内合并发送正常 |
| music | pjsk_alias | `/cn歌曲别名 74` | 查询/绘图及群内合并发送正常 |
| card | pjsk_chara_alias | `/jp角色别名 miku` | 查询/绘图及群内合并发送正常 |
| music | pjsk_song | `/cn查曲 74` | 查询/绘图及群内合并发送正常 |
| card | pjsk_card | `/cn查卡 1` | 查询/绘图及群内合并发送正常 |
| event | pjsk_event | `/cn活动 200` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_check_mysekai_data | `/cnmsd` | 查询/绘图及群内合并发送正常 |
| profile | pjsk_info | `/cn个人信息` | 查询/绘图及群内合并发送正常 |
| profile | pjsk_check_data | `/cn抓包状态` | 查询/绘图及群内合并发送正常 |
| profile | pjsk_data_mode | `/cn抓包模式` | 正常业务提示 |
| profile | get_verified_uids | `/cnpjsk验证列表` | 查询/绘图及群内合并发送正常 |
| education | pjsk_challenge_info | `/cn挑战信息` | 查询/绘图及群内合并发送正常 |
| education | pjsk_power_bonus_info | `/cn加成信息` | 查询/绘图及群内合并发送正常 |
| education | pjsk_area_item | `/cn区域道具 miku` | 查询/绘图及群内合并发送正常 |
| education | pjsk_bonds | `/cn羁绊 miku` | 查询/绘图及群内合并发送正常 |
| education | pjsk_leader_count | `/cn队长次数` | 查询/绘图及群内合并发送正常 |
| education | pjsk_material_info | `/cn材料信息` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_res | `/cnmsr` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_blueprint | `/cnmsb` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_furniture | `/cnmsf 1` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_photo | `/cnmsp 1` | 上游502未恢复；越界及错误提示已修复 |
| mysekai | pjsk_mysekai_gate | `/cnmsg` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_musicrecord | `/cnmsm` | 查询/绘图及群内合并发送正常 |
| mysekai | pjsk_mysekai_material_info | `/cn烤森材料` | 查询/绘图及群内合并发送正常 |
| deck | pjsk_event_deck | `/cn组卡` | 查询/绘图及群内合并发送正常 |
| deck | pjsk_challenge_deck | `/cn挑战组卡 miku` | 查询/绘图及群内合并发送正常 |
| deck | pjsk_no_event_deck | `/cn长草组卡` | 查询/绘图及群内合并发送正常 |
| deck | pjsk_bonus_deck | `/cn加成组卡 150` | 查询/绘图及群内合并发送正常 |
| deck | mysekai_deck | `/cn烤森组卡` | 查询/绘图及群内合并发送正常 |
| deck | pjsk_score_up | `/实效 100 100 100 100 100` | 查询/绘图及群内合并发送正常 |
| gacha | pjsk_gacha_record | `/cn抽卡记录` | 查询/绘图及群内合并发送正常 |
| event | pjsk_event_record | `/cn活动记录` | 空值排序已修复并线上出图 |
| music | pjsk_note_num | `/cn物量 1000` | 查询/绘图及群内合并发送正常 |
| music | pjsk_music_list | `/cn歌曲列表 ma 32` | 查询/绘图及群内合并发送正常 |
| music | pjsk_play_progress | `/cn打歌进度` | 查询/绘图及群内合并发送正常 |
| music | pjsk_music_rewards | `/cn歌曲奖励` | 查询/绘图及群内合并发送正常 |
| music | pjsk_bpm | `/cn查bpm 74` | 查询/绘图及群内合并发送正常 |
| music | pjsk_music_cover | `/cn查曲绘 74` | 查询/绘图及群内合并发送正常 |
| music | pjsk_best30 | `/cnb30` | 初次虽出图但为0.00；后续修复定数源及数字难度，重测36.03 |
| card | pjsk_card_img | `/cn卡面 1` | 查询/绘图及群内合并发送正常 |
| card | pjsk_box | `/cn卡牌一览 miku` | 查询/绘图及群内合并发送正常 |
| chart | pjsk_chart | `/cn谱面 74 ex` | 查询/绘图及群内合并发送正常 |
| gacha | pjsk_gacha | `/cn卡池 -1` | 查询/绘图及群内合并发送正常 |
| misc | chara_bd | `/cn生日 miku` | 查询/绘图及群内合并发送正常 |
| misc | pjsk_update | `/cnpjsk更新` | 查询/绘图及群内合并发送正常 |
| vlive | pjsk_live | `/cnvlive` | 查询/绘图及群内合并发送正常 |
| score | pjsk_music_meta | `/cn歌曲meta 74` | 查询/绘图及群内合并发送正常 |
| score | pjsk_score_control | `/jp控分 1000 74` | 查询/绘图及群内合并发送正常 |
| score | pjsk_custom_room_score_control | `/jp自定义控分 1000` | 缺少custom_room_pt.csv |
| score | pjsk_music_board | `/jp歌曲排行` | 查询/绘图及群内合并发送正常 |
| stamp | pjsk_stamp | `/jppjsk表情 1 png` | 查询/绘图及群内合并发送正常 |
| stamp | pjsk_rand_stamp | `/jp随机表情 miku png` | 查询/绘图及群内合并发送正常 |
| stamp | pjsk_stamp_base | `/jppjsk表情底图 1 png` | 测试表情底图不存在 |
| entertainment | pjsk_entertainment_limit_check | `/jppec` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_skp | `/cnskp` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_skl | `/cnskl` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_sks | `/cnsks` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_skds | `/cnskds` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_sk | `/cnsk 100` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_cf | `/cncf 100` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_csb | `/cncsb 100` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_ptr | `/cnptr 100` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_rtr | `/cnrtr 100` | 查询/绘图及群内合并发送正常 |
| sk | pjsk_winrate | `/jp胜率` | 上游403未恢复；错误提示已改善 |
| music | pjsk_alias_set | `/cn添加歌曲别名 74 audit_20261001` | 隔离状态测试；未向群发送修改提示 |
| music | pjsk_alias_del | `/cn删除歌曲别名 audit_20261001` | 隔离状态测试；未向群发送修改提示 |
| music | pjsk_sync_music_alias | `/同步歌曲别名` | 新旧接口协议已兼容、在线抽样通过；全量任务未跑完 |
| card | pjsk_card_story | `/jp卡牌剧情 1` | 未执行外部写入/模型调用 |
| event | pjsk_event_story | `/jp活动剧情 1` | 未执行外部写入/模型调用 |
| profile | pjsk_bind | `/cn绑定` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_unbind | `/jp解绑 3` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_set_main | `/jp主账号 1` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_swap_bind | `/jp交换绑定 1 2` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_hide_suite | `/cn隐藏抓包` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_show_suite | `/cn展示抓包` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_hide_id | `/cn隐藏id` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_show_id | `/cn展示id` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_blacklist | `/pjsk黑名单添加 audit_invalid_uid` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_blacklist_remove | `/pjsk黑名单移除 audit_invalid_uid` | 隔离状态测试；未向群发送修改提示 |
| profile | verify_game_account | `/cnpjsk验证` | 账号已验证，未测试重新验证流程 |
| profile | upload_profile_bg | `/cn上传个人信息背景` | 无输入图片，仅验证参数检查 |
| profile | clear_profile_bg | `/cn清空个人信息背景` | 隔离状态测试；未向群发送修改提示 |
| profile | adjust_profile_bg | `/cn调整个人信息` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_user_sta | `/用户统计 group` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_bind_history | `/绑定历史 27198599` | 隔离状态测试；未向群发送修改提示 |
| profile | pjsk_create_guest_account | `/jppjsk注册` | 未执行外部写入/模型调用 |
| event | pjsk_send_boost | `/jp送火` | 当前无5v5活动，未实际送火 |
| entertainment | pjsk_entertainment_limit | `/jppel 200` | 隔离状态测试；未向群发送修改提示 |
| entertainment | pjsk_guess_cover | `/jp猜曲绘 easy` | 隔离状态测试；未向群发送修改提示 |
| entertainment | pjsk_guess_chart | `/jp猜谱面 easy` | 隔离状态测试；未向群发送修改提示 |
| entertainment | pjsk_guess_card | `/jp猜卡面 easy` | 隔离状态测试；未向群发送修改提示 |
| entertainment | pjsk_guess_music | `/jp猜歌 easy` | 隔离状态测试；未向群发送修改提示 |
| entertainment | pjsk_spin_gacha | `/cn单抽 -1` | 隔离状态测试；未向群发送修改提示 |
| misc | extract_card | `/jp提取卡牌` | 无输入图片，仅验证参数检查 |
| misc | heyiwei | `/cnpjsk detail` | 隔离状态测试；未向群发送修改提示 |
| mysekai | msr_change_bind | `/cnmsr换绑` | 确认提示正常，未确认换绑 |
| stamp | pjsk_stamp_refresh | `/jppjsk表情刷新` | 无参数，仅验证用法提示 |
| stamp | pjsk_stamp_refresh_batch | `/jppjsk表情刷新批量` | 未执行外部写入/模型调用 |
| stamp | pjsk_stamp_base_delete | `/jppjsk删除表情底图 1` | 不存在的底图删除失败提示正常 |
| sub | sekai_group_sub | `/cnpjsk开启 msr` | 隔离状态测试；未向群发送修改提示 |
| sub | sekai_group_unsub | `/cnpjsk关闭 msr` | 隔离状态测试；未向群发送修改提示 |
| sub | sekai_user_sub | `/cnpjsk订阅 msr` | 隔离状态测试；未向群发送修改提示 |
| sub | sekai_user_unsub | `/cnpjsk取消订阅 msr` | 隔离状态测试；未向群发送修改提示 |
| handler | default_region | `/pjsk默认区服 cn` | 隔离状态测试；未向群发送修改提示 |
