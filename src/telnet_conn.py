# -*- coding: utf-8 -*-
"""Telnet 连接。IO 层用裸 socket + IAC 协商（不引 telnetlib/telnetlib3——
Python 3.13 已移除标准 telnetlib，telnetlib3 是 asyncio 架构且为新增依赖，
而本工具无网自足原则下 Telnet 协议协商仅 ~40 行，自实现最合算）。
对前端透明：raw 流推 xterm，xterm 输入转发 socket.sendall。
含断线指数退避重连（同 SSHConnection）。"""
import socket
import select
import threading
import time

from .base_conn import BaseConnection

# Telnet 协议控制字节（RFC 854）
IAC, DONT, DO, WONT, WILL = 255, 254, 253, 252, 251
SB, SE = 250, 240   # 子协商起止（内容原样丢弃，仅保协议流干净）

# 服务端 WILL X（它要开功能）→ 一律 WONT X（客户端不支持）；
# 服务端 DO X（要客户端开）→ 一律 WONT X。
# BSP 调试场景设备只回显 shell 字节流，拒绝全部协商最稳妥
# （拒绝 echo 还能让设备端回显生效，避免双重回显）。
def _handle_iac(sock, buf):
    """处理 buf 中的 IAC 序列：回复协商、剥离控制字节，返回纯净负载。"""
    out = bytearray()
    i = 0
    n = len(buf)
    while i < n:
        b = buf[i]
        if b != IAC:
            out.append(b)
            i += 1
            continue
        if i + 1 >= n:            # 截断的 IAC，丢弃（下块重新对齐风险极低）
            break
        cmd = buf[i + 1]
        if cmd == IAC:            # IAC IAC = 字面 255 数据
            out.append(IAC)
            i += 2
        elif cmd in (WILL, WONT, DO, DONT):
            if i + 2 >= n:
                break
            opt = buf[i + 2]
            if cmd == WILL:
                sock.sendall(bytes((IAC, DONT, opt)))
            elif cmd == DO:
                sock.sendall(bytes((IAC, WONT, opt)))
            i += 3
        elif cmd == SB:           # 子协商：吞到 IAC SE
            j = i + 2
            while j + 1 < n and not (buf[j] == IAC and buf[j + 1] == SE):
                j += 1
            i = j + 2 if j + 1 < n else n
        else:                     # 其余两字节命令（如 GOAHEAD 249）
            i += 2
    return bytes(out)


class TelnetConnection(BaseConnection):
    """Telnet 连接（TCP 23 端口为主，端口可自定义）。"""
    kind = "telnet"

    def __init__(self, host, port=23, port_id=None):
        super().__init__(port_id or f"telnet:{host}:{port}")
        self.host = host
        self.telnet_port = int(port) if port else 23
        # 兼容 api_status 的 p.port/p.baud 字段
        self.port = f"{host}:{self.telnet_port}"
        self.baud = None
        self._reconnect_attempts = 0
        self.start()

    def _io_open(self):
        sock = socket.create_connection((self.host, self.telnet_port), timeout=8)
        sock.settimeout(None)
        # TCP_NODELAY：小包（按键回显）立即发，交互不粘延迟
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self._io_handle = sock

    def _io_read_chunk(self):
        sock = self._io_handle
        if sock is None:
            # 句柄为 None = 重连失败后的空窗：抛异常把 reader 驱回重连退避循环，
            # 否则静默返回 b"" 会让 reader 空转、永不再重试（老 bug：断开后只报一次就死透）
            raise EOFError("Telnet 未连接")
        r, _, _ = select.select([sock], [], [], 0.2)
        if not r:
            return b""
        data = sock.recv(4096)
        if not data:
            raise EOFError("Telnet 对端关闭连接")
        return _handle_iac(sock, data)

    def _io_write(self, data: bytes):
        if self._io_handle is None:
            raise RuntimeError("Telnet 未连接")
        # 负载里的 255 必须转义为 IAC IAC（RFC 854）
        self._io_handle.sendall(data.replace(b"\xff", b"\xff\xff"))

    def _io_close(self):
        with self.lock:
            if self._io_handle:
                try:
                    self._io_handle.close()
                except Exception:
                    pass
                self._io_handle = None

    def _io_reconnect(self):
        """指数退避重连：1s/2s/4s... 上限 60s。手动 disconnect（alive=False）不重连。
        退避等待可被 _reconn_kick 中断（按 R 立即重试——与 SSH/基类语义一致）。"""
        self._reconnect_attempts += 1
        delay = min(2 ** self._reconnect_attempts, 60)
        self._reconn_kick.wait(delay)
        self._reconn_kick.clear()
        if not self.alive:
            return False
        try:
            self._io_close()
            if not self.alive:
                return False
            self._io_open()
            if not self.alive:
                self._io_close()
                return False
            self._reconnect_attempts = 0
            return True
        except Exception:
            return False
