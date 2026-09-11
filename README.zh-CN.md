[English](./README.md) | **简体中文**

<div align="center">

<img src="assets/icons/terminal-2.svg" width="64" alt="" />

# unbury

*一条命令，把编码智能体（coding agent）跑完的会话变成一张答案卡片。*

<img src="https://readme-typing-svg.demolab.com?font=JetBrains+Mono&size=22&pause=1300&color=58A6FF&center=true&vCenter=true&width=640&lines=your+agent+fixed+the+bug%E2%80%A6;then+buried+the+answer;unbury+it+%E2%80%94+one+command%2C+zero+config" alt="typing: your agent fixed the bug, then buried the answer — unbury it, one command, zero config" />

你的编码 agent 刚把 bug 修完——然后答案就被埋进上千行推理叙述和原始工具输出里。`unbury` 直接读取已经结束的 **Claude Code** 或 **Codex** 会话，渲染出一张一屏读完的答案卡片，每条证据都能跳回转录原文。不用再往回滚屏，也不用为 agent 已经回答过的问题再付一次 token。

<p>
<a href="https://github.com/SuperMarioYL/unbury/actions/workflows/ci.yml"><img src="https://github.com/SuperMarioYL/unbury/actions/workflows/ci.yml/badge.svg" alt="CI 状态" /></a>
<a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white" alt="Python 3.12+" /></a>
<a href="./LICENSE"><img src="https://img.shields.io/badge/license-MIT-3fb950" alt="MIT 许可证" /></a>
<img src="https://img.shields.io/badge/zero_config-no_API_key-2ea043" alt="零配置，无需 API key" />
<img src="https://img.shields.io/badge/lint-ruff-261230" alt="ruff 代码检查" />
</p>

</div>

## <img src="assets/icons/player-play.svg" width="22" alt="" /> 演示 — 22 秒讲完整个产品

<p align="center">
<img src="assets/demo-unbury-card.gif" width="880" alt="终端录制：先是一整屏原始会话 JSONL 快速滚过，然后 unbury 打印出一张一屏的答案卡片——逐字结论加上带行号引用的证据行——最后写出带跳转链接的 HTML 视图" />
</p>

这是真实录制，不是示意图：录制脚本驱动的是真实的 `unbury` 命令，跑在一个真实项目里已经结束的 Claude Code 会话上——53 轮对话、426 KB 的 JSONL。录制命令与事实记录在 [`docs/demo-results.json`](docs/demo-results.json)，渲染 GIF 的脚本是 [`docs/demo.tape`](docs/demo.tape)。

按顺序看到的内容：

1. `unbury list` — 这个目录下已结束的会话，两种 agent 一起列出。
2. 会话在磁盘上的原貌——答案就在这一堆 JSON 里，只是不知道在哪一行。
3. `unbury --session 82ed5a79` — 一条命令、一屏：逐字引用的结论，加上证据行（改了哪些文件、跑了哪些命令、做了哪些判断），每行末尾的 `:行号` 就是它在 JSONL 里的位置。
4. `unbury --html` — 同一张卡片，外加 `unbury-answer.html`：完整转录、每一轮都有稳定锚点、卡片上每一行都深链到它对应的那一轮。点一行，落到那一行。

## <img src="assets/icons/file-search.svg" width="22" alt="" /> 为什么需要它

跑完的编码 agent 会话是一种很别扭的产物：活干完了、结论也在——但结论只是夹在工具调用之间的一句"没有类型"的话，整份转录是写给*模型*看的，不是写给你的。在 unbury 之前，找回结论只有两条路：在终端缓冲区里往回滚屏（几分钟的逐行辨认），或者重新问一遍 agent（为已经产出过的答案再付一次 token，而且复述还可能走样）。

unbury 在这些方案中间的位置：

| 你想要的是… | 适合用 | unbury 为什么不合适 |
| --- | --- | --- |
| 让*下一次*会话把答案放在最前面 | 提示词规则 / 输出格式类技能 | 那些是生成时的手段，改不了已经跑完的会话 |
| 压缩历史，让模型能继续 | 内置摘要（`/compact` 之类） | 服务的是模型的上下文预算：恰好丢掉人最需要的维度，也没有证据链接 |
| 交互式翻看转录 | 转录查看器 | 答案还是得你自己找 |
| 找回已结束会话的结论，而且要有据可查 | **unbury** | 一条命令，任何已结束的 Claude Code / Codex 会话，每一句都链回原文 |

两个值得明说的设计取舍：

- **逐字引用，不复述。** 结论就是 agent 最后那条实质性回答，用启发式原样提取。不调模型、不需要 API key、完全离线——也就不会有"转述走样"。
- **跳转链接是产品本体，不是点缀。** 一张说错了结论的卡片比滚屏更糟。所以每一行都带 `路径:行号`，`--html` 再把它变成一次点击。

## <img src="assets/icons/cpu.svg" width="22" alt="" /> 工作原理

单进程、四个阶段、零网络：

```
~/.claude/projects/**/*.jsonl    ~/.codex/sessions/**/*.jsonl     （agent 本来就在写的日志）
                 \                 /
              discover — 找到本目录最新一个已结束的会话
                              |
              parsers — claude · codex：各家 JSONL 方言 → 统一的 turns
                              |
              extract — 结论 + 证据 → AnswerCard
                              |
      render — 一屏卡片          htmlview — 带锚点的链接转录视图
```

核心原语是 **AnswerCard**——横跨一次已结束会话、带溯源链接的类型化结论：

```python
SessionRef { agent, path, turns }
Evidence   { kind: "file" | "command" | "decision",
             summary, ref: (path, line) }
AnswerCard { session: SessionRef,
             conclusion: str,          # 最后一条 assistant 回答，逐字
             evidence: list[Evidence] } # 有序、去重
```

解析器把各家方言归一成同一种 turns，提取与渲染因此完全不用关心会话来自哪个 agent。两个值得知道的方言细节：

- **只读已结束的会话。** Claude Code 会话在没有存活进程持有它时算结束（按 pid 判断存活）；Codex 的 rollout 文件静默满 5 分钟算结束。无论哪种，unbury 都不会去卡片化你正在跑的会话。
- **Codex 把改动藏在脚本里。** 现在的 Codex 会话里，文件修改只以 `exec` 工具调用入参里的 JS 字符串形式存在（`tools.apply_patch('…')`），没有结构化的 apply_patch 调用可读。codex 解析器会解码这些字符串字面量，把文件修改证据找回来。

## <img src="assets/icons/bolt.svg" width="22" alt="" /> 快速开始

一分钟内跑通，没有任何要配置的东西：

```bash
uv tool install git+https://github.com/SuperMarioYL/unbury   # 或者：pipx install git+https://github.com/SuperMarioYL/unbury
```

然后进入你跑 agent 的那个目录：

```bash
unbury          # 该目录最新一个已结束会话的答案卡片
unbury --html   # 同一张卡片，外加带跳转链接的 unbury-answer.html
```

没有 API key、没有配置文件、没有常驻进程——unbury 只读取 Claude Code（`~/.claude/projects/`）和 Codex（`~/.codex/sessions/`）本来就写在磁盘上的会话日志。

想改代码的话：

```bash
git clone https://github.com/SuperMarioYL/unbury && cd unbury
uv tool install .        # 或者：pip install -e .
pytest                   # 解析器/提取/视图测试，全部用合成 fixture
```

## <img src="assets/icons/terminal-2.svg" width="22" alt="" /> 用法

全部的调优面就是一条命令加三个开关：

```bash
unbury                        # 答案卡片：本目录最新一个已结束会话
unbury list                   # 本目录记录的已结束会话
unbury --session 82ed5a79     # 指定会话：id（见 list）、唯一前缀，或转录文件路径
unbury --agent claude         # 只看 claude | codex；默认两者都看
unbury --html                 # 同时写出 unbury-answer.html（带链接的转录视图）
```

`--session` 不受当前目录限制——几周前跑完的存量会话，仍然只差一个前缀的距离；在项目里跑 `unbury list` 就能看到有什么。界面到此为止；再复杂的需求应该进 issue，而不是进配置文件。

## <img src="assets/icons/robot.svg" width="22" alt="" /> 支持的 agent

| Agent | 读取位置 | 「已结束」的定义 | 说明 |
| --- | --- | --- | --- |
| Claude Code | `~/.claude/projects/<project>/<id>.jsonl` | 没有存活进程持有它 | 会话标题、工具调用、人工输入与系统注入消息的过滤 |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` | 文件静默 ≥ 5 分钟，且非子 agent 线程 | 从 `exec` 入参里的 `apply_patch` 字符串中恢复文件修改 |

新 agent 走的是同一条缝：一个解析器就是一个模块，把某种方言的 JSONL 变成 `unbury.parsers` 的统一 turns（`parse_session(path) -> ParsedSession`）。发现、提取和两套渲染器都保持 agent 无关。

## <img src="assets/icons/list-check.svg" width="22" alt="" /> 已知局限

- 提取是启发式的，不靠模型——这正是 unbury 能零配置、离线使用的原因，也是结论逐字引用而不重写的原因。
- 各家日志格式没有文档、说变就变。解析器按方言用 fixture 回归测试；解析不了的行只计数、不致命。
- 卡片展示放得下的行数，并注明还有多少行没显示；完整的证据表永远在 HTML 视图里。

## <img src="assets/icons/map.svg" width="22" alt="" /> 路线图

- **更多解析器** — Astra、Gemini CLI、Cursor——每个都是解析器接口上的一个小模块，配套一种贡献者能从自己会话录制的 fixture 格式。
- **解析器贡献指南** — 把测试套件在用的"录制 fixture"模式写下来，给新 agent 用。
- **明确不做：** LLM 摘要。零配置——无 key、离线、逐字——就是产品本身。

## <img src="assets/icons/scale.svg" width="22" alt="" /> 许可证

[MIT](./LICENSE) © 2026 SuperMarioYL。分节图标来自 [Tabler Icons](https://tabler.io/icons)（MIT）。

<p align="center"><sub><a href="./LICENSE">MIT</a> © 2026 SuperMarioYL</sub></p>
