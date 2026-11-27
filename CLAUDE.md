# CLAUDE.md

给 Claude Code 等 agent 的入口文件。完整项目说明见 [AGENTS.md](AGENTS.md)；
下面第 1 节「分支与工作树规则」与 AGENTS.md 逐字一致——改一处必须改两处，冲突时以 AGENTS.md 为准。

本仓库的 agent 工作守则，一句话记牢：**改文件先开工作树，分支上随便提交，只有用户说了才合并进 main，
一版快进、多版留最终合并提交。**

## 1. 分支与工作树规则（硬性）

### 1.0 先确认自己在哪

```bash
git rev-parse --show-toplevel     # 当前工作树路径
git rev-parse --abbrev-ref HEAD   # 当前分支
git worktree list                 # 所有工作树，第一行是主检出
```

- **主检出**：`git worktree list` 的第一行（当前是 `D:\Projects\terminal-music-box`），只签出
  `main`。它是发布线，**不是工作区**：不在里面改文件、不提交、不切分支、不 rebase、不 reset。
- **工作树**：别处签出特性分支的独立目录（`.agents/worktrees/…`、`.codebuddy/worktrees/…`、
  `.qoder/worktrees/…`、`~/.zcode/worktrees/…` 等），一个工作树只对应一个分支。

仓库里已经躺着很多别的 agent / 工具留下的工作树和分支。它们不属于你：
**不清理、不合并、不复用**，除非用户明确把它指给你。这些目录都已被 `.gitignore` 排除，
不会出现在 `git status` 里，也不需要你收拾。

### 1.1 要改文件 → 先有工作树

| 你现在的情况 | 该怎么做 |
| --- | --- |
| 已经在非 main 的工作树里 | 直接改、直接提交，**不要新建**工作树 |
| 在主检出里，且要改文件 | 新建工作树 + 分支（哪怕只改一行文档） |
| 只是只读排查（读代码、跑测试、看日志） | 不需要工作树，但不许改文件 |

新建工作树（在主检出根目录执行，分支一律从 main 起步）：

```bash
git worktree add ../tmb-<slug> -b <type>/<slug> main
```

- `<type>` 用 `feat` / `fix` / `chore` / `docs` / `refactor` / `perf` / `test`，`<slug>` 用英文小写短横线。
- 工具自带工作树机制时，**用它生成的路径和分支名**，不要重复建。自动生成的名字
  （`dsh-<uuid>`、`worktree-<slug>` 之类）既然已经存在，就沿用，不要为了好看改名或重建。
- 工作树放在仓库内部时（`.agents/`、`.codebuddy/`、`.qoder/`），这些目录已被忽略，不会污染提交。
- 分支从**本地 main** 起步。本仓库的本地 main 可能领先 `origin/main`，以本地为准，别从
  `origin/main` 拉一个落后的分支。
- **一个分支只做一件事**。中途发现无关的问题，另开工作树，不要夹带。
- 默认不从别的特性分支切分支。确实依赖某个未合并的改动时，在收尾汇报里写明依赖关系，
  合并时先合被依赖的那个。

### 1.2 分支上随时提交

- 非 main 分支上的 `git add` / `git commit` 随时可以做，**不需要授权**。做完一段就提交，
  不要攒一大坨未提交的改动，也不要让工作树晾在那儿。
- 每次提交都应该是能跑的状态：至少跑相关的测试模块；合并前必须整套通过。
- 提交前 `git status` 看一眼，按文件逐个 add，别用 `git add .` 盲加；`*.wav`、`*.log`、
  `external_songs/`、`__pycache__/`、草稿文件都不该进库。
- **不推送 main**。推送自己的特性分支前先问一声——本仓库远端目前只有 main，别擅自公开分支。

### 1.3 只有用户说明才合并进 main

**触发条件**：用户明确说了「合并进 main」「合了吧」「merge it」这类话。
以下情况都**不算**授权：

- 测试全绿、功能完成、代码自己觉得漂亮；
- 另一个 agent 或另一个分支说「我这边好了」；
- 用户在讨论里提过「以后要合」；
- 分支放久了想清理。

**没有明确指令 = 不合并。** 收尾时把分支名和工作树路径报给用户，等指令。

**合并前的检查**（在分支工作树里）：

1. 整套测试通过：`python -m unittest discover -s tests`。
2. 看一眼 main 有没有走远：`git log --oneline main..HEAD`，必要时 `git fetch origin`。
3. 读一遍要合进去的东西：`git log --graph --oneline main..HEAD`、`git diff main...HEAD --stat`；
   确认不是「修了一半」的分支，也没有夹带无关改动。
4. 判断这次改动是**一版**还是**多版**。

**判断「一版 / 多版」**——看这个改动最后留下了几套实现，而不是数提交个数：

- **一版**：`main..HEAD` 是一条直线（最多加一个「把 main 合进来」的同步合并），从头到尾只写了
  一套实现。
- **多版**：合并过其他特性分支（`git log --merges --format='%s' main..HEAD` 里出现
  `Merge branch 'feat/…'`），或者同一件事试过几套做法、最后收敛成一套。

**合并动作**（在主检出执行；主检出路径以 `git worktree list` 第一行为准，当前是
`D:/Projects/terminal-music-box`）：

```bash
git -C "D:/Projects/terminal-music-box" status --short --branch    # 必须是干净的 ## main
```

不是干净的 `## main` 就停手：不要 stash、不要 reset、不要替用户提交，把现场情况报给用户。

- **一版 → 只允许快进**：

```bash
git -C "D:/Projects/terminal-music-box" merge --ff-only <branch>
```

  快进失败说明 main 已经前进，**不要**改成 `--no-ff` 硬合。回到分支上同步 main，再重试快进。

- **多版 → 禁止快进，生成一个「最终版」合并提交**：

```bash
git -C "D:/Projects/terminal-music-box" merge --no-ff <branch> -m "Merge branch '<branch>' (final)" -m "Keeps <adopted version>; drops <the other versions> because <reason>."
```

  合并提交的正文要写清楚**最终采用哪一版、放弃了什么、为什么**，让以后查得出来。
  提交信息用英文，和仓库既有风格一致。

**main 前进后的同步**（在分支工作树里，不在 main 上）：

```bash
git merge main
```

- 默认做法是把 main 合进自己的分支，冲突在分支上解决；绝不在 main 上解冲突、也绝不把冲突标记
  提交进去。
- 只有在该分支**从未推送过**、且希望保住快进时，才可以用 `git rebase main`；改写过的历史不要
  推给别人。
- 把 main 合进分支**不会**让这次改动变成「多版」，判断依据始终是「有几套实现」。

**一次要合多个分支时**（用户点名合 A 和 B）：先在各自分支上把冲突处理干净、测试跑通，再按
顺序一个个合进 main，每次合并后 main 都要能过测试；不要手动把两版拼成一个大 diff。

**合并后**（在主检出）：

1. 再跑整套测试；
2. `git log --oneline -5`、`git show --stat HEAD` 看合并结果；
3. 复核 diff，确认没有把 main 上更晚的修复改回旧版本——陈旧分支翻车基本都是这么翻的；
4. **不要**顺手 `git push`、不要删分支、不要删工作树。推送和清理都要用户再点一次头。

### 1.4 禁区

- 在 main 上直接提交（哪怕「只是一个 typo」）。
- `git push --force`；对 main 做 `rebase` / `reset --hard` / `branch -D`。
- 没读完 diff 就把分支合进 main，或合并没测过的分支。
- 删除、重建、清理别人的分支或工作树（`git worktree remove`、`git worktree prune`、`git branch -D`）。
- 在特性分支之间互相当同步手段乱合并；把两个 agent 的改动揉进一个提交或一个工作树。
- 在别人的工作树里替别人改文件、提交。
- 把 `external_songs/`、`*.wav`、`*.log`、`*.scratch*`、`*-issue.txt`、`.venv/`、`__pycache__/`
  带进提交。

### 1.5 常见情形照这个办

| 情形 | 做法 |
| --- | --- |
| 要改代码或文档 | 先确认在工作树里，没有就新建分支 |
| 已经在工作树里 | 直接改、提交，不新建 |
| 想「就改一行」直接动 main | 不行，开工作树 |
| 测试挂了 | 在分支上修；修不好就停手汇报，不合并 |
| main 有了新提交 | 在分支上 `git merge main`，解决冲突、重跑测试 |
| 用户说「合吧」 | 走 §1.3：判一版/多版 → 快进或 `--no-ff` |
| 用户说「推上去」 | 先跑测试，再 `git push`；只说 main 就只推 main |
| 想删旧分支 / 旧工作树 | 先问用户 |
| 拿不准该不该合 | 不合，问用户 |

### 1.6 收尾汇报

干完活按这个格式说清楚，别让用户猜：

```
分支：feat/canon-lock
工作树：D:\Projects\terminal-music-box\.agents\worktrees\canon-lock
改动：tmb/songs.py, tests/test_songs.py
测试：python -m unittest discover -s tests → 534 tests OK（约 53s，3 skipped）
合并：未合并，等指令
```

---

## 2. 项目速览

- **终端音乐盒**：零依赖、跨平台的终端乐器 + 音游，纯 Python 3.10+ 标准库，主要面向树莓派，
  日常在 Windows 上开发和调试。
- 三个玩法：自由演奏（三个八度 + 13 种程序化合成音色）、胎教模式（自动播放，按键续命）、
  音游模式（内置 4 首曲目 + 外部 `.tmbp` 音乐包）。
- 两条硬前提：**只用标准库**（不需要 `pip install`）、**音频运行时合成**（不附带任何采样文件）。

## 3. 常用命令

```bash
python main.py                              # 启动（等价：python -m tmb）
python main.py --demo                       # 无头演示，不需要交互终端
python main.py --wav out.wav                # 渲染音频到 WAV
python -m unittest discover -s tests -v     # 整套测试（约 1 分钟）
python -m unittest tests.test_charts -v     # 单个模块
```

代码约定、谱面规则、测试写法与目录结构见 AGENTS.md 第 2–4 节。

## 4. 收尾自检

1. 改的是工作树，不是主检出；
2. 所有改动都提交在自己的分支上，`git status` 干净，没有夹带无关文件；
3. 相关测试或整套测试通过；
4. 没动别人的分支、工作树，没删东西；
5. 汇报了分支名、工作树路径、测试结果、合并状态（默认未合并）。
