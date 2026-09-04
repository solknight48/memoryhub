<p align="center">
  <a href="https://github.com/solknight48/memoryhub/blob/main/README.md">English</a> · <strong>简体中文</strong>
</p>

![MemoryHub 地图：一个项目的会话，作为时间线上的检查点](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/map.png)

# MemoryHub

**把每一场 AI 编程会话当作 git 管着的记忆来管理——提纯后保存，下次装回来，在地图上整理。**

MemoryHub（`mh`）是一个小小的 Python CLI 加一张本机网页地图，面向 Claude Code、pi 和 Codex。会话结束，`mh save` 把它留下；下一场会话 `mh load`，项目记忆就回来了；`mh ui` 是你管理这一切的地方。

- **每场会话都留下，噪音一点不留**——按规则提纯成 User/Agent 对话，不调用模型，存成检查点里的一个文件，提交进你自己的 git 仓库
- **该装的时候装回来**——下一场会话从你所在的检查点出发，带上它的父级和链接，最新的优先，在 token 预算之内
- **整理，而不是囤积**——跳过一场会话、删掉或改写一轮、把会话挪走、改存摘要，地图上或终端里都行
- **长成项目的样子**——模板给出阶段，同一阶段可以并行几次尝试，子检查点划出更小的范围，该一起加载的用链接连起来

[![CI](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml/badge.svg)](https://github.com/solknight48/memoryhub/actions/workflows/ci.yml)
![License](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)
![Python](https://img.shields.io/badge/python-3.12%2B-3776ab?style=flat-square)
![Agents](https://img.shields.io/badge/agents-Claude%20Code%20%C2%B7%20pi%20%C2%B7%20Codex-7C3AED?style=flat-square)
[![PyPI](https://img.shields.io/pypi/v/memoryhub-mh?style=flat-square&color=0891b2)](https://pypi.org/project/memoryhub-mh/)

```bash
uv tool install memoryhub-mh && mh skill install
```

Linux 或 macOS · git ≥ 2.32 · Python ≥ 3.12 · 也可以 `pipx install memoryhub-mh` 或 `pip install memoryhub-mh`。新变化见[更新日志](https://github.com/solknight48/memoryhub/blob/main/CHANGELOG.md)。

## 看看它的样子

下面是地图在一个小咖啡馆网站项目上的真实截图，不是效果图。

| 点一个节点 | 打开一个检查点 | 保存正在进行的会话 |
|---|---|---|
| ![节点菜单：打开、设为当前、子检查点、再来一次、链接、重命名、删除](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/node-menu.png) | ![一个检查点的会话；其中一场取消了勾选，加载时跳过](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/checkpoint.png) | ![保存框：对话还是摘要，存到哪个检查点](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/save-box.png) |
| 能对它做的一切，每项一句说明。 | 取消勾选一场会话，之后每次加载都不带它。 | 原样存对话，或者存 agent 写的摘要。 |

一场已保存的会话就是对话本身，别无其他。可以改写或删除单独一轮；中枢保留历史。

![一场已保存、提纯后的会话，每轮都有编辑和删除](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/session.png)

正在进行的会话，连思考和工具调用一起显示，顶部是保存框。

![实时会话面板与保存框](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/live.png)

新建检查点：模板里的下一个阶段、同一阶段的另一次尝试、子检查点，或任意名字。

![新建检查点菜单](https://raw.githubusercontent.com/solknight48/memoryhub/main/docs/img/new-checkpoint.png)

## 快速上手

### 1. 安装

```bash
uv tool install memoryhub-mh   # 或：pipx install memoryhub-mh · pip install memoryhub-mh
mh skill install               # 让 Claude Code 学会 /mh 工作流
```

包名是 `memoryhub-mh`，命令是 `mh`。机器上没有 Python 3.12 时 `uv` 会自己取一个；`pipx` 和 `pip` 需要先装好。

### 2. 给项目一个中枢

```bash
cd my-site
mh init --template frontend   # .memoryhub/，带上前端项目的阶段
mh checkpoint                 # 第一个阶段：requirement-analysis
```

### 3. 干活、保存、加载

```bash
# …… 和 Claude Code 一起干活；结束时 agent 会运行：
mh save                       # 这场会话提纯后存入检查点
# 下一次：
mh load                       # 记忆回到上下文里
mh ui                         # 打开地图
```

`mh hook install` 让 Claude Code 在会话开始时自动 load、结束时自动 save。

## 管理会话

| 你想要 | 地图上 | 终端里 |
|---|---|---|
| 留下这场会话 | 保存框 → **Dialog** | `mh save` |
| 改存一份摘要 | 保存框 → **Summary** | `mh save --compact --with agent` |
| 加载时不带某场会话 | 取消勾选 | `mh skip CKPT/SESSION` |
| 改写或删掉某一轮 | 该轮的 edit / delete | `mh edit`、`mh rm -x N` |
| 把会话挪到别处 | 那一行的 move… | `mh mv CKPT/SESSION CKPT` |
| 让两个检查点一起加载 | 节点 → Link to… | `mh link A B` |
| 在更小的范围里工作 | 节点 → Sub-checkpoint… | `mh checkpoint NAME --under CKPT` |
| 同一阶段并行再试一次 | 节点 → Another take | `mh checkpoint --at STAGE` |
| 整个节点一起加载 | 勾选 "with sub-checkpoints" | `mh load --tree` |
| 找到会话的来源 | open original ↗ | `mh trace CKPT/SESSION` |
| 导入过去的会话 | — | `mh import` |
| 撤销任何改动 | — | `git -C .memoryhub revert HEAD` |

## 为什么用 MemoryHub

- **机械地提纯**——工具调用、思考、框架包装和末尾没回答的问句都按规则剥掉。存下来的读起来就是那场对话，而且不花一分钱。
- **是 git 仓库，不是数据库**——`.memoryhub/` 是普通仓库里的普通 markdown：可以 diff、push、revert，不装 mh 也能读。
- **默认彼此独立**——检查点各自加载，除非你把它们链接起来；子检查点在父级之内加载；再来一次是一条并行的路，不是副本。
- **地图说实话**——紫色就是下一次 `mh load` 会装的东西；加载够不到的链接是灰的；终端里的改动一次轮询内就出现。
- **只在本机**——回环地址、每次启动一个 token、不上云。除非你 push 中枢，什么都不会离开这台机器。唯一的一次模型调用（写摘要）用的也是你本来就在用的 CLI。

## 工作原理

| 步骤 | 发生了什么 |
|---|---|
| **保存** | 找到会话的 transcript，把每个用户轮次和随后的回答配对，其余全部剥掉。 |
| **存放** | 对话以 `<结束时间>_<会话>.md` 落在当前检查点里，中枢里一次提交。一场会话只住在一个检查点。 |
| **加载** | 当前检查点、它的父级和链接；会话按时间合并，最新优先，在预算之内（默认 20 000 token）。 |
| **地图** | `mh ui` 画出中枢：阶段、尝试、子检查点、链接、下一次加载会装什么，以及此刻正在写的会话。 |
| **整理** | 跳过、编辑、移动、摘要都是和别的一样的提交；地图和 CLI 对每件事共用一条规则。 |

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

## 全自动

```bash
mh hook install            # 本项目：会话开始时 load，结束时 save
mh hook install --user     # 所有项目
mh hook install --remove   # 撤销
```

SessionStart 注入 `mh load`；SessionEnd 和 PreCompact 运行 `mh save`。

## 参考与范围

- [CONTRIBUTING.md](https://github.com/solknight48/memoryhub/blob/main/CONTRIBUTING.md)——改动必须守住的不变量 · [CHANGELOG.md](https://github.com/solknight48/memoryhub/blob/main/CHANGELOG.md)——何时改了什么
- `scripts/showcase.py` 用一个一次性项目重新生成上面的截图
- 有意不做的：托管服务、往正在运行的会话里打字、在地图上选模板

## 许可证

[MIT](https://github.com/solknight48/memoryhub/blob/main/LICENSE)——自由使用、修改和分发。

## 参与贡献

欢迎 issue 和 pull request。从[贡献指南](https://github.com/solknight48/memoryhub/blob/main/CONTRIBUTING.md)开始；每个改动都要保持测试套件密闭、两份 README 同步。
