# AGENTS.md

本仓库的 agent 工作守则。在这里干活的 agent 和人（DSH、Claude Code、Codex、CodeBuddy、
Qoder……）都按这份文件来。

三条核心，先看这三条，其余都是展开：

1. **要改文件，先有工作树**（已经建好的工作树直接复用，不再新建）。
2. **非 main 分支上可以随时提交**，不用等谁批准。
3. **只有用户明确说明才合并进 main**；合并时按「一版快进、多版留最终合并提交」处理。

优先级：用户当轮的明确指令 > 本文件 > 个人习惯或工具的默认行为。
本文件自身的修改也要走同样流程：工作树 → 分支 → 提交 → 等用户合并。

---

## 0. 项目速览

- **终端音乐盒**：零依赖、跨平台的终端乐器 + 音游，纯 Python 3.10+ 标准库，主要面向树莓派，
  日常在 Windows 上开发和调试。
- 三个玩法：自由演奏（三个八度 + 13 种程序化合成音色）、胎教模式（自动播放，按键续命）、
  音游模式（内置 4 首曲目 + 外部 `.tmbp` 音乐包）。
- 两条硬前提：**只用标准库**（不需要 `pip install`）、**音频运行时合成**（不附带任何采样文件）。

---

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

## 2. 项目约定

### 2.1 依赖与体积

- **只用标准库**。新增第三方依赖会毁掉「零依赖、树莓派直接跑」这个前提，除非用户明确同意。
  需要什么能力先在标准库里找。
- 不引入采样音频、字体、二进制资源；音频一律运行时合成。
- 仓库保持轻量：谱面源文件进库（`packs/`），音频和 `.tmbp` 不进库。

### 2.2 代码

- **UI 文案走 `tmb/theme.py`**：screen 里一律 `theme.t("key")`，新增 key 必须同时补 `ZH` 和英文
  两张表（对应 Unicode / ASCII 两种模式），不要在任何 screen 里硬编码中文或英文句子。
- **渲染**：`tmb/ansi.py` 是差量渲染 + 宽字符处理（CJK 占两列）。动到字符宽度、光标定位时，
  两种模式都要看。
- **输入**：POSIX（`term_posix.py`）和 Windows（`term_win.py`）是两条独立后端。改键盘、鼠标、
  备用屏、kitty 协议相关逻辑时两边都要考虑，别只测自己脚下的平台。
- **性能**：目标设备是树莓派。别把重活放进每帧渲染或音频线程；预加载、缓存、池化是既有设计，
  改动前先看 `tmb/audio/engine.py`。
- **曲目与谱面**：内置曲目数据在 `tmb/songs.py`（很大，尽量用工具生成/修改），双手轨道规划规则
  在 `tmb/charts.py`。不要手改坐标绕过规则去「凑」一个能过的谱面，改规则要连带跑
  `tests/test_charts.py`、`tests/test_rhythm_game.py`。
- 代码注释和 docstring 用英文，UI 文案中英双语。
- 文件编码 UTF-8。不要整文件重写换行符，否则 diff 糊成一片没法评审。

### 2.3 测试

- **全部无头**：用 `tests/helpers.py` 的 `HeadlessCase`（注入事件、`app.step(dt)`、
  `find_label` / `click_label`），音频用 `NullBackend`。不开真终端、不要声卡、不用 `sleep`
  等真实时间（用 `advance()`）。
- 新增行为要带测试；修 bug 先写一个能复现的测试。
- 整套：`python -m unittest discover -s tests -v`，约 1 分钟（534 个用例，平台相关用例会跳过）。
- 单模块：`python -m unittest tests.test_charts -v`。
- 提交或合并前：整套必须通过。

### 2.4 文档

- `README.md`（中文）与 `README.en.md`（英文）必须同步修改，行为变了就更新对应段落。
- 规则只有一份源文件：就是本文件。`CLAUDE.md` 里只有一行 `@AGENTS.md`（Claude Code 的导入
  语法），**不要往里面抄内容**，免得两份漂移；改规则只改 `AGENTS.md`。

### 2.5 数据与素材

- `packs/`：谱面源文件（`chart.json` + `manifest.json`），不含音频，可以进库。
- `external_songs/`：音乐包实际加载目录，已被 `.gitignore` 排除（外部音频常有版权问题）。
- `tools/`：`make_pack.py` 打包、`chart_canon_style.py` 自动作谱、`chart_studio.html` /
  `align_studio.html` 是零依赖单文件网页工具，直接用浏览器打开。

---

## 3. 常用命令

```bash
python main.py                     # 启动（等价：python -m tmb）
python main.py --mode ascii        # ASCII 模式
python main.py --demo              # 无头脚本演示，不需要交互终端
python main.py --wav out.wav       # 渲染音频到 WAV（不发声）
python main.py --audio null        # 静音后端
python main.py --audio alsa        # 指定后端：auto|alsa|pulse|winmm|null|wav
python main.py --no-kitty          # 跳过 kitty 键盘协议协商（测试用）

python -m unittest discover -s tests -v        # 整套测试
python -m unittest tests.test_charts -v        # 单个模块

python tools/make_pack.py --src packs/<song> --audio <audiofile>
python tools/chart_canon_style.py --audio <audiofile> --id <id> \
    --title-zh <中文名> --title-en <英文名> --out-dir packs/<id>
```

设置保存在 Linux `~/.config/terminal-music-box/config.json`、
Windows `%APPDATA%\terminal-music-box\config.json`。

---

## 4. 目录结构

```
main.py              启动入口
tmb/
  __main__.py        CLI 参数
  app.py             状态机 + 主循环
  screens/           各个界面：主菜单、自由演奏、音游、选歌
  events.py          归一化的按键/鼠标/缩放事件
  ansi.py            屏幕缓冲 + 差量渲染（宽字符）
  terminal.py        平台门面（备用屏、鼠标、生命周期）
  term_posix.py      POSIX 原始模式 + ANSI 输入解析
  term_win.py        Windows 控制台 INPUT_RECORD 后端
  ui.py              即时模式控件 + 鼠标命中检测
  theme.py           Unicode/ASCII 主题 + 中英文字符串表
  config.py          设置持久化
  testing.py         无头测试终端
  audio/backends.py  alsa / pulse / winmm / wav / null
  audio/engine.py    多声部混音线程 + 声部管理
  audio/synth.py     Minecraft 音符盒音色合成
  songs.py           旋律、谱面、可暂停的歌曲播放器
  charts.py          双手轨道规划规则
  external.py        外部音乐包（.tmbp）
tests/               unittest，无头驱动
tools/               打包、自动作谱、网页作谱工具
packs/               谱面源文件
```

---

## 5. 收尾自检

1. 改的是工作树，不是主检出；
2. 所有改动都提交在自己的分支上，`git status` 干净，没有夹带无关文件；
3. 相关测试或整套测试通过；
4. 没动别人的分支、工作树，没删东西；
5. 汇报了分支名、工作树路径、测试结果、合并状态（默认未合并）。
