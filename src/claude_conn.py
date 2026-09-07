# -*- coding: utf-8 -*-
"""Claude Code 本地终端连接。IO 层用 pywinpty (ConPTY) 跑真实 claude CLI。
对前端透明：raw 流推 xterm，xterm 输入转发 PTY write。
与 SSH 的最大差异：EOF 是语义事件（claude /exit）不是故障——不重连，提示后自然退出。

设计文档：docs/CLAUDE_CODE_INTEGRATION.md（路线 A+C：终端保真 + 旁路状态面板）。
"""
import os, re, shutil, threading, tempfile, time

from .base_conn import BaseConnection

# pywinpty 可选依赖（延迟导入，参照 ssh_conn 的 paramiko 模式——纯串口场景不加载）
# 注意：包的 import 名是 winpty 不是 pywinpty（pip install pywinpty 装 winpty 包）
_pty_mod = None  # 懒加载缓存；False 表示未安装
def _get_pty():
    global _pty_mod
    if _pty_mod is not None:
        return _pty_mod if _pty_mod is not False else None
    try:
        from winpty import ptyprocess as _pp
        _pty_mod = _pp
        return _pp
    except ImportError:
        _pty_mod = False
        return None


class ClaudeNotFoundError(RuntimeError):
    """claude CLI 未安装或找不到。消息面向用户可操作（含安装指引）。"""


# ---- claude 可执行解析（结果缓存；force=True 强制重试） ----
_exe_cache = None  # (path, is_cmd_shim) 或 None

def _resolve_claude_exe(force=False):
    """按序解析 claude 可执行路径。返回 (path, is_cmd_shim)。

    顺序：
    1. 环境变量 SERIAL_CLAUDE_EXE（用户覆盖口）
    2. shutil.which("claude.exe")（直接命中最理想）
    3. which("claude") 解析到 claude.CMD → 推导同目录 npm 包内 claude.exe
       （node_modules\\@anthropic-ai\\claude-code\\bin\\claude.exe，npm shim 标准布局）
    4. 兜底：.CMD 路径 + is_cmd_shim=True（spawn 时经 cmd.exe /c 中转）
    """
    global _exe_cache
    if _exe_cache is not None and not force:
        return _exe_cache
    # 1. 环境变量覆盖
    env_p = os.environ.get("SERIAL_CLAUDE_EXE", "").strip()
    if env_p:
        if os.path.isfile(env_p):
            _exe_cache = (env_p, False)
            return _exe_cache
        raise ClaudeNotFoundError(
            f"环境变量 SERIAL_CLAUDE_EXE 指向的文件不存在：{env_p}\n"
            f"请修正该变量，或清除后让工具自动查找 claude。")
    # 2. PATH 上的 claude.exe
    p = shutil.which("claude.exe")
    if p and os.path.isfile(p):
        _exe_cache = (p, False)
        return _exe_cache
    # 3. claude.CMD（npm shim）→ 推导包内真身
    p = shutil.which("claude")
    if p and os.path.isfile(p):
        inner = os.path.join(os.path.dirname(p), "node_modules",
                             "@anthropic-ai", "claude-code", "bin", "claude.exe")
        if os.path.isfile(inner):
            _exe_cache = (inner, False)
            return _exe_cache
        # 4. 兜底：cmd shim 中转（多一层进程树，terminate 时实测验证）
        if p.lower().endswith((".cmd", ".bat")):
            _exe_cache = (p, True)
            return _exe_cache
        _exe_cache = (p, False)
        return _exe_cache
    raise ClaudeNotFoundError(
        "未检测到 claude CLI。安装：npm install -g @anthropic-ai/claude-code\n"
        "（若已安装仍提示找不到，重启本工具让它继承最新 PATH，"
        "或设环境变量 SERIAL_CLAUDE_EXE 指向 claude.exe 全路径）")


def _humanize_claude_error(e):
    """把连接构造异常转成可操作中文。"""
    if isinstance(e, ClaudeNotFoundError):
        return str(e)
    msg = str(e)
    if "winpty" in msg or "pywinpty" in msg or _get_pty() is None and "pty" in msg.lower():
        return "pywinpty 未安装（PTY 支持）。请在工具所用 Python 环境执行：pip install pywinpty"
    return f"claude 启动失败：{msg}"


def _bg_sessions_running():
    """列出正以后台 agent 运行的 session_id 集合。
    信号：bg agent 是独立 claude 进程，命令行带 --session-id <uuid>。
    wmic 扫进程命令行（本机 Windows；失败返回空集——最坏也只是
    claude 自己再报一次红字）。"""
    try:
        import subprocess
        # CREATE_NO_WINDOW：工具是 GUI 进程（无控制台），wmic 是控制台程序——
        # 不加此标志每次点恢复都会闪一个黑色 cmd 窗口
        out = subprocess.run(
            ["wmic", "process", "where", "commandline like '%--session-id%'",
             "get", "CommandLine"],
            capture_output=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout or b""
        # wmic 输出是本地代码页（GBK）——text=True 用 cp1252/utf8 解会乱，
        # 拿 bytes 手工按 GBK 解（--session-id <uuid> 是 ASCII，怎么解都不损）
        txt = out.decode("gbk", errors="replace")
        return set(re.findall(r"--session-id ([0-9a-f-]{36})", txt))
    except Exception:
        return set()


def _trust_workspace(cwd):
    """恢复/打开会话前把 cwd 的信任位写成 true（~/.claude.json projects 段）。
    用户从本工具面板主动恢复会话 = 用户信任该目录（会话本来就在那开的），
    不该每次都卡 trust folder 确认。只动这一个目录，锁内写防并发。"""
    if not cwd or not os.path.isdir(cwd):
        return
    try:
        import json
        from threading import Lock
        if not hasattr(_trust_workspace, "_lock"):
            _trust_workspace._lock = Lock()
        with _trust_workspace._lock:
            path = os.path.join(os.path.expanduser("~"), ".claude.json")
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            projs = d.setdefault("projects", {})
            key = cwd.replace("\\", "/")
            ent = projs.setdefault(key, {})
            if not ent.get("hasTrustDialogAccepted"):
                ent["hasTrustDialogAccepted"] = True
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False)
                os.replace(tmp, path)
    except Exception:
        pass   # 预信任失败不阻塞启动——大不了弹一次确认，用户手动点 Yes


class ClaudeConnection(BaseConnection):
    """本地 ConPTY 跑 claude CLI。kind='claude'。

    - 不落盘日志（Claude 自带 ~/.claude 转写；工具行式日志存 TUI 重绘流无回看价值）
    - EOF 不重连（claude /exit 是正常结束）
    - resize(rows, cols) 由 /api/resize 调用，转 PTY setwinsize
    """
    kind = "claude"

    def __init__(self, cwd=None, resume=None, cols=120, rows=30, port_id=None, light_theme=False, agents=False):
        super().__init__(port_id or "claude:1")
        self.cwd = cwd or os.path.expanduser("~")
        self.resume = resume or None
        self.agents = bool(agents)   # True：打开 claude agents TUI（接管后台会话本体的官方入口）
        self._cols, self._rows = cols, rows
        self._light_theme = bool(light_theme)
        # 兼容 api_status 的 p.port/p.baud 字段
        base = os.path.basename(os.path.normpath(self.cwd)) or self.cwd
        self.port = f"Claude({base})"
        self.baud = None
        self._proc = None
        self._eof_handled = False
        self.start()

    # ---- start 覆盖：不落盘（见类 docstring）----
    def start(self):
        self._io_open()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()
        # 不调 _start_log：log_fp 保持 None（append_line 已判空），buf 保留供搜索/感知

    def new_log(self):
        # 无日志可开（不落盘）；返回提示而非抛炸
        return None

    # ---- IO 层 ----
    def _io_open(self):
        pp = _get_pty()
        if pp is None:
            raise RuntimeError("pywinpty 未安装（pip install pywinpty）")
        # 预信任 cwd：面板恢复/打开 = 用户主动信任，跳过 trust folder 确认
        _trust_workspace(self.cwd)
        exe, is_shim = _resolve_claude_exe()
        if is_shim:
            # .CMD 不能直接 CreateProcess：经 cmd.exe /c 中转（多一层进程树）
            argv = ["cmd.exe", "/c", exe]
        else:
            argv = [exe]
        if self.resume:
            argv += ["--resume", self.resume]
        elif self.agents:
            # claude agents TUI：接管正以后台 agent 运行的会话本体的官方入口
            # （--resume 后台会话被 claude 拒绝；无 CLI attach flag，TUI 回车即接管）
            argv += ["agents"]
        # 每个会话都建 --settings 临时文件（不只亮色）：theme 键随工具壳体亮暗写入
        # （亮=light-ansi 走 ANSI 16 色、颜色落到本工具 xterm 调色板；暗=dark 保持
        # 默认观感）。--settings 只作用于当前进程、不写用户配置文件。工具中途换主题
        # 时改写此文件即可——Claude 监视 settings 文件热重载，运行中会话立即生效。
        # 必须用临时文件而非内联 JSON：cmd shim 中转时 cmd.exe /c 会剥掉
        # 内联 JSON 的双引号，claude 收到非法 JSON 直接报错；文件路径无此问题。
        fd, settings_path = tempfile.mkstemp(suffix=".json", prefix="claude_theme_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write('{"theme": "%s"}' % ("light-ansi" if self._light_theme else "dark"))
        self._theme_settings_path = settings_path
        argv += ["--settings", settings_path]
        env = dict(os.environ)  # ConPTY 要求完整环境；claude 依赖 PATH/HOME/TERM
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        # cwd 必须显式传：不传则继承后端进程 cwd（所有会话都开在工具目录）
        self._proc = pp.PtyProcess.spawn(argv, cwd=self.cwd, env=env,
                                         dimensions=(self._rows, self._cols))

    def _io_read_chunk(self):
        if self._proc is None:
            return b""
        if not self._proc.isalive():
            return self._handle_eof()
        try:
            data = self._proc.read(8192)   # 阻塞读（str）；EOF 抛 EOFError
        except EOFError:
            return self._handle_eof()
        except OSError:
            # close() 竞态（terminate 后 read 抛系统错误而非干净 EOF）
            return self._handle_eof()
        return data.encode("utf-8", errors="replace")

    def _handle_eof(self):
        """claude 进程退出：提示一次、自然收尾。不重连（语义事件非故障）。"""
        if not self._eof_handled:
            self._eof_handled = True
            self.append_line("[claude] 进程已退出，会话结束。可点 ✕ 关闭，或从 Claude 面板恢复。")
        self.alive = False   # 让 _reader_loop 的 while 自行退出
        self._cleanup_theme_settings()
        try:
            self._io_close()
        except Exception:
            pass
        return b""

    def _io_write(self, data: bytes):
        if self._proc is None:
            return
        # PtyProcessUnicode 语义：write 接 str
        self._proc.write(data.decode("utf-8", errors="replace"))

    def _io_close(self):
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.isalive():
                proc.terminate(force=True)
        except Exception:
            pass
        self._cleanup_theme_settings()

    def _cleanup_theme_settings(self):
        """删除 --settings 临时文件（claude 启动时已读完，进程退出后清理）。"""
        p = getattr(self, "_theme_settings_path", None)
        if p:
            self._theme_settings_path = None
            try:
                os.remove(p)
            except Exception:
                pass

    # /theme 菜单选项文本(与 buf 清洗行匹配用)。菜单:1.Auto 2.Dark 3.Light
    # 4.Dark-色盲 5.Light-色盲 6.Dark-ANSI 7.Light-ANSI 8.自定义
    _THEME_MENU_LIGHT = 7   # light-ansi:颜色落 ANSI 16 色,由本工具 xterm 亮色调色板解释
    _THEME_MENU_DARK = 2
    _THEME_MENU_ITEMS = ["Auto (match terminal)", "Dark mode", "Light mode",
                         "Dark mode (colorblind-friendly)", "Light mode (colorblind-friendly)",
                         "Dark mode (ANSI colors only)", "Light mode (ANSI colors only)",
                         "New custom theme"]

    def _theme_menu_cursor(self, base_seq, wait_s=2.0):
        """开 /theme 菜单后,从 base_seq 之后的新增清洗行里找 ❯ 光标所在选项
        序号(1~8)。只看新增行:buf 是 TUI 重绘流,上次菜单的旧 ❯ 帧还在尾部,
        混读会把旧光标当当前位置(实测翻车:落到相邻项)。找不到返回 None。"""
        deadline = time.time() + wait_s
        while time.time() < deadline:
            time.sleep(0.3)
            for it in reversed(self.get_buffer_after(base_seq, 60)):
                s = (it.get("text") or "").strip()
                if s.startswith("❯"):
                    for i, name in enumerate(self._THEME_MENU_ITEMS, 1):
                        if name in s:
                            return i
                    return None   # ❯ 行存在但不匹配任何选项(异常状态)
        return None

    def set_light_theme(self, light):
        """工具壳体换主题时让运行中的会话自己切(/api/claude_theme 调用)。
        settings 文件热重载实测无效(2.1.239 改文件无重绘)——走 TUI 菜单注入。
        菜单光标每次定位在"当前生效主题"上(起点漂移,盲导航必错,实测翻过车),
        必须闭环。逐键闭环导航(不是一次性连发 N 键再 Enter——TUI 偶尔吞键,
        盲发差值会落到相邻项,实测翻车:目标 7 落到 6=dark-ansi):
        每按一个 ↓ 都回读光标实际位置,没动就重发,到位才 Enter。"""
        if self._proc is None:
            return False
        target = self._THEME_MENU_LIGHT if light else self._THEME_MENU_DARK
        try:
            # 1) 开菜单(记 buf 序号,之后只看新增行——旧菜单帧混读会拿到旧光标)
            with self.buf_lock:
                base_seq = self.buf[-1]["seq"] if self.buf else 0
            self._io_write(b"/theme\r")
            time.sleep(1.0)
            cur = self._theme_menu_cursor(base_seq)
            if cur is None:
                # 菜单没开或读不到光标:Esc 兜底关闭,放弃本次(不乱动用户界面)
                self._io_write(b"\x1b")
                return False
            # 2) 逐键闭环:每按一个 ↓ 回读光标,没动重发(最多 2 次重试/步)
            retries = 0
            while cur != target and retries < 16:
                last_seq = cur
                with self.buf_lock:
                    nav_seq = self.buf[-1]["seq"] if self.buf else 0
                self._io_write(b"\x1b[B")
                nxt = self._theme_menu_cursor(nav_seq, wait_s=1.0)
                if nxt is None or nxt == last_seq:
                    retries += 1   # 键被吞:同一步重发(不上限次数,只累计重试)
                    continue
                retries = 0
                cur = nxt
            if cur != target:
                self._io_write(b"\x1b")
                return False
            # 3) Enter 确认(确认后的 "Theme set to" 行不会带 ❯,不影响下轮)
            self._io_write(b"\r")
            time.sleep(0.8)
            # 4) 验证:新增行里找 "Theme set to <dark|light-ansi>"
            confirm = "light-ansi" if light else "dark"
            got = [it.get("text") or "" for it in self.get_buffer_after(base_seq, 60)]
            if any("Theme set to" in t and confirm in t for t in got):
                self._light_theme = bool(light)
                return True
            # 5) 没确认行(Enter 被排队/会话生成中):Esc 关菜单防残留
            self._io_write(b"\x1b")
            return False
        except Exception:
            return False

    def _io_reconnect(self):
        # claude 无重连语义（EOF 路径已让 reader 干净退出，不会走到这；保险起见拒绝）
        return False

    # ---- resize（/api/resize 调用）----
    def resize(self, rows, cols):
        self._rows, self._cols = rows, cols
        if self._proc is None:
            return
        try:
            with self.lock:
                self._proc.setwinsize(rows, cols)
        except Exception:
            pass
