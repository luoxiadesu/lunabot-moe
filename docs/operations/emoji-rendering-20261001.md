# Emoji 方框修复（2026-10-01）

服务器环境：Pilmoji 2.0.0、emoji 2.15.0、Pillow 9.5.0。
根因是 `patch_pilmoji.py` 将 `EMOJI_DATA.values()[en]` 的英文名称拼进 Unicode
正则。真实 `😀`、`❤️`、`🇨🇳`、肤色和 ZWJ 序列全部被当成普通文字，
随后由没有对应字形的中文字体显示为方框。服务器已安装依赖，图片源也能返回 PNG；
不是 pip 安装时漏掉 emoji 图片。另有逐字符检测无法识别纯国旗的问题。

修复内容：

- 补丁使用 `EMOJI_DATA` 的 Unicode 键，按长度倒序匹配完整序列；既支持原版
  Pilmoji，也能修复旧补丁，重复执行不产生变化。保持现有库版本和绘制位置。
- 绘图入口使用 emoji 序列检测，支持纯国旗和键帽。
- 真正启用 emoji 图片后，在线测试遇到原 CDN 超时。新增
  `data/utils/emoji_cache` 持久缓存、每个进程最多 256 项内存缓存、原子落盘、
  图片格式/尺寸检查、3 秒网络超时及 Google Noto Emoji 官方 CDN 备用来源。
  两个来源均失败时仍由 Pilmoji 回退文字，5 分钟内同一进程不反复下载。
  未缓存的新 emoji 仍需要网络，不保证所有最新 emoji 均有图片。
- 绘图缓存增加渲染版本，旧的带方框图片会在下次请求时重新生成。
- README 改为要求依赖安装后运行 `python patch_pilmoji.py`，随后重启 bot；
  重新安装 Pilmoji 会覆盖 site-packages，因此也必须重跑补丁。

验证：6 项回归测试通过，包括原版/旧补丁修复与幂等、完整序列解析、纯国旗识别、
实际 Pilmoji 贴图、备用来源、损坏缓存恢复、断网读缓存及失败退避。
使用服务器真实 Painter、中文字体和在线资源生成前后对比，覆盖普通表情、爱心、
新表情、国旗、肤色、家庭 ZWJ、键帽；修改前为方框，修改后显示彩色图。
部署后另用实际多进程绘图路径验证成功，bot 和其余四项服务健康。
没有通过本轮测试向群发送消息。

备份：`/bot/lunabot-backups/emoji-20261001`，包含旧绘图文件、补丁、
实际环境的 `helpers.py` 及新增文件清单。回退时停止 bot，恢复这些文件后启动，
保留用户数据；缓存为可重新生成的图片。
证据：`/bot/lunabot-emoji-check-20261001/emoji-before-after.png` 和
`emoji-live-worker.png`。本地对比图在 `data/utils/emoji-check/before-after.png`。
