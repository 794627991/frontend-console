# -*- coding: utf-8 -*-
"""SSH 连接。IO 层用 paramiko interactive shell。
对前端透明：raw 流推 xterm，xterm 输入转发 channel.sendall。
含 keepalive + 断线指数退避重连。"""
import time, threading

from .base_conn import BaseConnection

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
        self._reconnect_attempts = 0
        self.start()

    def _io_open(self):
        paramiko = _get_paramiko()
        if paramiko is None:
            raise RuntimeError("paramiko 未安装，无法建立 SSH 连接")
        # 停掉旧 keepalive 线程（重连场景），避免多个线程并发 send_ignore
        self._keepalive_stop = True
        if getattr(self, "_keepalive", None) and self._keepalive.is_alive():
            try: self._keepalive.join(timeout=1.0)
            except Exception: pass
        self._keepalive_stop = False
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(hostname=self.host, port=self.ssh_port, username=self.username,
                       timeout=10, allow_agent=False, look_for_keys=False)
        if self.key_path:
            kwargs["key_filename"] = self.key_path
        else:
            kwargs["password"] = self.password
        client.connect(**kwargs)
        self._client = client
        # 交互式 shell（PTY），匹配嵌入式设备 dropbear/uboot-over-ssh 场景
        chan = client.invoke_shell()
        self._channel = chan
        self._io_handle = chan
        # keepalive 线程
        self._keepalive = threading.Thread(target=self._keepalive_loop, daemon=True)
        self._keepalive.start()

    def _io_read_chunk(self):
        if self._channel is None:
            time.sleep(0.1)
            return b""
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
        """指数退避重连：1s/2s/4s... 上限 60s。手动 disconnect（alive=False）不重连。"""
        self._reconnect_attempts += 1
        delay = min(60, 2 ** (self._reconnect_attempts - 1))
        time.sleep(delay)
        try:
            self._io_close()
            self._io_open()
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False

    def _keepalive_loop(self):
        """每 30s 发 keepalive，防 NAT/防火墙断连。"""
        while self.alive and self._client is not None and not getattr(self, "_keepalive_stop", False):
            try:
                time.sleep(30)
                if not self.alive or self._client is None or getattr(self, "_keepalive_stop", False):
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
