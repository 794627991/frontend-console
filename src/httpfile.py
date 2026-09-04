# -*- coding: utf-8 -*-
"""HTTP 文件下载服务（纯标准库 http.server）+ Flask Blueprint 路由。

设备端用 wget/curl/hfs 协议从 PC 拉固件/配置——与 TFTP 同目录联动：
- 共享 TftpServer.root_dir（TFTP 切目录，HTTP 跟着切；反之亦然）
- 默认端口 8081；设备拉取 URL: http://<PC_IP>:8081/<文件名>
- 只读下载（GET/HEAD），无上传无删除——最小可用面
- 路径穿越防护：只允许 root_dir 下文件，URL 不带子目录（与 TFTP 同粒度）
"""
import os, threading, posixpath
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import unquote

from flask import Blueprint, request, jsonify

httpfile_bp = Blueprint("httpfile", __name__)

PORT = 8081  # 用户指定默认端口

class _Handler(BaseHTTPRequestHandler):
    """GET/HEAD：按 root_dir 服务文件。目录浏览（/ 或无扩展名 404 页）不支持。"""
    # tftp 单例注入（避免循环导入，启动时由本模块赋值）
    tftp = None

    def _serve(self, head_only=False):
        # URL 路径 → 文件名：去 /、unquote（%xx）、拒绝子目录与穿越
        raw = unquote(self.path.split("?")[0])
        name = posixpath.basename(raw.strip("/"))
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            self.send_error(403, "bad path")
            return
        root = self.tftp.root_dir if self.tftp else "."
        local = os.path.join(root, name)
        if not os.path.isfile(local):
            self.send_error(404, "file not found")
            return
        try:
            size = os.path.getsize(local)
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
            self.end_headers()
            if head_only:
                return
            with open(local, "rb") as f:
                while True:
                    chunk = f.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass  # 设备端中断（wget -c 断点/超时取消），正常现象
        except Exception as e:
            try: self.send_error(500, str(e))
            except Exception: pass

    def do_GET(self):
        self._serve(head_only=False)

    def do_HEAD(self):
        self._serve(head_only=True)

    def log_message(self, fmt, *args):
        pass  # 静默访问日志（不打进后端控制台）

class _ThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class HttpFileServer:
    """线程化 HTTP 下载服务，共享 TFTP 目录。默认 8081（用户指定），可改。"""
    def __init__(self, port=PORT):
        self.port = port
        self.running = False
        self.server = None

    def start(self, port=None):
        if self.running:
            return True, f"HTTP 下载已在运行，端口 {self.port}"
        # 允许自定义端口（默认 8081 被别的工具占用时——比如本机跑着 HFS 2.4）
        if port:
            try:
                port = int(port)
                if not (1 <= port <= 65535): raise ValueError
            except ValueError:
                return False, "端口号无效"
            self.port = port
        try:
            self.server = _ThreadingHTTPServer(("0.0.0.0", self.port), _Handler)
        except OSError as e:
            return False, f"端口 {self.port} 占用: {e}"
        self.running = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return True, f"HTTP 下载已启动，端口 {self.port}，目录随 TFTP"

    def stop(self):
        self.running = False
        if self.server:
            try: self.server.shutdown()
            except Exception: pass
            try: self.server.server_close()
            except Exception: pass
            self.server = None
        return True, "已停止"

    def status(self):
        # 目录/文件列表直接取 TFTP 单例（联动核心：一个数据源）
        root = _Handler.tftp.root_dir if _Handler.tftp else None
        return {"running": self.running, "port": self.port, "root_dir": root}

# 单例
_hfs = HttpFileServer()

@httpfile_bp.route("/api/httpfile/status")
def httpfile_status():
    return jsonify({"ok": True, **_hfs.status()})

@httpfile_bp.route("/api/httpfile/start", methods=["POST"])
def httpfile_start():
    """启动 HTTP 下载。body: {port?}（默认 8081，被占用时可传自定义端口）"""
    data = request.get_json(force=True, silent=True) or {}
    ok, msg = _hfs.start(data.get("port"))
    return jsonify({"ok": ok, "msg": msg, **_hfs.status()})

@httpfile_bp.route("/api/httpfile/stop", methods=["POST"])
def httpfile_stop():
    ok, msg = _hfs.stop()
    return jsonify({"ok": ok, "msg": msg, **_hfs.status()})
