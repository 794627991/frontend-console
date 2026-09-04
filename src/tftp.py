# -*- coding: utf-8 -*-
"""TFTP 服务器（RFC 1350，纯标准库实现）+ Flask Blueprint 路由。
BSP 调试常用：设备端 tftp 命令从 PC 拉固件/配置（下载），或推日志/抓包（上传）。
"""
import os, time, threading, socket, struct

from flask import Blueprint, request, jsonify

tftp_bp = Blueprint("tftp", __name__)

class TftpTransfer:
    """一次传输的会话状态。"""
    def __init__(self, kind, filename, peer):
        self.kind = kind          # 'get'(设备下载) / 'put'(设备上传)
        self.filename = filename
        self.peer = peer          # (ip, port)
        self.bytes_done = 0
        self.total = None         # get 时为文件大小
        self.status = "running"   # running / done / error
        self.err = ""
        self.started_at = time.time()
        self.via = "tftp"         # 传输来源：tftp / hfs（HTTP 下载复用本类）

class TftpServer:
    """线程化 TFTP 服务器。监听 UDP 69，每个传输在独立线程用独立数据端口收发。

    - RRQ（设备读 = 设备下载文件）：从 root_dir 读文件发给设备
    - WRQ（设备写 = 设备上传文件）：收设备数据写入 root_dir
    - 仅支持 octet（二进制）模式——嵌入式设备 tftp 客户端默认都是 octet
    - 超时重传 + 最终放弃；blksize 协商（RFC 2348）取设备请求值（默认 512）
    """
    def __init__(self):
        self.root_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        self.running = False
        self.sock = None
        self.transfers = []       # 最近传输列表（新→旧）
        self._lock = threading.Lock()

    # ---- 生命周期 ----
    def start(self, root_dir=None):
        if root_dir:
            ok, msg = self.set_dir(root_dir)
            if not ok:
                return False, msg
        if self.running:
            return True, "已在运行"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", 69))
        except OSError as e:
            return False, f"端口 69 占用或无权限: {e}"
        self.sock = s
        self.running = True
        threading.Thread(target=self._serve, daemon=True).start()
        return True, f"TFTP 已启动，目录: {self.root_dir}"

    def stop(self):
        self.running = False
        if self.sock:
            try: self.sock.close()
            except Exception: pass
            self.sock = None
        return True, "已停止"

    def set_dir(self, path):
        """切换 TFTP 根目录（运行中也可切）。
        容错：strip 空格、去首尾引号（手输常见）、末尾反斜杠规范化。"""
        path = (path or "").strip().strip('"').strip("'")
        if not path:
            return False, "目录不能为空"
        # 绝对路径规范化（末尾反斜杠）；相对路径原样交 isdir 判断，避免误拼 cwd 掩盖错误
        if os.path.isabs(path):
            path = os.path.normpath(path)
        if not os.path.isdir(path):
            return False, f"目录不存在: {path}"
        self.root_dir = path
        return True, path

    def status(self):
        with self._lock:
            return {
                "running": self.running,
                "root_dir": self.root_dir,
                "files": self._list_files(),
                "transfers": [{
                    "kind": t.kind, "filename": t.filename, "peer": "%s:%s" % t.peer,
                    "bytes": t.bytes_done, "total": t.total,
                    "status": t.status, "err": t.err, "via": getattr(t, "via", "tftp"),
                    "elapsed": round(time.time() - t.started_at, 1),
                } for t in self.transfers[:20]],
            }

    def _list_files(self):
        """root_dir 下的文件列表（供前端/MCP 预览可传输内容）。"""
        try:
            out = []
            for fn in sorted(os.listdir(self.root_dir)):
                fp = os.path.join(self.root_dir, fn)
                if os.path.isfile(fp):
                    st = os.stat(fp)
                    out.append({"name": fn, "size": st.st_size, "mtime": int(st.st_mtime)})
            return out[:200]
        except Exception:
            return []

    # ---- 协议 ----
    OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 2, 3, 4, 5, 6

    def _serve(self):
        """主循环：监听 69 端口的 RRQ/WRQ，为每个请求起独立传输线程。"""
        while self.running:
            try:
                data, peer = self.sock.recvfrom(2048)
            except OSError:
                break  # sock 被 stop() 关闭
            try:
                self._handle_request(data, peer)
            except Exception:
                pass

    def _handle_request(self, data, peer):
        if len(data) < 4:
            return
        opcode = struct.unpack("!H", data[:2])[0]
        if opcode not in (self.OP_RRQ, self.OP_WRQ):
            return
        # 解析 filename\0mode\0[option\0value\0...]
        parts = data[2:].split(b"\0")
        filename = parts[0].decode("utf-8", "replace") if parts else ""
        mode = parts[1].decode("ascii", "lower") if len(parts) > 1 else ""
        if mode and mode != "octet":
            self._send_err(self.sock, peer, 0, "only octet supported")
            return
        # RFC 2348/2349 选项协商：blksize（块大小）、tsize（文件大小）。
        # 关键：带选项的请求必须回 OACK（opcode=6）确认协商值，否则 RFC 2348 客户端
        # 会 fallback 到默认 512，而服务端却按协商值切割 → 块大小错位 → 中途协议崩溃。
        # （tftpy 等成熟实现：只要请求带选项就必发 OACK，绝不偷偷改 blksize 不告知。）
        blksize = 512
        want_oack = False  # 请求带了任何选项就需 OACK
        tsize_val = None   # tsize 协商值（RRQ 时填文件大小）
        i = 2
        while i + 1 < len(parts):
            opt = parts[i].lower()
            val = parts[i+1]
            if opt == b"blksize":
                try:
                    blksize = min(max(int(val), 8), 65464)
                    want_oack = True
                except ValueError: pass
            elif opt == b"tsize":
                want_oack = True  # tsize 也需 OACK 回应
            i += 2
        # 防路径穿越：只允许 root_dir 下的直接文件名
        if not filename or os.path.basename(filename) != filename or filename in (".", ".."):
            self._send_err(self.sock, peer, 1, "bad filename")
            return
        local = os.path.join(self.root_dir, filename)
        if opcode == self.OP_RRQ:
            if not os.path.isfile(local):
                self._send_err(self.sock, peer, 1, "file not found")
                return
            # 去重：同文件 + 同设备 IP 的 RRQ 若已有传输在跑，是客户端超时重发 RRQ
            # （标准重传行为），不新建记录/线程，避免一次下载出现 N 条 error 记录。
            with self._lock:
                for ex in self.transfers:
                    if ex.kind == "get" and ex.filename == filename \
                       and ex.peer[0] == peer[0] and ex.status == "running":
                        return  # 已有传输在跑，忽略重发 RRQ
            t = TftpTransfer("get", filename, peer)
            t.total = os.path.getsize(local)
            with self._lock: self.transfers.insert(0, t)
            threading.Thread(target=self._send_file,
                args=(local, t, blksize, want_oack), daemon=True).start()
        else:  # WRQ
            with self._lock:
                for ex in self.transfers:
                    if ex.kind == "put" and ex.filename == filename \
                       and ex.peer[0] == peer[0] and ex.status == "running":
                        return
            t = TftpTransfer("put", filename, peer)
            with self._lock: self.transfers.insert(0, t)
            threading.Thread(target=self._recv_file,
                args=(local, t, blksize, want_oack), daemon=True).start()

    def _send_file(self, path, t, blksize, want_oack):
        """RRQ：把文件分块发给设备，等 ACK。

        协议要点（对照 tftpy / RFC 1350）：
        1. 设备 RRQ 带选项时先发 OACK，设备回 ACK(0) 后才开始发 DATA；
           不发 OACK 直接用协商 blksize 会让 RFC 2348 客户端 fallback 到 512，
           块大小错位 → 中途协议崩溃（大文件传到几 MB 卡死的根因）。
        2. 文件恰为 blksize 整数倍时，最后补发一个 0 字节 DATA 作为终止块，
           等其 ACK 才算 done（RFC 1350 强制；否则 PC 自判 done，设备死等）。
        3. 超时放弃前发 ERROR 包，让设备立即 abort 而非死等 100s+。
        4. 陈旧/重复 ACK（block 不匹配）静默丢弃继续等，只有真正 timeout 才计重传。
        """
        ds = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ds.settimeout(3.0)  # 3s（tftpy 5s×3 对嵌入式太松，1s 太紧，3s×5 折中）
        try:
            with open(path, "rb") as f:
                payload = f.read()
            block = 1
            off = 0
            # ---- OACK 握手：设备带选项时先确认协商值，设备回 ACK(0) 再传 DATA ----
            if want_oack:
                oack = struct.pack("!H", self.OP_OACK) + \
                       b"blksize\0" + str(blksize).encode() + b"\0" + \
                       b"tsize\0" + str(t.total).encode() + b"\0"
                retries = 0
                ds.sendto(oack, t.peer)
                while True:
                    try:
                        resp, _ = ds.recvfrom(65536)
                    except socket.timeout:
                        retries += 1
                        if retries > 5:
                            self._send_err(ds, t.peer, 0, "OACK 超时无响应")
                            t.status = "error"; t.err = "设备端 OACK 无响应"
                            return
                        ds.sendto(oack, t.peer)
                        continue
                    if len(resp) >= 4 and struct.unpack("!H", resp[:2])[0] == self.OP_ACK \
                       and struct.unpack("!H", resp[2:4])[0] == 0:
                        break  # 设备确认 OACK，开始传 DATA
                    # 陈旧包静默丢弃
            # ---- 传数据块 ----
            while off < t.total or (off == 0 and block == 1):  # 空文件也发一个块
                chunk = payload[off:off + blksize]
                pkt = struct.pack("!HH", self.OP_DATA, block) + chunk
                retries = 0
                ds.sendto(pkt, t.peer)
                while True:  # 等当前 block 的 ACK
                    try:
                        resp, _ = ds.recvfrom(65536)
                    except socket.timeout:
                        retries += 1
                        if retries > 5:
                            self._send_err(ds, t.peer, 0, "设备端超时无响应")
                            t.status = "error"; t.err = "设备端超时无响应"
                            return
                        ds.sendto(pkt, t.peer)  # 超时才重传
                        continue
                    if len(resp) >= 4 and struct.unpack("!H", resp[:2])[0] == self.OP_ACK \
                       and struct.unpack("!H", resp[2:4])[0] == block:
                        break  # 正确 ACK，进下一块
                    # 陈旧/重复 ACK：静默丢弃继续等，不计重传
                off += len(chunk)
                t.bytes_done = off
                block = (block + 1) & 0xFFFF
                if len(chunk) < blksize:  # 最后一块（短块）已发并 ACK，完成
                    break
            # ---- 整数倍文件：补发 0 字节终止块，等其 ACK 才算真完成 ----
            if off >= t.total and (t.total % blksize == 0) and t.total > 0:
                term_pkt = struct.pack("!HH", self.OP_DATA, block)  # 0 字节数据
                retries = 0
                ds.sendto(term_pkt, t.peer)
                while True:
                    try:
                        resp, _ = ds.recvfrom(65536)
                    except socket.timeout:
                        retries += 1
                        if retries > 5:
                            self._send_err(ds, t.peer, 0, "终止块超时无响应")
                            t.status = "error"; t.err = "终止块未确认"
                            return
                        ds.sendto(term_pkt, t.peer)
                        continue
                    if len(resp) >= 4 and struct.unpack("!H", resp[:2])[0] == self.OP_ACK \
                       and struct.unpack("!H", resp[2:4])[0] == block:
                        break
            t.status = "done"
        except Exception as e:
            t.status = "error"; t.err = str(e)
        finally:
            ds.close()

    def _recv_file(self, path, t, blksize, want_oack):
        """WRQ：收设备数据写入文件。
        设备带选项时先发 OACK（设备回 ACK(0) 后开始发 DATA），否则回 ACK(0) 起步。
        最后一块判定 len(data) < blksize 即终止（RFC 1350 正确，短块/空块即终止）。
        超时放弃前发 ERROR，让设备立即 abort 而非死等。"""
        ds = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ds.settimeout(3.0)
        try:
            # ---- OACK 握手：设备带选项时确认协商值，设备回 ACK(0) 后才发 DATA ----
            if want_oack:
                oack = struct.pack("!H", self.OP_OACK) + \
                       b"blksize\0" + str(blksize).encode() + b"\0" + \
                       b"tsize\0" + b"0\0"  # WRQ 时未知文件大小，tsize 回 0
                ds.sendto(oack, t.peer)
                # 等设备 ACK(0) 或 DATA(1)（部分实现 OACK 后直接发 DATA）
                retries = 0
                first_pkt = None
                while True:
                    try:
                        first_pkt, _ = ds.recvfrom(65536)
                        break
                    except socket.timeout:
                        retries += 1
                        if retries > 5:
                            self._send_err(ds, t.peer, 0, "OACK 超时无响应")
                            t.status = "error"; t.err = "设备端 OACK 无响应"
                            return
                        ds.sendto(oack, t.peer)
            else:
                ds.sendto(struct.pack("!HH", self.OP_ACK, 0), t.peer)
            block = 1
            tmp = path + ".tftp.part"
            with open(tmp, "wb") as f:
                # 若 OACK 后设备直接发了 DATA(1)，先处理首包
                if first_pkt is not None:
                    _process = True  # 下面循环会先消费 first_pkt
                while True:
                    if first_pkt is not None:
                        resp = first_pkt; first_pkt = None
                    else:
                        retries = 0
                        while True:
                            try:
                                resp, _ = ds.recvfrom(65536)
                                break
                            except socket.timeout:
                                retries += 1
                                if retries > 5:
                                    self._send_err(ds, t.peer, 0, "设备端超时无响应")
                                    t.status = "error"; t.err = "设备端超时无响应"
                                    return
                                # 重发上一 ACK 触发设备重传当前块
                                ds.sendto(struct.pack("!HH", self.OP_ACK, (block - 1) & 0xFFFF), t.peer)
                                continue
                    if len(resp) < 4:
                        continue
                    op, blk = struct.unpack("!HH", resp[:4])
                    if op == self.OP_ERROR:
                        t.status = "error"; t.err = resp[4:].decode("utf-8", "replace")
                        return
                    if op != self.OP_DATA:
                        continue  # 非 DATA 包（含 OACK 回声等）静默丢弃
                    if blk == (block - 1) & 0xFFFF:
                        # 重复块（我方 ACK 丢了设备重传）：重发 ACK，不写文件，继续等
                        ds.sendto(struct.pack("!HH", self.OP_ACK, (block - 1) & 0xFFFF), t.peer)
                        continue
                    if blk != block:
                        continue  # 陈旧/未来块：静默丢弃继续等
                    f.write(resp[4:])
                    t.bytes_done += len(resp) - 4
                    ds.sendto(struct.pack("!HH", self.OP_ACK, block), t.peer)
                    if len(resp) - 4 < blksize:  # 最后一块（短块/空块即终止）
                        break
                    block = (block + 1) & 0xFFFF
            os.replace(tmp, path)  # 原子替换，避免半截文件
            t.status = "done"
        except Exception as e:
            t.status = "error"; t.err = str(e)
            try: os.remove(path + ".tftp.part")
            except OSError: pass
        finally:
            ds.close()

    def _send_err(self, sock, peer, code, msg):
        try:
            sock.sendto(struct.pack("!HH", self.OP_ERROR, code) + msg.encode("utf-8"), peer)
        except Exception:
            pass

# 单例（路由共享）
_tftp = TftpServer()

@tftp_bp.route("/api/tftp/status")
def tftp_status():
    """TFTP 状态：运行中/目录/文件列表/最近传输。"""
    return jsonify({"ok": True, **_tftp.status()})

@tftp_bp.route("/api/tftp/start", methods=["POST"])
def tftp_start():
    """启动 TFTP。body: {root_dir?}"""
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = _tftp.start(data.get("root_dir"))
    return jsonify({"ok": ok, "msg": msg, **_tftp.status()})

@tftp_bp.route("/api/tftp/stop", methods=["POST"])
def tftp_stop():
    ok, msg = _tftp.stop()
    return jsonify({"ok": ok, "msg": msg, **_tftp.status()})

@tftp_bp.route("/api/tftp/set_dir", methods=["POST"])
def tftp_set_dir():
    """切换 TFTP 目录。body: {root_dir}"""
    data = request.get_json(force=True, silent=True) or {}
    path = (data.get("root_dir") or "").strip()
    if not path:
        return jsonify({"ok": False, "err": "need root_dir"}), 400
    ok, msg = _tftp.set_dir(path)
    return jsonify({"ok": ok, "msg": msg, **_tftp.status()} if ok else {"ok": False, "err": msg})
