# 终端音乐盒 (Terminal Music Box)

**中文** | [English](README.en.md)

零依赖、跨平台的终端乐器 + 音游,纯 Python 3 标准库编写。在任何 ANSI 终端中运行,
支持**全键盘与鼠标**操作,主要面向**树莓派**设计。

实现 [issue #1 — 软件侧开发计划](https://github.com/MainRedstoner/terminal-music-box/issues/1)。

## 功能特性

- **两种界面模式**,主菜单中随时切换:
  - **Unicode 模式** — 中文界面,圆角按钮(`╭─╮ │ ╰─╯`)。
  - **ASCII 模式** — 全英文,朴素按钮(`+-|`),兼容性优先。
- **自由演奏** — 字母键弹奏三个八度,内置 Minecraft 1.20 音符盒全部 **13 种旋律音色**
  (剔除打击乐),全部运行时程序化合成,不附带任何采样文件。
- **胎教模式** — 自动播放轻柔旋律;只有在 2 秒内按下任意演奏键,音乐才继续,
  否则暂停。开启后演奏键静音,只保留自动播放的声音,选歌按钮也随之出现。
- **音游模式** — 竖直下落的音符、判定线、完美/良好/失败判定与特效、
  实时分数与连击、延迟校正、可自定义键位。
- **音频** — 实时多声部混音器:Linux 下流式输出到 ALSA(`aplay`)或
  PulseAudio/PipeWire(`pacat`/`paplay`),Windows 下使用 `winmm`,另提供 WAV/null
  后端用于无头测试。音色在启动与切换时后台预加载,首次弹奏不卡顿;
  多音齐奏时混音器自动让位(峰值保持 + 慢释放),不再削波爆音。

## 环境要求

- Python **3.10+**(仅标准库,**无需 `pip install`**)。
- Linux/树莓派:安装 `aplay`(alsa-utils)或 `paplay`(pulseaudio-utils)之一即可出声。
- Windows:使用系统自带 `winmm` API,无需额外软件。
- 支持 ANSI + 256 色的终端(Linux 控制台、SSH、Windows Terminal 等现代终端均可)。
  鼠标使用 SGR 扩展跟踪协议。

## 运行

```bash
python main.py            # 或:python -m tmb
python main.py --mode ascii        # 以 ASCII 模式启动
python main.py --audio alsa        # 强制指定后端:alsa|pulse|winmm|null|wav
python main.py --wav out.wav       # 不发声,把音频渲染到 WAV 文件
python main.py --demo              # 无头脚本演示(不需要交互终端)
```

设置(界面模式、音色、音游键位、延迟偏移、胎教曲目、声音设置)自动保存到:
Linux `~/.config/terminal-music-box/config.json`,
Windows `%APPDATA%/terminal-music-box/config.json`。

## 操作说明

### 主菜单
`↑/↓` 选择 · `Enter` 确认 · 鼠标点击 · 数字键 `1–4` 快捷选择。
`^Q`/`^D`/`^C`/`Esc` 退出。

### 自由演奏
三个 C 大调八度(每行 7 个自然音):

```
Q W E R T Y U   —— 高音 (C5..B5)
A S D F G H J   —— 中音 (C4..B4)
Z X C V B N M   —— 低音 (C3..B3)
```

- `^X` — 循环切换音色(竖琴、贝斯、长笛、钟声、吉他、风铃、木琴、铁木琴、
  牛铃、迪吉里杜管、比特、班卓琴、电钢琴)。
- **长按持续**:支持 Kitty 键盘协议的终端(或 Windows 终端)中,长笛、
  比特、迪吉里杜管等持续音色按住琴键即持续发声,松开即止;不支持时仍为
  固定音长,且长按不会重复触发。WSL(ConPTY)在备用屏下不派发释放事件,
  此时程序自动放弃备用屏以换取完整的按键释放。
- **音量/音长**:键盘下方的调节条,`↑/↓` 切换音量/音长,`←/→` 调整
  当前音色的值(音量 0–2.0,音长 0.25–4×;余音类音色只能裁剪),即时生效,
  比特默认音长 0.25×。
- `^T` — 胎教模式开关。
- `^A` — 选择胎教曲目。
- `^Q`/`^D`/`^C`/`Esc` — 返回主菜单。
- 鼠标可直接点击屏幕上的琴键与按钮。

### 胎教模式
开启后自动播放摇篮曲,演奏键转为"静音伴奏":按键仍会亮起并维持播放,
但不再发声,只剩自动播放的旋律。**2 秒内**按下**任意**演奏键即可让音乐继续,
否则暂停;再次按键即恢复。**选歌按钮**仅在胎教开启后显示;也可随时按
`^A` 选歌,未选择时默认列表第一首(小星星)。曲目播完自动循环。

### 音游模式
- 曲目旋律全程自动播放,音符恰好落至判定线时发声;打击只判定,不发声。
- 卡农的音色锁定为迪吉里杜管,土耳其进行曲锁定为电钢琴,不随自由演奏的音色切换而变化。
- 土耳其进行曲为完整版(A—B—A′—C—D—E—C—A—B—A′—过渡—尾声),谱面跟随右手主题;
  音符密集的段落只使用中间四条轨道,避免外圈两条轨道。
- 默认键位:`A S D J K L`(6 轨道),可在**键位设置**中重新绑定(重复按键自动交换)。
- 卡农谱面为手工编排:密集乐句走中间四轨(`S D J K`),手法型每重复两次轮换,避免长段落变成单一循环;稀疏音符按音区铺满六轨,乐句重音处双押。
- **延迟校正**:跟随节拍器按键采样,取中位数作为输入延迟偏移。
- 游玩中仅 `Esc` 可暂停;暂停菜单可退出或继续,**继续时先倒数 3 秒**。
- 判定:**完美**(±50 ms)、**良好**(±120 ms),其余为**失败**。
- 实时显示分数、连击、最大连击、完美/良好/失败计数与准确率,结算页给出评级。

## 内置曲目

全部为公有领域旋律,共 10 首。胎教模式可使用全部曲目;音游模式提供完整版《卡农》
(下落谱面跟随小提琴 I)、《G 大调小步舞曲》(保留 AABB 反复,右手旋律附带重音双押)
与《土耳其进行曲》(右手主题,A—B—A—C—A 迴旋):

| 曲目 | 英文 |
| --- | --- |
| 小星星 | Twinkle Twinkle |
| 玛丽有只小羊羔 | Mary Had a Little Lamb |
| 欢乐颂 | Ode to Joy |
| 铃儿响叮当 | Jingle Bells |
| 祝你生日快乐 | Happy Birthday |
| 卡农 | Canon in C |
| G 大调小步舞曲 | Minuet in G |
| 土耳其进行曲 | Turkish March |
| 摇篮曲 | Brahms' Lullaby |
| 伦敦桥 | London Bridge |

《卡农》依据 [Mutopia-2015/09/02-2047](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=2047)
的三小提琴与低音完整乐谱移调至 C,排版者 Michael Fischer v. Mollard,依据
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 使用。

《G 大调小步舞曲》(BWV Anh. 114,Christian Petzold)依据
[Mutopia-2017/01/19-75](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=75)
的公有领域双谱表乐谱,保留两段反复与装饰音。

《土耳其进行曲》依据 [Mutopia-2015/08/13-108](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=108)
的《Rondo alla Turca》完整收录(不反复),排版者 Rune Zedeler 与 Chris Sawer,公有领域;
自动播放保留双手钢琴织体,谱面取右手旋律并略去短于十六分音符的装饰音。

## 架构

```
tmb/
  events.py        归一化的按键/鼠标/缩放事件
  ansi.py          屏幕缓冲 + 差量渲染(支持宽字符)
  terminal.py      平台门面(备用屏、鼠标、生命周期)
  term_posix.py    termios 原始模式 + ANSI/SGR 输入解析(Linux/macOS)
  term_win.py      Windows 控制台 INPUT_RECORD 后端(含按键抬起 + 鼠标)
  ui.py            即时模式控件 + 鼠标命中检测
  theme.py         Unicode/ASCII 主题 + 中英文字符串表
  config.py        持久化设置
  app.py           状态机 + 主循环
  testing.py       无头测试终端
  audio/
    backends.py    alsa / pulse / winmm / wav / null 输出
    engine.py      多声部混音线程 + 声部管理
    synth.py       Minecraft 音符盒音色程序化合成
  songs.py         旋律、谱面、可暂停的歌曲播放器
  screens/         main_menu、freeplay、rhythm、rhythm_game、song_select
```

### 跨平台输入
- **POSIX**:`termios` 原始模式、增量 UTF-8 解码、转义序列解析;
  单独 `Esc` 用短超时区分;`SIGWINCH` 处理窗口缩放。
- **Windows**:`ReadConsoleInputW` 直接提供按键**按下与抬起**及原生鼠标事件;
  输出启用 VT 处理,与 POSIX 共用同一套 ANSI 渲染器。
- POSIX 终端拿不到按键抬起事件,自动重复的按键事件用短超时去抖,不会连发音符。

## 测试

```bash
python -m unittest discover -s tests -v
```

测试套件无头驱动整个应用(注入事件、捕获文本帧),并通过渲染 WAV 验证
混音器与合成器——不需要交互终端,也不需要声卡。

## 树莓派部署提示

- 安装:`sudo apt install python3 alsa-utils`(或 `pulseaudio-utils`)。
- 直接 `python3 main.py` 即可;SSH 会话中同样可用(鼠标需终端支持 SGR)。
- 无声时检查 `aplay -l` 是否有输出设备;PipeWire 桌面环境下 `aplay`/`paplay` 均可。

## 许可说明

内置旋律均为公有领域作品。音频在运行时合成,不附带、不再分发任何 Minecraft 素材。