# -*- coding: utf-8 -*-
"""本地终端连接（ConPTY 跑真实 shell：cmd / PowerShell / Git Bash）。

与 claude_conn.ClaudeConnection 同源（都用 pywinpty 的 ConPTY），差别只在
spawn 的命令行：那类是固定 claude CLI，这里是用户可选的 shell。kind='shell'。

设计取舍：
- 不落盘日志（与 claude 一致——本地交互终端无回看价值，用户要看的是真终端）
- EOF 不重连（用户敲 exit 是正常结束，重连会把已关的窗口又弹出来）
- resize 走 /api/resize 同一个端点（setwinsize）
- shell 退出时**不**自动关闭 tab（与设备断连不同，这里有退出码可看）
"""
import os
import threading

from .base_conn import BaseConnection
from .claude_conn import _get_pty


# 可选 shell：值 → (显示名, 命令行构造)。cmd 用 /K 保持窗口不退（用户要的是
# 「起来后直接就能敲命令」的常驻终端，不是执行完一条就关）。
#
# 代码页刻意**不**改（a588 实测）：ConPTY 会把子进程按当前代码页写出的字节
# 转成 UTF-8 交给我们，所以用户看到的中文与真实终端里完全一致。人为
# `chcp 65001` 反而让 cmd 用 UTF-8 解释既有 GBK 文件——实测 `type 日志.txt`
# 从「正确」变成 `����־`，`python ... > out.txt` 后 `type out.txt` 同样乱码，
# 而默认 936 下这两类都正确。UTF-8 文本（源码/JSON）在 936 下会花，但那条路
# 走「打开日志/编辑器」tab（内部自动探测编码），不该靠改终端代码页解决。
SHELLS = {
    "cmd": ("命令提示符", ["cmd.exe", "/K"]),
    "powershell": ("PowerShell", ["powershell.exe", "-NoLogo", "-NoExit"]),
    "pwsh": ("PowerShell 7", ["pwsh.exe", "-NoLogo", "-NoExit"]),
    "bash": ("Git Bash", ["bash.exe", "--login", "-i"]),
}


def _resolve_shell(shell):
    """把前端传入的 shell 名解析成 (显示名, argv)。未知值回落 cmd。"""
    key = (shell or "cmd").strip().lower()
    if key not in SHELLS:
        key = "cmd"
    name, argv = SHELLS[key]
    return key, name, argv


def validate_cwd(cwd):
    """校验用户给的工作目录。返回错误文案，None 表示通过。

    抽成纯函数是为了让 API 层与 ShellConnection 用同一套判据（此前两边
    各写一半：server 只查 isdir，相对路径按 Flask 进程 cwd 解析——用户以为
    指定了目录，实际在别处跑命令）。空串合法（= 用户主目录）。
    """
    cwd = (cwd or "").strip()
    if not cwd:
        return None
    if not os.path.isabs(cwd):
        return "工作目录请填绝对路径：%s" % cwd
    if not os.path.isdir(cwd):
        return "目录不存在：%s" % cwd
    return None


class ShellConnection(BaseConnection):
    """本地 ConPTY 终端。kind='shell'。

    cwd 为用户指定目录（留空=用户主目录），shell 决定起哪个终端。
    """
    kind = "shell"

    def __init__(self, shell="cmd", cwd=None, cols=120, rows=30, port_id=None):
        super().__init__(port_id or "shell:1")
        self.shell_key, self.shell_name, self._argv = _resolve_shell(shell)
        # a581（设计核实）：cwd 非法不能静默回落 ~——用户会以为路径生效，实际
        # 在 home 里跑命令。抛给 server 转 400 内联红字。
        # a588：判据抽到 validate_cwd，与 API 层共用（相对路径也要拒）。
        _err = validate_cwd(cwd)
        if _err:
            raise ValueError(_err)
        self.cwd = (cwd or "").strip() or os.path.expanduser("~")
        self._cols, self._rows = cols, rows
        # 兼容 api_status 的 p.port/p.baud 字段
        self.port = self.shell_name
        self.baud = None
        self._proc = None
        self._eof_handled = False
        self.start()

    # ---- start 覆盖：不落盘（同 ClaudeConnection）----
    def start(self):
        self._io_open()
        self.reader = threading.Thread(target=self._reader_loop, daemon=True)
        self.reader.start()

    def new_log(self):
        return None      # 本地终端不落盘

    # ---- IO 层 ----
    def _io_open(self):
        pp = _get_pty()
        if pp is None:
            raise RuntimeError("pywinpty 未安装（PTY 支持）。请执行：pip install pywinpty")
        env = dict(os.environ)
        # ConPTY 下的终端能力声明——没有这两个变量，很多 CLI 会退化成无颜色纯文本
        env.setdefault("TERM", "xterm-256color")
        env.setdefault("COLORTERM", "truecolor")
        # 刻意不设 PYTHONIOENCODING（a588 实测）：设成 utf-8 后 cmd 里
        # `python x.py > out.txt` 写出 UTF-8 字节，紧接着 `type out.txt` 在 936
        # 代码页下变成 `涓枃...`；不设则由 Python 自己跟随控制台代码页，
        # 写出的就是 936 字节，`type` 读回正确。用户在真 cmd 里得到的
        # 行为与这里必须一致。
        try:
            self._proc = pp.PtyProcess.spawn(self._argv, cwd=self.cwd, env=env,
                                             dimensions=(self._rows, self._cols))
        except FileNotFoundError:
            # a581：pywinpty 抛的是英文 FileNotFoundError，用户看不懂「命令
            # 找不到」到底缺什么。转成可操作的中文（如 Git Bash 未安装）。
            raise RuntimeError(
                "未安装 %s（%s 不在 PATH）。请先安装，或在弹窗里改选其他 Shell。"
                % (self.shell_name, self._argv[0]))
    def _io_read_chunk(self):
        if self._proc is None:
            return b""
        if not self._proc.isalive():
            return self._handle_eof()
        try:
            data = self._proc.read(8192)      # 阻塞读（str）；EOF 抛 EOFError
        except EOFError:
            return self._handle_eof()
        except OSError:
            # close() 竞态（terminate 后 read 抛系统错误而非干净 EOF）
            return self._handle_eof()
        return data.encode("utf-8", errors="replace")

    def _handle_eof(self):
        """shell 退出：提示一次后自然收尾。不重连（exit 是用户意图）。"""
        if not self._eof_handled:
            self._eof_handled = True
            _msg = ("[终端] 进程已退出（敲 exit 或 shell 异常结束）。"
                    "可点 ✕ 关闭此标签，或从「新建连接 → 终端」再开一个。")
            # a581：append_line 只进 buf（侧栏行数/搜索用），前端 xterm 只消费
            # _push_raw 的 raw 流——原来只调前者，敲 exit 后界面全静默。
            self.append_line(_msg)
            try:
                self._push_raw("\r\n" + _msg + "\r\n")
            except Exception:
                pass
        self.alive = False
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

    def _io_reconnect(self):
        """本地终端不自动重连（同 claude）：exit 后重连等于强行复活已关窗口。"""
        return False

    def resize(self, rows, cols):
        self._rows, self._cols = rows, cols
        if self._proc is None:
            return
        try:
            with self.lock:
                self._proc.setwinsize(rows, cols)
        except Exception:
            pass
