# MemoryHub (`mh`)

[English](README.md) | **简体中文**

用 Git 式的检查点管理 AI 会话上下文。

每一次 Claude Code 会话都从零开始。MemoryHub 解决的正是这件事：会话结束时，
`mh save` 会把它**提纯**（只保留 User/Agent 对话——工具调用、思考过程和框架噪音
全部按规则剥除，纯机械处理，不消耗任何 LLM 费用），然后存入一个**检查点**
（checkpoint）。检查点是一个子中枢：一个具名的提纯会话容器。检查点之间默认
**互相独立**；把两个**链接**起来，它们就会**一起加载，并按时间顺序合并**。
新会话运行 `mh load`，就把项目的记忆取了回来。

```
.memoryhub/                                  ← 中枢（hub）：一个普通的 git 仓库
  checkpoints/
    2026-07-14_1650_data-pipeline/           ← 检查点：<创建时间>_<名称>/
      2026-07-10_1432_a1b2c3d4.md            ← 提纯会话：<时间>_<会话 id>.md
      2026-07-12_0910_e5f6a7b8.md
    2026-07-17_1820_backtest-scaffold/
      2026-07-15_1100_c9d0e1f2.md
  links.toml                                 ← 被链接的检查点会一起加载
  current                                    ← 未纳入版本控制的指针：当前检查点
```

## 安装

```sh
uv tool install git+https://github.com/solknight48/memoryhub
mh skill install           # 让 Claude Code 会话学会这套工作流
```

**环境要求**：Linux 或 macOS，git ≥ 2.32，Python ≥ 3.12。`mh` 通过调用系统的
`git` 工作，不依赖任何平台特有的东西；测试套件在两个系统上都跑过。Windows 未经测试。

### 更新，以及从克隆仓库使用

`uv tool install` 会**复制**源码，所以从本地路径装出来的是一份**快照**：在克隆仓库里
`git pull` 并不会改变已安装的 `mh`，像 `mh ui` 这样的新命令根本不会出现。二选一：

```sh
# 跟随你的工作区——每一次编辑、每一次 `git pull` 都即时生效，
# 之后不需要再做任何更新动作
uv tool install --force -e .

# 或者按需重新生成快照，从克隆仓库或直接从 GitHub
uv tool install --force .
uv tool install --force git+https://github.com/solknight48/memoryhub
```

查看自己装的是哪一种：

```sh
cat "$(uv tool dir)"/memoryhub/lib/python*/site-packages/memoryhub-*.dist-info/direct_url.json
```

出现 `"editable": true` 就说明它跟随你的工作区。如果 `mh --help` 里少了某个你确定
源码中已有的命令，原因就在这里。

## 快速上手

```console
$ cd ~/dev/tickstore
$ mh init                        # 在项目根目录建立中枢；并打印一段 CLAUDE.md 片段
$ mh checkpoint data-pipeline    # 创建检查点；它成为当前检查点

# ……和 Claude 一起工作；会话结束时（通过 skill，agent 会自己执行）：
$ mh save
saved 2026-07-18_0941_7aee4e68.md -> data-pipeline (1 sessions)

# 下一次会话，热启动：
$ mh load
<!-- mh | loaded: data-pipeline | 1 of 1 sessions | @ 3f1c2ab -->
...

# 第二条工作线，之后与第一条链接起来：
$ mh checkpoint backtest
$ mh save
$ mh link data-pipeline backtest
$ mh load                        # 两者的会话，按时间顺序合并
<!-- mh | loaded: backtest + data-pipeline (linked) | 3 of 3 sessions | @ 9d8e7f6 -->
```

## 命令

| 命令 | 作用 |
|---|---|
| `mh init [--global] [--claude]` | 创建中枢（`--claude` 会把 Memory 片段追加进 CLAUDE.md）。 |
| `mh checkpoint <name>` | 新建检查点（子中枢），并设为当前。 |
| `mh save [--to CKPT] [--file MD] [--session-id ID] [--transcript P]` | 把当前会话提纯后存入某个检查点。 |
| `mh import [--to CKPT] [--agent A]... [--dry-run]` | 回填：发现本项目在当前目录子树下启动过的历史会话（Claude Code、pi、Codex），导入某个检查点。 |
| `mh load [CKPT...] [--no-links] [--budget N] [--all] [--json]` | 热启动上下文包：所选检查点 + 链接闭包，按时间合并。 |
| `mh link A B` / `mh unlink A B` | 让两个检查点一起加载 / 取消。 |
| `mh list` / `mh show CKPT[/SESSION]` / `mh search Q` | 查看中枢内容。 |
| `mh back [N]` / `mh forward [N]` / `mh goto CKPT` | 在按时间排序的检查点之间移动当前指针。 |
| `mh status` | 当前位置、数量统计、新鲜度、远端。 |
| `mh log` | 中枢的 git 日志（每一次变更都是一次提交）。 |
| `mh sync` | 对 `origin` 执行 `pull --rebase` + `push`；冲突时自动中止并还原中枢。 |
| `mh hubs [--prune]` | 列出所有已注册的中枢。 |
| `mh ui [--port N] [--read-only]` | 在浏览器里打开检查点地图，并整理中枢。 |
| `mh skill install` | 安装 Claude Code skill。 |

## `mh save` 到底做了什么

一趟确定性的处理——不调用 LLM，不联网：

1. **确定目标检查点** —— `--to CKPT`（完整 slug、唯一前缀，或 `mh list` 中从 1 开始的
   序号），否则用 `current` 指针。既没有当前检查点又没给 `--to` 会直接报错，绝不会
   悄悄选一个默认值。
2. **找到 transcript**，先匹配到的胜出：`--transcript PATH`（自动识别格式）→
   `--session-id ID` 或 `$CLAUDE_CODE_SESSION_ID`（在 `~/.claude/projects/*/` 下
   通配查找）→ 否则取本项目在所有 agent 中最新的那份 transcript，因为正在进行的
   会话必然是自己最新的一份。（`--file MD` 会跳过第 2–5 步，原样存入你给的 markdown。）
3. **配对对话** —— 按顺序遍历 JSONL，把每个用户轮次与紧随其后的助手文本配成一对。
   连续的、未被回答的用户消息会合并成一个 **User** 轮次；出现在任何提问之前的助手
   文本会被忽略。
4. **剥掉一切不是对话的内容** —— 全部按规则机械执行：
   - 助手的**思考块、工具调用与工具结果**——只有 `type: "text"` 的内容块保留；
   - **子 agent 的往来**与元记录（`isSidechain`、`isMeta`）；
   - 消息中任意位置的 `<system-reminder>…</system-reminder>` 块；
   - 以 `<command-name>`、`<command-args>`、`<local-command-stdout>`、
     `<bash-input>`、`<bash-stdout>`、`<user-prompt-submit-hook>` 等**开头**的框架
     包装消息——只匹配开头，所以正文里只是提到某个标签的真实提问会被保留；
   - 被 `[Request interrupted by user` / `[Request cancelled` 打断的轮次。
5. **丢弃末尾未被回答的那一轮** —— 触发这次保存的那句"保存本次会话"永远不会进入
   记录。（`mh import` 会保留它：归档式导入保留完整历史。）如果这一步之后什么都不剩
   就会报错，所以空会话永远不会变成一个空文件。
6. **写入 `<结束时间>_<key>.md`** 到检查点目录。时间戳取会话的**结束**时间——最后
   一条记录的时间戳，转成本地时间，取不到就退回 transcript 的 mtime——这样按时间合并
   加载时，顺序反映的是工作真正发生的时刻，即使会话是很久以后才保存的。key 是会话
   身份：`7aee4e68`（Claude，uuid 的前 8 位）、`pi-…` 或 `cx-…`。**该检查点中同 key
   的已有文件会先被删除**——重新保存同一个会话是替换，并把它移到新的结束时间上，
   绝不会产生重复。
7. **提交** —— 在中枢里执行 `git add -A` 并提交 `save: <文件> -> <检查点>`。
   没有产生任何改动的保存不会产生提交。

渲染出的文件以 `# Session Context` 开头：一行溯源信息（来源 transcript、会话 id、
轮次数量），随后是由 `---` 分隔的 `## User 1` / `## Agent 1` 配对。被回答但没有
文本内容的轮次渲染为 `_(no textual reply captured)_`。

```markdown
# Session Context

_Pure dialog extracted from `7aee4e68-….jsonl` (session `7aee4e68-…`). 12
exchanges. Tool calls, results, and internal reasoning removed._

## User 1

I want to build a memory management extension for terminal use.

## Agent 1

A "git for context" — nice concept. Let me take a quick look …
```

## 地图：`mh ui`

```console
$ mh ui
mh ui: http://127.0.0.1:7777/?t=iZOfgx9wYdtc7eA9YTSyYQ
```

一条检查点时间线——节点大小对应会话数量，被链接的检查点用弧线相连，当前指针带外圈
高亮，并按你设定的 token 预算标出下一次 `mh load` 实际会包含哪些会话。点击检查点查看
它的会话，点击会话查看它的每一轮对话。

在这里你可以**删除或改写单独一轮对话**、删除或移动整个会话，以及重命名、删除、链接
和解除链接检查点。每一次改动都是中枢里的一次提交（在 `mh log` 中显示为 `curate: …`），
所以 `git -C .memoryhub revert` 就是撤销手段。`--read-only` 只提供地图，不允许编辑。

有两点让这种编辑是安全的，而不是鲁莽的：

- **mh 绝不改写自己无法复现的文件。** 每次编辑前，它会先解析该会话再重新渲染；
  除非结果与原文件逐字节一致，否则该会话在界面上标为只读并原样保留。这一点很重要，
  因为提纯后的对话经常会*引用 mh 自己的输出*——一个讨论 MemoryHub 的会话，正文里
  就含有 `## User 1` 这样的行——而一个猜错了的解析器会悄悄把一轮对话劈成两半。
- **在确认能够提交之前，什么都不会被写入。** 整理操作是先写文件再提交；如果提交在
  之后失败，改动就会留在磁盘上却不在日志里。mh 会*先*检查中枢能否提交，所以报错就
  意味着什么都没有发生。

服务只监听回环地址，且每个请求都要带上启动时生成的一次性 token（否则浏览器里的任何
页面都能向 `127.0.0.1` 发 POST），同时校验 `Host` 头，使得恶意域名无法指向这个端口。
页面完全自包含——不用 CDN、不联网——因此离线可用。

## 接管一个已有历史的项目

```console
$ cd ~/dev/legacy-project
$ mh init
$ mh import --dry-run     # 先看看都有什么，覆盖所有 agent
$ mh import
imported 17 sessions -> history (claude 11, codex 1, pi 5)
$ mh load                 # 项目的全部过往，按时间合并
```

`mh import` 会在 **Claude Code**（`~/.claude/projects`）、**pi**
（`~/.pi/agent/sessions`）和 **Codex**（`~/.codex/sessions`）中发现本项目的历史会话，
并用每个会话自己记录的 `cwd` 做校验（因此兄弟项目的会话绝不会混进来），逐个机械提纯，
最终作为一次 git 提交落入 `history` 检查点（可用 `--to` 覆盖）。

**范围跟随你的当前目录**：在仓库根目录运行会导入整个项目的历史；在子目录运行则只导入
在该子树下启动过的会话——一次处理一条工作线：

```console
$ cd ~/dev/legacy-project/backtest
$ mh import --to backtest     # 只导入 backtest 这条工作线的会话
```

已经保存过的会话会被跳过，所以之后再次运行 `mh import` 只会补上新增的部分。归档式导入
会保留最后那个未被回答的轮次（这与实时的 `mh save` 不同，后者会丢弃触发它的那句请求）。
新增一个 agent，只需要在 `src/memoryhub/agents.py` 里加一个发现函数和一个提取函数。

## 值得了解的语义

- **加载**：`mh load` 取当前检查点（或你指定的那些），沿链接扩展（连通分量），并在
  `--budget` 范围内按从旧到新输出完整会话（默认约 6000 tokens；筛选时保留最新的一段
  连续后缀，末尾的省略脚注会列出被裁掉的部分）。
- **保存**见上文详解：每个检查点中每个会话一个文件，以会话身份为 key，以会话结束时间
  为时间戳。
- **走动**只移动那个未纳入版本控制的 `current` 指针；不会检出任何东西，所有检查点都
  留在磁盘上。
- **每一次变更都是中枢里的一次 git 提交**（`mh log`）。撤销、手术、重命名、删除、
  合并：直接用 `git -C .memoryhub ...`——中枢就是个普通仓库，mh 从不跟你抢。
- **是 exclude，不是 ignore**：`mh init` 写的是项目里的 `.git/info/exclude`（仅本地
  生效），不会去动你已纳入版本控制的 `.gitignore`。
- **并发**：两个会话同时写同一个中枢，由 git 自己的 `index.lock` 串行化；mh 会给出
  重试提示。没有自造的锁。
- **持久性**：中枢被排除在项目仓库之外，所以项目的远端**不会**帮你备份它——配置一次
  `origin`，然后用 `mh sync`。
- 与 `purify-context` skill 的关系：提取逻辑相同（已内联并有一致性测试）。那个 skill
  仍适用于临时导出；`mh save` 则是提纯 + 存储 + 提交，一步完成且确定性。

## 开发

```sh
git clone https://github.com/solknight48/memoryhub
cd memoryhub
uv run pytest              # 完整 E2E 测试套件（在隔离的 HOME 中以子进程跑 CLI）
uv tool install --force -e .   # 让装好的 `mh` 就是你正在改的代码
```

结构：`src/memoryhub/{cli,hub,git,purify,checkpoint,load,agents,curate,server}.py`；
Claude Code skill 与 `mh ui` 页面作为包数据放在 `src/memoryhub/{skill,ui}/`。

- `purify.py` 内联自 `purify-context` skill——一个一致性测试把提取语义钉在它上面，
  当那个 skill 不在本机时该测试会跳过。
- `curate.py` 是唯一解析会话 markdown 的代码（`load`、`show`、`search` 都是逐字读取
  文件），并且绝不能改写那些"解析 → 重新渲染"无法逐字节还原的文件。
- `server.py` 刻意只用标准库，好让 `typer` 保持为唯一的运行时依赖；它的 `dispatch()`
  是一个普通函数，因此测试 API 不需要真的开 socket。
