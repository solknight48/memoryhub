# MemoryHub (`mh`)

**简体中文** | [English](README.en.md)

[![CI](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml/badge.svg)](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml)

用 Git 式的检查点管理 AI 会话上下文。

每次 Claude Code 会话都从零开始。MemoryHub 解决这件事：会话结束时 `mh save` 把它
**提纯**（只留 User/Agent 对话，工具调用、思考过程和框架噪音按规则剥除，纯机械处理，
不花 LLM 费用），存进一个**检查点**。检查点之间默认独立；把两个**链接**起来，它们就会
一起加载并按时间合并。新会话运行 `mh load`，记忆就回来了。

```
.memoryhub/                                  ← 中枢：一个普通的 git 仓库
  checkpoints/
    2026-07-14_1650_data-pipeline/           ← 检查点：<创建时间>_<名称>/
      2026-07-10_1432_a1b2c3d4.md            ← 提纯会话：<结束时间>_<会话 id>.md
  links.toml                                 ← 链接的检查点一起加载
  current                                    ← 本地指针，不纳入版本控制
```

## 安装

```sh
uv tool install git+https://github.com/solknight48/memoryhub
mh skill install           # 让 Claude Code 会话学会这套工作流
```

需要 Linux 或 macOS、git ≥ 2.32、Python ≥ 3.12。Windows 未测试。

从克隆仓库安装时注意：`uv tool install` 会**复制**源码，装出来的是快照，之后
`git pull` 不会更新已安装的 `mh`，新命令也不会出现。想让它跟随工作区就用
`uv tool install --force -e .`；想重新生成快照就加 `--force` 再装一次。

## 快速上手

```console
$ cd ~/dev/tickstore
$ mh init                        # 在项目根目录建立中枢
$ mh checkpoint data-pipeline    # 创建检查点，并设为当前

# ……和 Claude 一起工作；会话结束时（agent 通过 skill 自己执行）：
$ mh save
saved 2026-07-18_0941_7aee4e68.md -> data-pipeline (1 sessions)

# 下一次会话，热启动：
$ mh load
<!-- mh | loaded: data-pipeline | 1 of 1 sessions | @ 3f1c2ab -->

# 第二条工作线，链接到第一条，之后一起加载：
$ mh checkpoint backtest
$ mh save
$ mh link data-pipeline backtest
$ mh load                        # 两者的会话，按时间合并
```

## 命令

| 命令 | 作用 |
|---|---|
| `mh init [--global] [--claude] [--template T]` | 创建中枢。 |
| `mh checkpoint [name] [--at STAGE] [--under CKPT]` | 新建检查点，并设为当前。不给名字：模板里的下一个阶段；只给 `--at`：同一阶段再来一个（`design-2`）；`--under`：子检查点（`design.head-page`）。 |
| `mh template [name] [--list [-v]] [--clear]` | 阶段模板——后面各检查点的默认名字。 |
| `mh save [CKPT] [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | 提纯当前会话并存入检查点。 |
| `mh save [CKPT] --compact --file MD` | 存入 agent 撰写的摘要，替代完整对话。 |
| `mh save [CKPT] --compact --with agent [--focus TEXT]` | 让这个会话自己的 CLI（`claude -p` 或 `pi -p`；`--with claude`/`pi` 指定一个）写摘要并存入。 |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | 回填本项目的历史会话（Claude Code、pi、Codex）。 |
| `mh load [CKPT...] [--no-links] [--tree] [--budget N] [--all] [--json]` | 热启动上下文包：所选检查点 + 链接闭包，按时间合并；`--tree` 把所选检查点下的子检查点也带上。 |
| `mh link A B` / `mh unlink A B` | 让两个检查点一起加载 / 取消。 |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | 查看中枢内容。 |
| `mh trace CKPT/SESSION` | 找回某个保存会话所提纯自的原始 transcript。 |
| `mh rm CKPT[/SESSION] [-x N] [--force]` | 删除检查点、会话，或单独一轮对话。 |
| `mh mv CKPT/SESSION CKPT` / `mh rename CKPT NAME` | 移动会话 / 重命名检查点。 |
| `mh edit CKPT/SESSION -x N [--user T] [--agent T]` | 改写一轮对话的某一侧。 |
| `mh skip CKPT/SESSION` / `mh unskip CKPT/SESSION` | 让某个会话不进 `mh load`（仍留在检查点里）/ 恢复加载。 |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | 移动当前指针。 |
| `mh status` / `mh log` | 位置与统计 / 中枢的 git 日志。 |
| `mh sync` | 对 `origin` 执行 `pull --rebase` + `push`，冲突自动中止。 |
| `mh hubs [--prune]` | 列出所有已注册的中枢。 |
| `mh ui [--port N] [--budget N\|none] [--read-only] [--detach] [--stop] [--session ID]` | 在浏览器里打开检查点地图并整理中枢。 |
| `mh hook install [--user] [--remove] [--budget N] [--tree]` | 通过 Claude Code hooks 自动 load/save。 |
| `mh skill install` | 安装 Claude Code skill。 |

## 保存：提纯，或压缩

`mh save` 是一趟确定性处理，不调用 LLM、不联网：找到本次会话的 transcript，
按顺序把每个用户轮次与其后的助手文本配对，剥掉一切不是对话的内容（思考块、工具调用与
结果、子 agent 往来、`<system-reminder>`、框架包装消息、被打断的轮次），丢弃触发这次
保存的末尾问句，然后写入 `<结束时间>_<会话 key>.md` 并提交。agent 回答过的斜杠命令——
`/mh load`——按你敲的原样保留；没人回答的（`/clear`、`/model`）是框架噪音，直接丢掉。

时间戳取会话的**结束**时间，所以按时间合并加载时顺序反映工作真正发生的时刻。
一个会话只存在于一个检查点：重新保存是替换，不会重复——即使当前指针已经移走，
不带目标的 `mh save` 仍在原处更新，`mh save --to <ckpt>` 则把它搬过去。hook 和
地图上的保存按钮遵循同一条规则。

`mh save --compact --file <md>` 则存入一份摘要，替代完整对话。**mh 自己不做摘要**——
它没有模型也不联网，撰写摘要的是驱动会话的 agent，skill 里带了这套流程，所以你只要说
"压缩保存"即可。在没有 agent 的 shell 里直接跑会**故意失败**，而不是退回去存提纯对话。
压缩保存落在会话真正的身份下，因此会替换同一会话的提纯版本——每个会话只保留一种表示。

## 全自动：`mh hook install`

skill 依赖 agent *记得*运行 mh，hooks 把"记得"这一步也去掉：

```sh
mh hook install          # 本项目（.claude/settings.local.json）
mh hook install --user   # 所有项目（~/.claude/settings.json）
```

从下一次 Claude Code 会话开始：**SessionStart** 运行 `mh load`，输出直接注入会话
上下文，记忆在第一句话之前就已到位；**SessionEnd** 和 **PreCompact** 运行
`mh hook save`——后者赶在压缩销毁对话之前抢先存档。

hook 处理器刻意宽容：没有中枢、没有当前检查点、没东西可存，都安静地以 0 退出，
所以 `--user` 全局安装绝不打扰不用 mh 的项目。它也尊重会话中的显式选择——已经
`--compact` 保存的会话原样保留，`--to` 路由到别的检查点的会话在原处更新而不是
重复。随时可撤销：`mh hook install --remove`。

## 地图：`mh ui`

```console
$ mh ui
mh ui: http://127.0.0.1:7777/?t=<每次启动新生成的 token>
```

`mh ui --detach` 把服务放到后台并打印 URL——在 agent 会话里 `/mh ui` 跑的就是它，
实时面板会钉在发起请求的那个会话上（`$CLAUDE_CODE_SESSION_ID`）。钉住只在会话还活着时
有效：静默十分钟且项目里有更新的 transcript，页面就转而跟随最新的，并说明原因。再跑
一次只会打印已在运行的服务的 URL；`mh ui --stop` 结束它；`mh status` 会显示它。
`mh skill install` 还会装上 **`/mh-ui`**——只做这一件事的一段话 skill，只占约 150 个
token 的上下文，而不用加载整个 `/mh` 工作流。

一条检查点时间线：节点大小对应会话数，链接用弧线相连，当前指针带外圈高亮，并按 token
预算标出下一次 `mh load` 实际会包含哪些会话。点进去可以**删除或改写单独一轮对话**、
删除或移动会话，以及重命名、删除、链接检查点。每次改动都是中枢里的一次提交，
`git -C .memoryhub revert` 就是撤销。在终端里做的改动几秒内就会出现在地图上。`--read-only` 只看不改，编辑入口全部隐藏。
同样的整理操作在终端里也有——`mh rm`、`mh mv`、`mh rename`、`mh edit`——agent
不用浏览器也能按要求整理记忆。

时间线是可以动手的，不只是一张图：**点一个节点**就弹出它的菜单——打开、设为当前
（下一次 `mh save`、`mh load` 用的那个）、子检查点、在同一阶段再开一个、链接、取消链接、
重命名、删除——每一项都带一行说明，用不上的置灰而不是点了才报错。打开后，检查点在下面
展开：标题行说明这是什么，同样的操作排成工具栏，再往下是它的会话。每一行会话前有个复选框：取消勾选，`mh load` 就不再带上它——
文件仍留在检查点里，`mh show` 和地图都还能看到，只是变淡并标上"skipped on load"
（终端里是 `mh skip` / `mh unskip`；名单存在中枢的 `skip.toml`，重命名、移动都会跟着走）。
还没到的阶段（虚线）则可以创建、重命名、移除、在前后插入
阶段、往前或往后挪——改的是中枢自己的 `template.toml`，所以是模板去适应项目，而不是
反过来。把一个代表阶段的检查点改名，阶段也会跟着改。页面上的每个提问——起名、选目标、
"确定删除？"——都是页内弹出的小面板，从不用浏览器对话框，所以 agent 也能驱动这张地图。

页面最底下是**项目记忆**——Claude Code 为这个项目记下的笔记
（`~/.claude/projects/<project>/memory/`），只读展示：每条笔记一张卡片，带类型、
markdown 正文、它链接到的其它笔记（`[[name]]`，可点），以及在原始 transcript 还在
本机时、在单独一页里打开它所来自的那次会话。这个文件夹不归 mh 所有，mh 从不写它，只是把它放在
检查点旁边一起显示。

面板下面是**当前正在进行的会话**（页眉的 `● live session` 按钮开关整个面板，开着时高亮，
重新加载也记得）：agent
此刻正在写的 transcript，一有增长就重新读取，所以你在终端里说的话过一两秒就出现在浏览器里。默认只展示最新的三轮，
更早的一键展开，地图不会被一场长会话顶到看不见。这里是**不过滤**的：思考、正文、每一次工具调用，按 agent 真正
产生的顺序排开，同一次回复里发出的多个工具调用会收在一条竖线下面，标成它们真实运行的
并行批次，子 agent 的输出也标出来是它的——因为看一场正在发生的会话时，工具调用
就是会话本身。图片也会显示：你贴进会话的图，或 agent 读过的截图，都出现在那一轮下面——
由 mh 直接从 transcript 或文件里提供，绝不复制进中枢。（**存下来**的仍然是提纯后的对话；
面板上的 "thinking" 和 "tool calls" 两个勾选框各自关掉那一部分——它们只改变页面显示什么，不影响 agent 本身。）
会话还在跑，就可以整理它——丢掉某一轮、改写某个回答、再把它们恢复回来。这些决定存成中枢旁边的一份草稿
（`.memoryhub/drafts/`，不追踪，不进日志），并且**每一次**保存这个会话时都会应用：
`mh save`、SessionEnd/PreCompact hook、面板上的保存按钮都一样。所以会话中途整理掉的
内容不会在最终保存时又回来，而整理之后新产生的对话照样会进去。agent 正在回答的那一问
会显示出来，但不会被保存——`mh save` 一直就是这么丢掉它的。

面板顶部的**保存框**写明怎么存、存到哪里：目标检查点（会话已经在的那个，否则就是当前检查点；
换一个就把会话挪过去）、两种存法各带一句说明、摘要可选的 focus，以及一个写明将要做什么的按钮。
**对话**就是机械保存。**摘要**则请运行这个会话的
CLI 来写摘要：mh 把提纯后的对话以 print 模式交给它（`claude -p`、`pi -p`），用的是该工具
自己的压缩格式——Claude Code 的编号续接摘要、pi 的 Goal / Progress / Next Steps 检查点——
在一个临时目录里运行，关闭工具和会话持久化，再把结果存为压缩保存。正在运行的会话不受任何
影响；代价是你账户上的一次模型调用。可选的 focus 相当于 `/compact <instructions>`。终端里
对应 `mh save --compact --with agent`。codex 会话暂无压缩。

安全性：只监听回环地址，每个请求都要带启动时生成的一次性 token，并校验 `Host` 头；
页面完全自包含，离线可用。**mh 绝不改写自己无法逐字节复现的文件**——先解析再重新渲染，
对不上就标为只读。提纯后的对话经常引用 mh 自己的输出（讨论 MemoryHub 的会话正文里就有
`## User 1` 这样的行），这个保护让编辑不会把一轮对话劈成两半。

## 接管一个已有历史的项目

```console
$ mh init
$ mh import --dry-run     # 先看看都有什么
$ mh import
imported 17 sessions -> history (claude 11, codex 1, pi 5)
```

`mh import` 会在 Claude Code、pi 和 Codex 的会话目录中发现本项目的历史，用每个会话
自己记录的 `cwd` 校验（兄弟项目不会混进来），逐个提纯后作为一次提交落入 `history`
检查点。范围跟随当前目录：在仓库根目录运行导入整个项目，在子目录运行只导入那条工作线。
已保存过的会话会跳过，所以之后再次运行只补新增的。

## 值得了解的

- **加载**：`mh load` 取当前检查点（或你指定的），沿链接扩展，在 `--budget` 内
  从旧到新输出完整会话（默认 20000 tokens——约 200k 上下文的十分之一，三四个
  典型会话——保留最新的一段连续后缀；SessionStart hook 的大小另由
  `mh hook install --budget N` 指定）。
- **token 估算认识中日韩文**：CJK 每字约 1 token，ASCII 约 4 字符 1 token——
  做预算足够准，且不引入分词器依赖。
- **名字不限文种**：`mh checkpoint 数据管道` 和 `mh checkpoint backtest`
  一样是一等公民。
- **同一阶段可以有多个检查点**：`design`、`design-2`、`design-3` 在时间线上是穿过
  这个阶段的并行分支，各自都连着前后的阶段——名字末尾带数字就是同一阶段的又一次尝试，`mh checkpoint --at design`
  会替你编号。`mh checkpoint dollar-bars --at research` 把一个名字里看不出阶段的
  检查点放到某个阶段（记在中枢的 `stages.toml` 里）。它们和别的检查点一样彼此独立——
  要一起加载就 link——所以并行的尝试，或者一个 worktree 一个尝试，各有各的记忆，
  又不会离开它们所属的阶段。
- **子检查点**：检查点之下更小的范围。`mh checkpoint head-page --under design`
  （或 `mh checkpoint design.head-page`）建出 `design.head-page`，存在 design 的目录里，
  在它的节点下缩进画出。它是范围，不是"再来一次"：加载它会连父级一起加载（在
  `design.head-page` 上 `mh load` 也会带上 design 的会话），只加载 design 则只有 design；
  `--tree` 则按整个节点加载——包里的每个检查点（链接进来的也算）都带上它所在节点的全部
  子检查点，所以在 `design.head-page` 上就是整个 design（`mh hook install --tree`
  让会话开始时注入的包也这么做，地图上的 "with sub-checkpoints" 勾选框可以预览）。
  父级改名、删除，子检查点跟着走；它们不算模板阶段。地图的检查点面板会列出它们，
  并提供 "+ sub-checkpoint…"。
- **阶段模板**：大多数项目走的是同一副骨架——计划、设计、开发、测试、部署、
  监控——各领域只是每一步叫法不同。`mh template --list` 列出十套（quant、
  frontend、backend、sdlc、mobile、devops、data、ml、sprint、hotfix）；
  `mh template quant`（或 `mh init --template quant`）把它记进中枢，之后
  `mh checkpoint` 不给名字就创建下一个阶段，`mh status` 报告项目走到了哪一步，
  地图把还没到的阶段画成虚线节点，点一下就建——第一个检查点还没建时也画；状态行写着项目走到了哪一步。
  选模板是终端里的事，地图不管。不会预先建好所有阶段，时间线上
  的日期都是真实的。中枢里的 `template.toml` 存着这份阶段列表的副本：改它，
  项目就有了自己的顺序。
- **可回溯到源头**：保存下来的会话记着它提纯自哪个 transcript 的 id。
  `mh trace <ckpt>/<session>` 把它解析成本机上的原始 `.jsonl`（不在本机就直说）；
  在地图里，保存会话的面板上有 **open original ↗**，点开会在**单独的一页**里显示完整
  未过滤的 transcript——思考、工具调用、图片都在（`?view=<id>`：只有这一个 transcript，
  一直钉住），提纯后的会话和它的源头可以并排看。中枢里不存任何跟机器绑定的东西，
  id 本身就是这条链接。
- **每一次变更都是一次 git 提交**。撤销、重命名、删除、合并都可以直接用
  `git -C .memoryhub ...`——中枢就是个普通仓库。
- **是 exclude 不是 ignore**：`mh init` 写项目里的 `.git/info/exclude`，
  不动你已纳入版本控制的 `.gitignore`。
- **持久性**：中枢被排除在项目仓库外，项目的远端不会备份它——配置一次 `origin`
  然后用 `mh sync`。
- **并发**：由 git 自己的 `index.lock` 串行化，没有自造的锁。

## 开发

```sh
git clone https://github.com/solknight48/memoryhub
cd memoryhub
uv run pytest                  # 完整 E2E 套件，在隔离的 HOME 中以子进程跑 CLI
uv run ruff check && uv run ruff format --check   # CI 跑的就是这两条
uv tool install --force -e .   # 让装好的 mh 就是你在改的代码
```

改动必须守住的不变量见 [CONTRIBUTING.md](CONTRIBUTING.md)；什么时候改了什么见
[CHANGELOG.md](CHANGELOG.md)。

`purify.py` 内联自 `purify-context` skill，有一致性测试把提取语义钉在它上面。
`curate.py` 是唯一解析会话 markdown 的代码，绝不能改写"解析 → 重新渲染"无法逐字节
还原的文件。`server.py` 刻意只用标准库，好让 `typer` 保持为唯一运行时依赖。

## 许可证

[MIT](LICENSE)。
