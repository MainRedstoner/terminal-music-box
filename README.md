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
  实时分数与连击、延迟校正、可自定义键位。曲目列表按 **内置音乐 / 外部音乐**
  分组展示；外部音乐包（谱面 + 音频打包成一个 `.tmbp` 文件）放入
  `external_songs/` 目录即可加载游玩。
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
python main.py --no-kitty          # 测试用:禁用 Kitty 键盘协议
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
卡农、小步舞曲、土耳其进行曲与致爱丽丝会奏出自由演奏键盘之外的音高,首次开启
(以及切歌、切换音色后)会先显示"加载中"预渲染这些音,完成后自动开始;之后再播即为即开。

### 音游模式
- 曲目旋律全程自动播放,音符恰好落至判定线时发声;打击只判定,不发声。
- 卡农的音色锁定为迪吉里杜管,《G 大调小步舞曲》《土耳其进行曲》与《致爱丽丝》锁定为电钢琴,不随自由演奏的音色切换而变化。
- 土耳其进行曲为完整版(A—B—A′—C—D—E—C—A—B—A′—过渡—尾声),谱面只打右手主题的
  **八分音符骨架**(十六分音符的跑动仍由自动播放奏出,但不作为打击点);
  密集段只使用中间四条轨道,同一只手连续超过六个音符时跨到另一只手;
  每两小节的强拍与结尾处加入双押。
- 默认键位:`A S D J K L`(6 轨道),可在**键位设置**中重新绑定(重复按键自动交换)。
- 卡农谱面为手工编排:密集乐句走中间四轨(`S D J K`),手法型每重复两次轮换,避免长段落变成单一循环;稀疏音符按音区铺满六轨,乐句重音处双押。
- 四首音游曲目共用同一套键位规划规则(`tmb/charts.py`):先按**音符数量**把音高
  切成六个连续带,保证同一音高永远落在同一轨道;八分音符及更快的音符只落在中间
  四轨,外侧两轨只承接稀疏长音;相邻同轨会被移开,超长单手流会跨到另一只手;
  重音双押取镜像(`A↔L`、`S↔K`、`D↔J`),两只手做同一个形状。
- **延迟校正**:跟随节拍器按键采样,取中位数作为输入延迟偏移。
- 游玩中仅 `Esc` 可暂停;暂停菜单可退出或继续,**继续时先倒数 3 秒**。
- 判定:**完美**(±50 ms)、**良好**(±120 ms),其余为**失败**。
- 实时显示分数、连击、最大连击、完美/良好/失败计数与准确率,结算页给出评级。

## 内置曲目

全部为公有领域旋律,共 11 首。胎教模式可使用全部曲目;音游模式提供完整版《卡农》
(下落谱面跟随小提琴 I)、《G 大调小步舞曲》(保留 AABB 反复,右手旋律按音符数量分带,
重音处镜像双押)、《土耳其进行曲》(右手主题,A—B—A—C—A 迴旋,打击点取八分音符骨架)
与《致爱丽丝》(右手最高声部,密集段走中间四轨,和弦与强拍处镜像双押):

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
| 致爱丽丝 | Für Elise |
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
自动播放保留双手钢琴织体与十六分音符跑动,打击点只取右手旋律的八分音符骨架,
并略去短于十六分音符的装饰音。

《致爱丽丝》依据 [Mutopia-2015/08/18-931](https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=931)
的 WoO 59 完整钢琴谱(Breitkopf & Härtel,1888),展开两组印刷反复;排版者
Stelios Samelis 已将该版本贡献至公有领域。音游谱面以右手最高声部为主音,微时值装饰音仅保留在自动播放中;八分音符及更快的音符走中间四轨,外侧两轨只承接稀疏长音,同一轨道不会连续出现三个音符;和弦与每四小节的第一拍加入镜像双押;右手高音段连续六个快速音符后会借一个音给左手,避免两根手指在六连音上连打。

## 外部音乐包

音游模式可以加载自制谱面:谱面与音频打包成**一个 `.tmbp` 文件**(zip 容器,
内含 `manifest.json`、`chart.json` 与压缩音频),放入仓库根目录的
`external_songs/` 后,音游曲目列表的"外部音乐"分组即会出现对应条目。
该目录已被 `.gitignore` 排除——外部音频往往是受版权保护的素材,不应进入版本库。

- **播放**:进入曲目时用 ffmpeg 把包内音频解码为 44.1 kHz 单声道 PCM
  (约 4 分钟歌曲 ≈ 20 MB 内存),经由现有混音器作为一条长音轨播放;
  暂停/继续精确衔接,慢设备上音画漂移超过 80 ms 时自动对齐。纯 PCM WAV
  打包的音乐包无需 ffmpeg 即可播放。
- **打包**:`tools/make_pack.py` 在打包时用 ffmpeg 把音频压缩为单声道
  Opus 96 kbps(无 libopus 时回退内置 AAC),2.9 MB 的示例包对应
  6.3 MB 原始音频,压缩也显著降低了树莓派上的解码内存占用。

  ```bash
  python tools/make_pack.py --src packs/my_song --audio audio.m4s
  ```

- **作谱**:`tools/chart_canon_style.py` 从旋律频段(250-1200 Hz,人声+钢琴)
  做起始检测——鼓组与贝斯被排除在外,音符跟随的是"调子"而非鼓点;音符
  保持在检测到的演奏时间上(现场演奏有弹性速度,不做全局网格量化),轨道
  规划使用与内置谱面相同的双手工具箱 `tmb/charts.py`:按音符数切音区、
  密集乐句轮换中间四轨(`S D J K`)、同一轨道不连击、单手长串自动换手、
  乐句重音镜像双押(A-L / S-K / D-J):

  ```bash
  python tools/chart_canon_style.py --audio audio.m4s \
      --id i_never_forgot --title-zh 我不曾忘记 --title-en "To the Traveler" \
      --out-dir packs/i_never_forgot
  python tools/make_pack.py --src packs/i_never_forgot --audio audio.m4s
  ```

`packs/` 目录存放谱面源文件(`chart.json` + `manifest.json`,不含音频),
便于在版本库中保存与迭代谱面;构建 `.tmbp` 时再把音频合并进去。

### 手动作谱台

不想依赖自动分析时,用 **`tools/chart_studio.html`** 手工作谱:零依赖单文件
网页工具,浏览器直接打开即可(建议 Chrome/Edge)。音频经 WebAudio 在浏览器
音频线程播放,页面卡顿不影响走带。界面是「画布 + 右侧曲目/选中音符侧栏 +
底部走带」:整曲概览条可点击/拖动定位,节拍、波形、各轨道音符分布与 BPM
同屏可见。

- **载入**——顶栏选文件,或把音频直接拖进窗口;没有素材时点「示范音」会合成
  一段 60 秒、120 BPM 的示范音乐,先熟悉流程。
- **延迟校准**——内置 16 响节拍器取按键中位数,一次性补偿「音频输出延迟 +
  反应延迟」;降速作谱时反应分量按速率缩放。暂停时放的音符直接落在播放头,
  不再扣反应延迟。
- **演奏模式**——与游戏一致的 `A S D J K L` 六轨,边听边按键放音符,
  `空格` 随时暂停/继续,支持 0.25×–1× 变速、节拍器、提示音与吸附。
- **编辑模式**(`Tab`)——钢琴卷帘 + 波形 + 小节/拍网格:点选、拖动改时间与
  轨道、`↑/↓` 换轨、`←/→` ±10 ms(Shift ±50 ms)、`Del` 删除、
  `Ctrl+Z` / `Ctrl+Shift+Z` 撤销重做、`Ctrl+滚轮` 缩放。双押 = 选中后按
  `L` 点另一个音符,两音符对齐同一时刻并联动编辑(`U` 解除)。
- **曲目卡片**——填写曲目信息、调整 BPM(`T` 可 Tap tempo)、查看各轨道音符
  分布;导出的 `chart.json` / `manifest.json` 直接对接 `make_pack.py --src`
  打包,也支持导入已有谱面继续编辑。
- **草稿**——按「文件名 + 时长」自动保存在浏览器里,重开页面选同一个音频
  即可恢复(含曲目信息、BPM、吸附与双押)。

B 站 `.m4s` 分段容器浏览器解不了,先转封装:
`ffmpeg -i in.m4s -c:a copy out.m4a`。

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
  external.py      外部音乐包(.tmbp):解析、ffmpeg 解码、PCM 播放器
  screens/         main_menu、freeplay、rhythm、rhythm_game、song_select
tools/
  make_pack.py     打包工具:ffmpeg 压缩音频并合成 .tmbp
  chart_canon_style.py  卡农风格自动作谱(旋律频段起始检测 + 双手规划)
  chart_studio.html     手动作谱台(独立网页,零依赖)
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
  只装 `pulseaudio-utils` 不会启动服务:先用 `pactl info` 确认能连上
  PipeWire/PulseAudio,否则程序会改用 ALSA。

## 许可说明

内置旋律均为公有领域作品。音频在运行时合成,不附带、不再分发任何 Minecraft 素材。