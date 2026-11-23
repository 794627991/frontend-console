# -*- coding: utf-8 -*-
"""2026-11-23 总审计壳侧（electron/main.js）修复的回归锚。

  P0-3     截图双触发去重：原 snipLastArmTs 只写不读，防重置全靠 snipArming
           在途锁（函数一返回就松）。SSE 回声晚到会重新 arm，拖到一半的
           选区被重置。现以「流程进行中 + 去重窗内」判为回声并流。
  a683-A4  log() 是 args.join(' ')，不解析占位符 → 退出日志显式 util.format
  a683-A5  spawn 只挂 exit 无 error 监听 → 可执行不存在时壳无声消失
  a683-A6  did-finish-load 补发文件关联只 send 不唤起（窗口藏在托盘时无反应）
  a683-A8  BOOT_TIMEOUT_DEV_MS 的注释理由（首启 pip 补装）已失效
  W-7      fc:save-as 非主 UI 拒绝返回 ''（与取消无法区分）→ 抛错
  a688-A3  readConfigBool 读 endpoint 取 tool_data_dir 不比对 boot_token

去重逻辑与 readConfigBool 是从 main.js 抽出原函数在 node 里**真跑**
（需要 node，没有则 skip）；其余几条是结构/源码断言。
"""
import json
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_JS = os.path.join(ROOT, "electron", "main.js")
NODE = shutil.which("node")


def _js():
    with open(MAIN_JS, encoding="utf-8") as f:
        return f.read()


def _seg(js, start, end):
    """取 start（含）到 end（不含）的原文；两个锚点都必须存在且唯一。"""
    assert js.count(start) == 1, "锚点不唯一/不存在：" + start
    i = js.index(start)
    j = js.index(end, i)
    return js[i:j]


def _run_node(code):
    if not NODE:
        pytest.skip("node 不可用")
    p = subprocess.run([NODE, "-e", code], capture_output=True, text=True,
                       encoding="utf-8")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


# ---------------------------------------------------------------- P0-3

_SNIP_HARNESS = """
const log = () => {};
const endpointUrl = 'http://backend.test';
let now = 1000000;
Date.now = () => now;
// openSnipWindow / _snipArmStart 依赖的外部件全部桩掉
const _snipGeo = async () => ({});
const _snipTarget = () => ({ bounds: { x: 0, y: 0, width: 100, height: 100 } });
const _snipPhysOffset = () => ({ x: 0, y: 0 });
const _snipSameBounds = (a, b) => !!a && !!b && a.width === b.width;
const _snipCreate = () => {};
const _snipDeliverArm = () => {};
// ---- 被测原文 ----
%(VARS)s
%(FNS)s
// ---- 计数：包住 _snipArmStart ----
let armCalls = 0;
const __realArmStart = _snipArmStart;
_snipArmStart = function (phys) { armCalls++; return __realArmStart(phys); };
%(OPEN)s
// ---- 场景 ----
const out = {};
(async () => {
  // 1) 首次触发：arm 一次
  let r = await openSnipWindow();
  out.first = { ok: r.ok, arms: armCalls };
  // 2) 回声：按钮路径已返回，SSE 路径 300ms 后晚到 → 并流，不再 arm
  now += 300;
  r = await openSnipWindow();
  out.echo_300ms = { ok: r.ok, arms: armCalls };
  // 3) 对话高峰期：回声晚到 2s 仍在窗内 → 并流
  now += 1700;
  r = await openSnipWindow();
  out.echo_2s = { ok: r.ok, arms: armCalls };
  // 4) 流程结束（完成/取消/取图失败都走 _snipHide）后再触发 → 正常重新 arm
  _snipHide();
  now += 10;
  r = await openSnipWindow();
  out.after_hide = { ok: r.ok, arms: armCalls };
  // 5) 截图界面里隔了 3s 再按键（窗口外）= 重新开始 → 正常 arm
  now += 3000;
  r = await openSnipWindow();
  out.user_again_3s = { ok: r.ok, arms: armCalls };
  // 6) 销毁（8s 未 ready / 渲染进程崩溃 / 加载失败）同样关门
  _snipDestroy();
  now += 10;
  r = await openSnipWindow();
  out.after_destroy = { ok: r.ok, arms: armCalls };
  // 7) 取图失败（fc:snip-fail → _snipHide）后立刻再按：不能被并流吞掉
  _snipHide();
  now += 5;
  r = await openSnipWindow();
  out.after_fail = { ok: r.ok, arms: armCalls };
  console.log(JSON.stringify(out));
  process.exit(0);   // _snipHide 留了 10 分钟空闲回收定时器，别等它
})();
"""


def _snip_fresh_run(js):
    code = _SNIP_HARNESS % {
        "VARS": _seg(js, "let snipWin = null;",
                     "// 显示三连（ready 与 8s 兜底共用）："),
        "FNS": _seg(js, "function _snipArmStart(phys) {", "async function _snipGeo() {"),
        "OPEN": _seg(js, "async function openSnipWindow() {", "function prewarmSnip() {"),
    }
    return _run_node(code)


def test_snip_echo_within_window_does_not_rearm():
    got = _snip_fresh_run(_js())
    assert got["first"] == {"ok": True, "arms": 1}
    # 旧实现：按钮路径返回后在途锁即松，晚到的回声重新 arm（arms 变 2、3）
    assert got["echo_300ms"] == {"ok": True, "arms": 1}, got
    assert got["echo_2s"] == {"ok": True, "arms": 1}, got


def test_snip_rearm_after_flow_ends_or_beyond_window():
    """去重窗只挡回声：流程结束后的触发、窗口外的再次按键都必须照常 arm。"""
    got = _snip_fresh_run(_js())
    assert got["after_hide"] == {"ok": True, "arms": 2}, got
    assert got["user_again_3s"] == {"ok": True, "arms": 3}, got
    assert got["after_destroy"] == {"ok": True, "arms": 4}, got
    assert got["after_fail"] == {"ok": True, "arms": 5}, got


def test_snip_dedup_window_is_wired_both_ways():
    """snipLastArmTs 必须有读点（原实现只写不读 = 注释里的防护）。"""
    js = _js()
    reads = [ln for ln in js.splitlines()
             if "snipLastArmTs" in ln and "Date.now() - snipLastArmTs" in ln]
    assert len(reads) == 1, reads
    assert "const SNIP_DUP_WINDOW_MS = " in js
    # 流程结束的每条路径都要关门
    for fn in ("_snipHide", "_snipDestroy"):
        seg = _seg(js, "function %s() {" % fn, "\n}\n")
        assert "snipArmActive = false" in seg, "%s 没有复位 snipArmActive" % fn


def test_snip_closed_event_resets_active_flag():
    js = _js()
    seg = _seg(js, "w.on('closed', () => {", "  // 意外最大化护栏")
    assert "snipArmActive = false" in seg


# ---------------------------------------------------------------- a688-A3

_CFG_HARNESS = """
const path = require('path');
let BOOT_TOKEN = 'tok-new';
const CONFIG_FILE = 'C:\\\\tool\\\\data\\\\config.json';
const ENDPOINT_FILE = 'C:\\\\anchor\\\\endpoint.json';
const files = {};
const fs = {
  readFileSync: (p, enc) => {
    if (!(p in files)) { const e = new Error('ENOENT'); e.code = 'ENOENT'; throw e; }
    return files[p];
  },
};
const cfgAt = (v) => JSON.stringify({ close_to_tray: v });   // 布尔：readConfigBool 只回 true/false
%s
const out = {};
// ① 本次启动的后端写的 endpoint：采信 tool_data_dir（那里写的是 false）
files[ENDPOINT_FILE] = JSON.stringify({ boot_token: 'tok-new', url: 'http://127.0.0.1:1',
                                        tool_data_dir: 'D:\\\\migrated' });
files[path.join('D:\\\\migrated', 'config.json')] = cfgAt(false);
out.fresh = readConfigBool('close_to_tray', true);
// ② 残留 endpoint（上一位置的 tool_data_dir，token 是旧的）：不采信 → 回落
//    到 CONFIG_FILE。两处取值相反，读错文件一眼可辨
files[ENDPOINT_FILE] = JSON.stringify({ boot_token: 'tok-stale', url: 'http://127.0.0.1:2',
                                        tool_data_dir: 'D:\\\\old-place' });
files[path.join('D:\\\\old-place', 'config.json')] = cfgAt(false);
files[CONFIG_FILE] = cfgAt(true);
out.stale = readConfigBool('close_to_tray', true);
// ③ 无 endpoint：回落（原行为不变）
delete files[ENDPOINT_FILE];
out.no_endpoint = readConfigBool('close_to_tray', true);
// ④ 回落位置也读不到：用默认值
delete files[CONFIG_FILE];
out.dft = readConfigBool('close_to_tray', 'DEFAULT');
console.log(JSON.stringify(out));
"""


def test_read_config_bool_only_trusts_this_boots_endpoint():
    code = _CFG_HARNESS % _seg(_js(), "function readConfigBool(key, dft) {",
                               "function loadShellState() {")
    got = _run_node(code)
    assert got == {"fresh": False, "stale": True,
                   "no_endpoint": True, "dft": "DEFAULT"}, got


def test_boot_token_is_module_level_and_assigned_in_boot():
    js = _js()
    assert "let BOOT_TOKEN = '';" in js               # 模块级（readConfigBool 可见）
    assert "const BOOT_TOKEN = " not in js            # 不再是 boot() 的局部量
    assert "BOOT_TOKEN = crypto.randomUUID" in js
    seg = _seg(js, "function readConfigBool(key, dft) {", "function loadShellState() {")
    assert "ep.boot_token === BOOT_TOKEN" in seg


# ---------------------------------------------------------------- 结构断言

def test_backend_has_error_listener_going_to_fatal():
    js = _js()
    seg = _seg(js, "backend.on('error',", "backend.on('exit',")
    assert "backend.on('error', (err) => {" in seg
    assert "fatal('后端启动失败'" in seg
    # spawn 失败后轮询必须收手（'exit' 不保证再来、exitCode 仍为 null）
    loop = _seg(js, "while (Date.now() < deadline) {", "fatal('后端启动超时',")
    assert loop.count("spawnFailed || backend.exitCode !== null") == 2, \
        "就绪轮询的两处提前返回都要认 spawnFailed"


def test_log_calls_do_not_rely_on_printf_placeholders():
    """log() 是 args.join(' ')：带 %s/%d 的调用必须自己 util.format。"""
    import re
    js = _js()
    bad = [ln.strip() for ln in js.splitlines()
           if re.search(r"(?<![\w.])log\((?!util\.format)[^;]*%[sdjO]", ln)]
    assert bad == [], bad
    assert "const util = require('util');" in js
    assert "log(util.format('后端退出 code=%s signal=%s（booted=%s）'" in js


def test_pending_open_file_replay_wakes_hidden_window():
    js = _js()
    seg = _seg(js, "win.webContents.on('did-finish-load', () => {",
               "// 窗口记忆：move/resize 防抖落盘")
    assert "win.webContents.send('fc:open-file', p);" in seg
    # 唤起，但不抢首启的首显时机（ready-to-show 之前窗口刻意不显）
    assert "if (winShownOnce && !win.isVisible()) showWindowFromTray();" in seg
    assert "win.once('ready-to-show', () => { if (win) { winShownOnce = true; win.show(); } });" in js


def test_save_as_rejects_non_main_ui_by_throwing():
    js = _js()
    seg = _seg(js, "ipcMain.handle('fc:save-as', async (event, opts) => {",
               "  const o = opts || {};")
    assert "if (!_isMainUi(event)) throw new Error(" in seg
    assert "return ''" not in seg.split("if (!_isMainUi(event))")[1].splitlines()[0]
    # 两处调用方都要能接住（否则非主窗拒绝变成未处理的 rejection）：
    # 调用点之前最近的开启块是 try（而不是已经闭合的旧 try），之后有 catch
    for f in ("web/js/backend-log.js", "web/js/nav.js"):
        with open(os.path.join(ROOT, f), encoding="utf-8") as fh:
            src = fh.read()
        i = src.index("fcShell.saveAs({")
        before = src[:i]
        assert before.rfind("try {") > before.rfind("} catch"), \
            "%s 的 saveAs 调用必须在 try 内" % f
        tail = src[i:i + 900]
        assert "} catch (_) {" in tail and "无法打开保存框" in tail, f


def test_boot_timeout_comment_no_longer_cites_pip_autoload():
    js = _js()
    seg = js[:js.index("const POLL_MS = 250;")]
    assert "deps_bootstrap 早已改为只打印 pip 指引" in seg
    assert "首启可能先跑 pip 补装" not in seg
    # 注释理由变了，数值不动（源码形态慢启动宁慢勿误杀）
    assert "const BOOT_TIMEOUT_DEV_MS = 180 * 1000;" in seg
    # 理由必须属实：deps_bootstrap 不自动 pip
    with open(os.path.join(ROOT, "src", "deps_bootstrap.py"), encoding="utf-8") as fh:
        py = fh.read()
    assert "pip_cmd = \"pip install \"" in py          # 只是打印指引
    for needle in ("subprocess.run", "check_call", "Popen"):
        assert needle not in py, "deps_bootstrap 出现了自动执行：%s" % needle


if __name__ == "__main__":
    import pytest as _pt
    sys.exit(_pt.main([__file__, "-q"]))
