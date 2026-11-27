"""Themes: Unicode (Chinese, rounded buttons) and ASCII (English, plain).

A Theme bundles a border style with a localized string table. Screens call
theme.t(key) so switching mode instantly re-languages and re-styles the UI.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class Border:
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str


ROUNDED = Border("╭", "╮", "╰", "╯", "─", "│")
PLAIN = Border("+", "+", "+", "+", "-", "|")


class Theme:
    def __init__(self, lang: str, border: Border, strings: Dict[str, str]):
        self.lang = lang
        self.border = border
        self.strings = strings

    @property
    def is_unicode(self) -> bool:
        return self.lang == "zh"

    def t(self, key: str, **kw) -> str:
        s = self.strings.get(key, key)
        if kw:
            try:
                return s.format(**kw)
            except (KeyError, IndexError, ValueError):
                return s
        return s


ZH: Dict[str, str] = {
    "app.title": "终端音乐盒",
    "app.subtitle": "Terminal Music Box",
    "menu.freeplay": "自由演奏",
    "menu.rhythm": "音游模式",
    "menu.toggle_mode": "切换 Unicode / ASCII",
    "menu.quit": "退出",
    "menu.hint": "↑↓ 选择 · Enter 确认 · 鼠标可点击",
    "mode.unicode": "Unicode 模式（中文）",
    "mode.ascii": "ASCII 模式（英文）",
    "common.back": "返回",
    "common.confirm": "确认",
    "common.cancel": "取消",
    "common.yes": "是",
    "common.no": "否",
    "common.on": "开",
    "common.off": "关",
    "freeplay.title": "自由演奏",
    "freeplay.high": "高音",
    "freeplay.mid": "中音",
    "freeplay.low": "低音",
    "freeplay.timbre": "音色",
    "freeplay.switch_timbre": "^X 切换音色",
    "freeplay.prenatal": "胎教模式",
    "freeplay.prenatal_toggle": "^T 胎教模式",
    "freeplay.select_song": "^A 选歌",
    "freeplay.exit_hint": "^Q/^D/^C/Esc 返回",
    "freeplay.song": "曲目",
    "freeplay.prenatal_on": "胎教模式：开",
    "freeplay.prenatal_off": "胎教模式：关",
    "freeplay.prenatal_hint": "按任意演奏键开始或继续播放，2 秒无按键则暂停",
    "freeplay.no_song": "（默认列表第一首）",
    "freeplay.timbre_line": "音色：{name}    ^X 切换音色",
    "freeplay.prenatal_song": "胎教模式：开 · 曲目：{title}",
    "freeplay.keyboard": "C 大调 · 三个八度",
    "freeplay.btn_timbre": "^X 音色",
    "freeplay.btn_prenatal": "^T 胎教：{state}",
    "freeplay.btn_song": "^A 选歌",
    "freeplay.vol": "音量",
    "freeplay.len": "音长",
    "freeplay.playing": "播放中",
    "freeplay.paused": "已暂停",
    "song.select": "选择曲目",
    "song.default_first": "未选择，使用默认第一首",
    "rhythm.title": "音游模式",
    "rhythm.list": "曲目列表",
    "rhythm.builtin": "内置音乐",
    "rhythm.external": "外部音乐",
    "rhythm.external_empty": "将 .tmbp 音乐包放入 external_songs 目录",
    "rhythm.need_ffmpeg": "缺少 ffmpeg，无法播放该音乐包（安装：sudo apt install ffmpeg）",
    "rhythm.external_error": "音乐包加载失败：{msg}",
    "rhythm.functions": "功能",
    "rhythm.calibration": "延迟校正",
    "rhythm.keys": "键位设置",
    "rhythm.menu_hint": "←→/Tab 切换 · ↑↓ 选择 · Enter 确认 · Esc 返回",
    "rhythm.start": "开始游玩",
    "rhythm.score": "分数",
    "rhythm.combo": "连击",
    "rhythm.maxcombo": "最大连击",
    "rhythm.perfect": "完美",
    "rhythm.good": "良好",
    "rhythm.miss": "失败",
    "rhythm.accuracy": "准确率",
    "rhythm.pause": "暂停",
    "rhythm.resume": "继续",
    "rhythm.restart": "重新开始",
    "rhythm.quit": "退出",
    "rhythm.quit_to_list": "返回曲目列表",
    "rhythm.countdown": "准备",
    "rhythm.latency": "延迟校正",
    "rhythm.latency_hint": "跟随节拍按任意键，测量你的输入延迟",
    "rhythm.tap_count": "已采样 {n}/{total}",
    "rhythm.offset_ms": "当前延迟：{ms} 毫秒",
    "rhythm.calib_done": "校正完成：{ms} 毫秒",
    "rhythm.calib_reset": "已重置为 0 毫秒",
    "rhythm.keys_hint": "选择 lane 后按下新按键",
    "rhythm.key_lane": "轨道 {i}",
    "rhythm.key_saved": "键位已保存",
    "rhythm.result": "演奏结束",
    "rhythm.grade": "评级",
    "rhythm.new_record": "新纪录！",
    "rhythm.press_any": "按任意键开始采样",
    "prenatal.title": "胎教模式",
    "loading.title": "加载中",
}

EN: Dict[str, str] = {
    "app.title": "Terminal Music Box",
    "app.subtitle": "Terminal Music Box",
    "menu.freeplay": "Free Play",
    "menu.rhythm": "Rhythm Game",
    "menu.toggle_mode": "Toggle Unicode / ASCII",
    "menu.quit": "Quit",
    "menu.hint": "Up/Down select · Enter confirm · mouse clickable",
    "sound.title": "Sound Settings",
    "sound.hint": "Up/Down pick · Left/Right volume · A/D length · Enter preview · R reset",
    "sound.reset_done": "Reset to defaults",
    "mode.unicode": "Unicode mode (Chinese)",
    "mode.ascii": "ASCII mode (English)",
    "common.back": "Back",
    "common.confirm": "OK",
    "common.cancel": "Cancel",
    "common.yes": "Yes",
    "common.no": "No",
    "common.on": "ON",
    "common.off": "OFF",
    "freeplay.title": "Free Play",
    "freeplay.high": "High",
    "freeplay.mid": "Mid",
    "freeplay.low": "Low",
    "freeplay.timbre": "Timbre",
    "freeplay.switch_timbre": "^X switch timbre",
    "freeplay.prenatal": "Prenatal",
    "freeplay.prenatal_toggle": "^T prenatal",
    "freeplay.select_song": "^A song",
    "freeplay.exit_hint": "^Q/^D/^C/Esc back",
    "freeplay.song": "Song",
    "freeplay.prenatal_on": "Prenatal: ON",
    "freeplay.prenatal_off": "Prenatal: OFF",
    "freeplay.prenatal_hint": "Press any play key to start or resume; 2s idle pauses",
    "freeplay.no_song": "(default: first song)",
    "freeplay.timbre_line": "Timbre: {name}    ^X switch",
    "freeplay.prenatal_song": "Prenatal: ON - Song: {title}",
    "freeplay.keyboard": "C major - 3 octaves",
    "freeplay.btn_timbre": "^X Timbre",
    "freeplay.btn_prenatal": "^T Prenatal: {state}",
    "freeplay.btn_song": "^A Song",
    "freeplay.vol": "Vol",
    "freeplay.len": "Len",
    "freeplay.playing": "Playing",
    "freeplay.paused": "Paused",
    "song.select": "Select Song",
    "song.default_first": "none selected, using first default",
    "rhythm.title": "Rhythm Game",
    "rhythm.list": "Song List",
    "rhythm.list_title": "Song List",
    "rhythm.builtin": "Built-in Music",
    "rhythm.external": "External Music",
    "rhythm.external_empty": "Drop .tmbp packs into the external_songs folder",
    "rhythm.need_ffmpeg": "ffmpeg missing - cannot play this pack (sudo apt install ffmpeg)",
    "rhythm.external_error": "Failed to load pack: {msg}",
    "rhythm.functions": "Functions",
    "rhythm.calibration": "Latency Calibration",
    "rhythm.keys": "Key Config",
    "rhythm.menu_hint": "Left/Right/Tab switch · Up/Down select · Enter confirm · Esc back",
    "rhythm.start": "Start",
    "rhythm.score": "Score",
    "rhythm.combo": "Combo",
    "rhythm.maxcombo": "Max Combo",
    "rhythm.perfect": "PERFECT",
    "rhythm.good": "GOOD",
    "rhythm.miss": "MISS",
    "rhythm.accuracy": "Accuracy",
    "rhythm.pause": "Paused",
    "rhythm.resume": "Resume",
    "rhythm.restart": "Restart",
    "rhythm.quit": "Quit",
    "rhythm.quit_to_list": "Back to list",
    "rhythm.countdown": "Ready",
    "rhythm.latency": "Latency Calibration",
    "rhythm.latency_hint": "Tap any key on the beat to measure input latency",
    "rhythm.tap_count": "Samples {n}/{total}",
    "rhythm.offset_ms": "Current offset: {ms} ms",
    "rhythm.calib_done": "Calibrated: {ms} ms",
    "rhythm.calib_reset": "Reset to 0 ms",
    "rhythm.keys_hint": "Select a lane then press the new key",
    "rhythm.key_lane": "Lane {i}",
    "rhythm.key_saved": "Keys saved",
    "rhythm.result": "Results",
    "rhythm.grade": "Grade",
    "rhythm.new_record": "New record!",
    "rhythm.press_any": "Press any key to begin sampling",
    "prenatal.title": "Prenatal Mode",
    "loading.title": "Loading",
}

UNICODE_THEME = Theme("zh", ROUNDED, ZH)
ASCII_THEME = Theme("en", PLAIN, EN)


def theme_for(mode: str) -> Theme:
    return ASCII_THEME if mode == "ascii" else UNICODE_THEME