# -*- coding: utf-8 -*-
"""SSH 连接。IO 层用 paramiko interactive shell。
对前端透明：raw 流推 xterm，xterm 输入转发 channel.sendall。
含 keepalive + 断线指数退避重连。"""
import socket
import time, threading

from .base_conn import BaseConnection


def _tcp_probe(host, port, timeout):
    """快速 TCP 连通性探测（不读不写）。失败立即抛 ConnectionError。

    a606：用来把「主机不可达」和「主机可达但 banner 慢」区分开——前者
    10 秒内快速报错，后者给足 120 秒等 dropbear 吐 banner。

    a610（审计）：报错文案按原因分流。原来一律包成「TCP 连接失败：…」，
    把 api_connect 里原有的「无法解析主机」「端口未开放」分支全截胡了，
    DNS 解析失败的用户看到的是 `[Errno 11001] getaddrinfo failed`。
    """
    s = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
    except socket.gaierror as e:
        raise ConnectionError("无法解析主机 %s：%s" % (host, e))
    except ConnectionRefusedError:
        raise ConnectionError(
            "无法连接到 %s:%s（端口未开放或服务未启动）" % (host, port))
    except socket.timeout:
        raise ConnectionError(
            "连接 %s:%s 超时（网络不可达或端口被防火墙拦截）" % (host, port))
    except OSError as e:
        raise ConnectionError("TCP 连接失败：%s:%s（%s）" % (host, port, e))
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass

# SSH 集成（可选依赖：延迟导入——纯串口场景不加载 paramiko，省 ~300ms 启动时间）
# 用到 SSH 时才 import，避免启动时阻塞。paramiko 为 None 表示未安装。
_paramiko = None  # 懒加载缓存
def _get_paramiko():
    """延迟导入 paramiko，首次 SSH 连接时才加载。"""
    global _paramiko
    if _paramiko is not None:
        return _paramiko if _paramiko is not False else None
    try:
        import paramiko as _pk
        _paramiko = _pk
        return _paramiko
    except ImportError:
        _paramiko = False  # 标记未安装，避免重复尝试
        return None

class SSHConnection(BaseConnection):
    """SSH 连接。IO 层用 paramiko interactive shell。
    对前端透明：raw 流推 xterm，xterm 输入转发 channel.sendall。
    含 keepalive + 断线指数退避重连。"""
    kind = "ssh"

    def __init__(self, host, port, username, password=None, key_path=None, port_id=None):
        super().__init__(port_id or f"ssh:{host}:{port}")
        self.host = host
        self.ssh_port = int(port) if port else 22
        self.username = username
        self.password = password
        self.key_path = key_path
        # 兼容 api_status 的 p.port/p.baud 字段
        self.port = f"{username}@{host}"
        self.baud = None
        self._client = None
        self._channel = None
        self._keepalive = None
        self._keepalive_stop = None  # per-thread Event：见 _io_open/_keepalive_loop
        self._reconnect_attempts = 0
        self.start()

    def _io_open(self):
        paramiko = _get_paramiko()
        if paramiko is None:
            raise RuntimeError("paramiko 未安装，无法建立 SSH 连接")
        # 停掉旧 keepalive 线程（重连场景），避免多个线程并发 send_ignore。
        # per-thread Event：旧线程持有旧 Event，醒来即见 set 退出；新线程配新 Event。
        # 绝不重置标志——旧实现在 join 超时后把共享标志改回 False，阻塞在
        # sleep(30) 的旧线程醒来把新连接当自己的继续跑，多次闪断后线程净增。
        if self._keepalive_stop is not None:
            self._keepalive_stop.set()
        stop_evt = threading.Event()
        self._keepalive_stop = stop_evt
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        # a606（用户实锤「MobaXterm 能连、工具连不上」）：嵌入式设备上的
        # dropbear 经常要 15~20 秒才发 SSH banner（实测 10.20.115.193
        # dropbear_2026.91：TCP 1ms 就握手成功，banner 等 15s 才到，完整
        # 建连 20.2s）。原来的 timeout/banner_timeout 都是默认 10s，正好卡
        # 在这类设备外面 → paramiko 报 "Error reading SSH protocol banner" /
        # "No existing session"。MobaXterm 默认不设 banner 超时（或远大于
        # 10s）所以能连。
        #
        # 改成两段式，避免"主机根本不通"时也干等：先单独做 TCP 探测（10s），
        # 连不上立即抛（症状与原来一致）；通过后 banner/auth 给足 120s——
        # 与前端倒计时上限一致（超时由前端 abort，后端不再抢跑）。
        _tcp_probe(self.host, self.ssh_port, 10)
        kwargs = dict(hostname=self.host, port=self.ssh_port, username=self.username,
                       timeout=120, banner_timeout=120, auth_timeout=120,
                       allow_agent=False, look_for_keys=False)
        if self.key_path:
            kwargs["key_filename"] = self.key_path
        else:
            kwargs["password"] = self.password or None
        client.connect(**kwargs)
        self._client = client
        # 交互式 shell（PTY），匹配嵌入式设备 dropbear/uboot-over-ssh 场景。
        # v3.5.134 并入（写于 v3.5.128 轮，滞留工作区随本版提交——见 3f069ed 留痕 commit）：显式大列数起步（默认 80 列会让远端行编辑按 80 回绕，
        # 本地宽窗口里长命令回显错位拼接——svn st 实锤）；实际尺寸随后由
        # 前端 fit → /api/resize → resize() 精确同步
        chan = client.invoke_shell(width=200, height=50)
        self._channel = chan
        self._io_handle = chan
        # keepalive 线程
        self._keepalive = threading.Thread(target=self._keepalive_loop, args=(stop_evt,), daemon=True)
        self._keepalive.start()

    def resize(self, rows, cols):
        """PTY 尺寸同步（v3.5.134 并入：xterm onResize → /api/resize 到此）——
        远端行编辑按同步后的列数回绕，与本地终端显示一致。"""
        if self._channel is not None:
            self._channel.resize_pty(width=int(cols), height=int(rows))

    def _io_read_chunk(self):
        if self._channel is None:
            # 句柄为 None = 重连失败后的空窗：抛异常把 reader 驱回重连退避循环，
            # 否则静默返回 b"" 会让 reader 空转、永不再重试（老 bug：EOF 后只报一次就死透）
            raise EOFError("SSH 未连接")
        # recv 阻塞至有数据或 timeout；用 select 避免 100% CPU
        import select
        r, _, _ = select.select([self._channel], [], [], 0.2)
        if r:
            data = self._channel.recv(4096)
            if not data:
                # EOF：对端关闭
                raise EOFError("SSH channel EOF")
            return data
        return b""

    def _io_write(self, data: bytes):
        if self._channel is None: raise RuntimeError("SSH 未连接")
        self._channel.sendall(data)

    def _io_close(self):
        with self.lock:
            if self._channel:
                try: self._channel.close()
                except Exception: pass
                self._channel = None
            if self._client:
                try: self._client.close()
                except Exception: pass
                self._client = None

    def _io_reconnect(self):
        """指数退避重连：1s/2s/4s... 上限 60s。手动 disconnect（alive=False）不重连。
        退避等待可被 _reconn_kick 中断（按 R 立即重试）；close() 置 alive=False
        经下方检查放弃，不留幽灵会话。"""
        self._reconnect_attempts += 1
        delay = min(60, 2 ** (self._reconnect_attempts - 1))
        # 可中断等待：kick（按 R）或 close()（alive 变 False）都能立即醒
        self._reconn_kick.wait(delay)
        self._reconn_kick.clear()
        # close() 在退避期间到达：放弃重连，避免重连成功后无人关闭的幽灵会话
        # （占掉嵌入式设备 dropbear 通常限 1~2 个的会话名额）
        if not self.alive:
            return False
        try:
            self._io_close()
            if not self.alive:  # _io_close 期间被 close()：不再开新会话
                return False
            self._io_open()
            if not self.alive:  # 极端窗口：_io_open 刚建好会话 close() 才到达
                self._io_close()  # 立即回收，不留幽灵
                return False
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False

    def _keepalive_loop(self, stop_evt):
        """每 30s 发 keepalive，防 NAT/防火墙断连。stop_evt 为本线程专属 Event：
        换连接时 _io_open 对旧 evt set，本线程在下一个可中断片段退出。"""
        while self.alive and self._client is not None and not stop_evt.is_set():
            try:
                if not self.alive or self._client is None or stop_evt.is_set():
                    break
                # paramiko 2.10+ 用 send_okay，兼容旧版用 global_request
                t = self._client.get_transport() if self._client else None
                if t is not None:
                    try:
                        t.send_ignore()
                    except Exception:
                        try: t.global_request("keepalive@openssh.com", wait=False)
                        except Exception: pass
            except Exception:
                break
            for _ in range(300):  # 30s = 300×0.1s，可中断小段
                if not self.alive or stop_evt.is_set():
                    return
                time.sleep(0.1)
