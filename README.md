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
| `mh init [--global] [--claude]` | 创建中枢。 |
| `mh checkpoint <name>` | 新建检查点，并设为当前。 |
| `mh save [CKPT] [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | 提纯当前会话并存入检查点。 |
| `mh save [CKPT] --compact --file MD` | 存入 agent 撰写的摘要，替代完整对话。 |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | 回填本项目的历史会话（Claude Code、pi、Codex）。 |
| `mh load [CKPT...] [--no-links] [--budget N] [--all] [--json]` | 热启动上下文包：所选检查点 + 链接闭包，按时间合并。 |
| `mh link A B` / `mh unlink A B` | 让两个检查点一起加载 / 取消。 |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | 查看中枢内容。 |
| `mh rm CKPT[/SESSION] [-x N] [--force]` | 删除检查点、会话，或单独一轮对话。 |
| `mh mv CKPT/SESSION CKPT` / `mh rename CKPT NAME` | 移动会话 / 重命名检查点。 |
| `mh edit CKPT/SESSION -x N [--user T] [--agent T]` | 改写一轮对话的某一侧。 |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | 移动当前指针。 |
| `mh status` / `mh log` | 位置与统计 / 中枢的 git 日志。 |
| `mh sync` | 对 `origin` 执行 `pull --rebase` + `push`，冲突自动中止。 |
| `mh hubs [--prune]` | 列出所有已注册的中枢。 |
| `mh ui [--port N] [--budget N\|none] [--read-only]` | 在浏览器里打开检查点地图并整理中枢。 |
| `mh hook install [--user] [--remove]` | 通过 Claude Code hooks 自动 load/save。 |
| `mh skill install` | 安装 Claude Code skill。 |

## 保存：提纯，或压缩

`mh save` 是一趟确定性处理，不调用 LLM、不联网：找到本次会话的 transcript，
按顺序把每个用户轮次与其后的助手文本配对，剥掉一切不是对话的内容（思考块、工具调用与
结果、子 agent 往来、`<system-reminder>`、框架包装消息、被打断的轮次），丢弃触发这次
保存的末尾问句，然后写入 `<结束时间>_<会话 key>.md` 并提交。

时间戳取会话的**结束**时间，所以按时间合并加载时顺序反映工作真正发生的时刻。
每个检查点中每个会话只有一个文件：重新保存是替换，不会重复。

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

一条检查点时间线：节点大小对应会话数，链接用弧线相连，当前指针带外圈高亮，并按 token
预算标出下一次 `mh load` 实际会包含哪些会话。点进去可以**删除或改写单独一轮对话**、
删除或移动会话，以及重命名、删除、链接检查点。每次改动都是中枢里的一次提交，
`git -C .memoryhub revert` 就是撤销。`--read-only` 只看不改，编辑入口全部隐藏。
同样的整理操作在终端里也有——`mh rm`、`mh mv`、`mh rename`、`mh edit`——agent
不用浏览器也能按要求整理记忆。

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
  从旧到新输出完整会话（默认约 6000 tokens，保留最新的一段连续后缀）。
- **token 估算认识中日韩文**：CJK 每字约 1 token，ASCII 约 4 字符 1 token——
  做预算足够准，且不引入分词器依赖。
- **名字不限文种**：`mh checkpoint 数据管道` 和 `mh checkpoint backtest`
  一样是一等公民。
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
uv tool install --force -e .   # 让装好的 mh 就是你在改的代码
```

`purify.py` 内联自 `purify-context` skill，有一致性测试把提取语义钉在它上面。
`curate.py` 是唯一解析会话 markdown 的代码，绝不能改写"解析 → 重新渲染"无法逐字节
还原的文件。`server.py` 刻意只用标准库，好让 `typer` 保持为唯一运行时依赖。

## 许可证

[MIT](LICENSE)。
