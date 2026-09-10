# -*- coding: utf-8 -*-
"""物理串口连接。IO 层用 pyserial。"""
import serial
import serial.tools.list_ports

from .base_conn import BaseConnection

class SerialPort(BaseConnection):
    """物理串口连接。IO 层用 pyserial。"""
    kind = "serial"

    def __init__(self, port, baud, port_id):
        super().__init__(port_id)
        self.port = port
        self.baud = baud
        self.ser = None
        self.start()

    def _io_open(self):
        # timeout=0.02：读到数据立即返回，读循环以小块高频轮询 + 读尽 in_waiting，
        # 吞吐时合并为大 chunk 推 SSE，减少前端 term.write 次数（输入卡顿主因之一）
        self.ser = serial.Serial(self.port, int(self.baud), timeout=0.02)
        self._io_handle = self.ser

    def _io_read_chunk(self):
        with self.lock:
            s = self.ser
        if s is None:
            # 句柄为 None = 重连失败后的空窗：抛异常把 reader 驱回重连退避循环，
            # 否则静默返回 b"" 会让 reader 空转、永不再重试（老 bug：拔线后只报一次就死透）
            raise EOFError("串口未打开")
        with self.lock:
            # 读尽当前缓冲（in_waiting 字节）——一次循环拿到尽可能多的数据，
            # 高吞吐时合并成大块一次推 SSE（减少前端 term.write 次数，输入卡顿主因之一）。
            # in_waiting 为 0 直接返回 b""，空转节奏由 _reader_loop 的 sleep(0.05) 控制；
            # read 只在 in_waiting>0 时调用，立即返回，不依赖 Serial timeout
            n = s.in_waiting
            if not n:
                return b""
            chunk = s.read(n)
        return chunk or b""

    def _io_write(self, data: bytes):
        with self.lock:
            if self.ser is None: raise RuntimeError("串口未连接")
            self.ser.write(data)

    def _io_close(self):
        with self.lock:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
                self.ser = None

    def _io_reconnect(self):
        with self.lock:
            if self.ser:
                try: self.ser.close()
                except Exception: pass
            self.ser = serial.Serial(self.port, self.baud, timeout=0.02)  # 与 _io_open 一致
        return True


def list_ports():
    ports = []
    for p in serial.tools.list_ports.comports():
        ports.append({"device": p.device, "description": p.description, "hwid": p.hwid})
    return ports
