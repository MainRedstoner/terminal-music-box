# AGENTS.md

## 分支与工作树（硬性）

**改文件先有工作树。** 已经在非 main 的工作树里就直接用，不新建；只读排查不用建。
新建时从本地 main 起步（本仓库 main 可能领先 origin/main）：
`git worktree add ../tmb-<slug> -b <type>/<slug> main`。
工具自动生成的工作树和分支名沿用，不改名、不重建。主检出只签出 main，不在里面改文件或提交。

**非 main 分支上随时提交**，不用授权。不推 main，推自己的分支也先问一声。

**只有用户明确说了才合并进 main**（「合了吧」「merge it」）。测试全绿、功能完成、别的 agent
说好了，都不算授权。合并前跑 `python -m unittest discover -s tests`，并确认主检出
（`git worktree list` 第一行）是干净的 `## main`。合并动作在主检出执行：

- **一版**（`main..HEAD` 一条直线，只有一套实现）→
  `git -C "D:/Projects/terminal-music-box" merge --ff-only <branch>`。
  快进失败说明 main 前进过：回分支上 `git merge main` 解决后再试，**不许**改用 `--no-ff` 硬合。
- **多版**（合并过别的特性分支，或同一件事试过几套做法）→ 不许快进，用
  `git -C "D:/Projects/terminal-music-box" merge --no-ff <branch> -m "Merge branch '<branch>' (final)" -m "最终采用哪版、放弃什么、为什么"`。

合并后重跑测试；不顺手 push，不删分支和工作树。别人的分支、工作树一概不动。

## 项目约定

- 零依赖：只用 Python 3.10+ 标准库，不加第三方包，不引入采样音频。
- 运行 `python main.py`（无头演示 `--demo`）；测试 `python -m unittest discover -s tests`，约 1 分钟。
- 界面文案一律走 `tmb/theme.py` 的 `theme.t("key")`，新 key 中文（ZH）和英文两张表都要补。
- 测试全部无头：用 `tests/helpers.py` 的 `HeadlessCase`，不开真终端、不要声卡、不 sleep。
- 改输入（按键/鼠标/备用屏）时，POSIX 和 Windows 两套后端都要考虑。
- 曲目数据在 `tmb/songs.py`，双手轨道规则在 `tmb/charts.py`，谱面别手改坐标绕规则。
- 改了行为就同步 `README.md` 与 `README.en.md`。
- `CLAUDE.md` 只有一行 `@AGENTS.md`，规则只维护这一份。
