# -*- coding: utf-8 -*-
"""HikLink 机器人积木（openclaw WS 协议）——独立插件，宿主零侵入。

协议逆向自 HiClaw 桌面端（与同事 ClaudeDesktop 同源）：
  1. SSO 登录   POST {moa}/moarestapi/login/pc/v2?pcUid=<uid>
                password = RSA_NO_PADDING(pcCode+'\\u200b'+明文) → base64
                pcCode   = sha256(hostname|cpu|arch|platform)
  2. 机器人注册 GET  {base}/moarestapi/robot/openclaw                列表
               POST {base}/moarestapi/robot/openclaw/create          创建
               GET  {base}/moarestapi/robot/openclaw/credential?...   取凭据
               base = hiklink-blue/red.hikvision.com（双集群）
  3. WS 长连    wss://hiklink-{blue/red}.hikvision.com/bot/gateway
               CLIENT_AUTH(appId=robot_num/appSecret) → SERVER_MSG_PUSH(msgJson)
               → CLIENT_MSG_PUSH 回复（1000 字/段，末段 finished=1）+ 心跳

与 harness 的接法（同进程直调）：固定会话收指令 → send_message → 完成后
分段推回；执行中新指令排队并立即回进度；/stop 终止当前任务。

凭据：优先复用 lanz_credentials.json（同一 SSO 账号体系），零配置直连；
    也可写 DATA_DIR/hiklink_session.json {"uid","password"} 覆盖。
宿主接入点仅 server.py 一行 import（模块导入即自动连接，失败静默不影响主工具）。
"""
import base64
import hashlib
import json
import logging
import os
import shutil
import ssl
import struct
import subprocess
import threading
import time
import uuid
import re
import zlib
from platform import architecture, node, system
from urllib.parse import urlencode
from urllib.request import ProxyHandler, build_opener, HTTPSHandler

from src.harness.lifecycle import _get_or_create
from src.harness.session import HarnessSession
from src.harness.consts import _sessions, _sessions_lock
from src.app_state import DATA_DIR

log = logging.getLogger("hiklink_bot")
# 文件日志：机器人链路排查全靠它（pythonw 无窗口，stdout 黑洞）
try:
    _fh = logging.FileHandler(os.path.join(DATA_DIR, "hiklink_bot.log"),
                              encoding="utf-8")
    _fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_fh)
    log.setLevel(logging.INFO)
except Exception:
    pass

# ---- 协议常量 ----
WS_BLUE = "wss://hiklink-blue.hikvision.com/bot/gateway"
WS_RED = "wss://hiklink-red.hikvision.com/bot/gateway"
MOAREST_BLUE = "https://hiklink-blue.hikvision.com"
MOAREST_RED = "https://hiklink-red.hikvision.com"
LOGIN_URL = "https://moa.hikvision.com/moarestapi/login/pc/v2"
RSA_PUB = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAwIxSPJ1umAW8Rx4d30QP\n"
    "OOtC6FlKLFMqCRndQDDI2p73qeAh0tPTR+6Zo2synM8JrLmwzxRFsgOgqzNH5MKc\n"
    "qXw+7bRchXT+WU1Fh1c7tIx7fDpJn2AyCHh4LdbSS/iiY5KKDn7LnvU4yV1OSLvF\n"
    "xY3eJs9Hsvw+SPmWChtIfrhn/8rExcPfVDyaPr0f42YSiHzSo/gCrltJj/Jv6wXP\n"
    "BlWKFHs+e++5GU9/WTv0Oe+hHJfXWf7b0Q/sNUsB2nSYgdVfFDcE8aUDQ8/ACsjI\n"
    "UQ5ND2N0SMJT2xo+rJrFiG4DUUrolKQqOLvFHOq9IwwejFVoNiCpyFIxBkIoLC6J\n"
    "qwIDAQAB\n"
    "-----END PUBLIC KEY-----")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36;"
      "name:HiClawPc;platform:win32;arch:x64;user:%s;")

SESSION_PATH = os.path.join(DATA_DIR, "hiklink_session.json")
WELCOME_TEXT = ("✦ 前端小助手已上线！直接发消息即可下达指令，"
                "回复会自动推回。/stop 停止当前任务。")
_SESSION_LOCK = threading.Lock()


def _load_session_file():
    """读 session 文件，主文件损坏自动回滚 .bak（写盘前总会留上一份）。"""
    for path in (SESSION_PATH, SESSION_PATH + ".bak"):
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict):
                if path != SESSION_PATH:
                    log.warning("主 session 文件损坏，已回退 .bak")
                return d
        except (ValueError, OSError):
            continue
    return {}


def _update_session_file(mutate):
    """SESSION_PATH 的原子读改写。多处（reader/任务/主线程）都要更新该文件，
    裸「读→改→写整文件」并发时会用旧内容洗掉别人刚写的字段；这里锁内完成
    且经 tmp+os.replace 落盘，读方永远看到完整新旧之一。"""
    with _SESSION_LOCK:
        try:
            d = {}
            if os.path.exists(SESSION_PATH):
                try:
                    with open(SESSION_PATH, encoding="utf-8") as f:
                        d = json.load(f) or {}
                except (ValueError, OSError):
                    d = _load_session_file()   # 主文件坏：从 .bak 接着改
            mutate(d)
            if os.path.exists(SESSION_PATH):   # 写前留底，损坏可回滚
                shutil.copy2(SESSION_PATH, SESSION_PATH + ".bak")
            tmp = SESSION_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f, ensure_ascii=False, indent=2)
            os.replace(tmp, SESSION_PATH)
            return True
        except Exception:
            return False
BOT_NAME = "前端小助手"   # 改名即新建机器人（旧机器人头像定死无法更新）
SEG = 1000          # 每段推送字符上限（HikLink 消息友好长度）
HEARTBEAT = 10      # 秒（实测服务端 ~20s 无有效心跳即断开，30s 档活不过首拍）
CMD_TIMEOUT = 1800  # 单条指令上限（秒）

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE
_opener = build_opener(ProxyHandler({}), HTTPSHandler(context=_ssl_ctx))


def _get_json(url, token=None):
    req = _opener.open(_mk_req(url, token, data=None), timeout=20)
    return json.loads(req.read().decode("utf-8", "replace"))


def _mk_req(url, token, data=None, headers=None):
    from urllib.request import Request
    h = {"User-Agent": UA % "", "Accept-Language": "zh-CN", "devicetype": "pc"}
    if token:
        h["Authorization"] = token
    if headers:
        h.update(headers)
    return Request(url, data=data, headers=h)


def _post_urlencoded(url, fields):
    data = urlencode(fields).encode()
    req = _mk_req(url, None, data=data,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    resp = _opener.open(req, timeout=20)
    return json.loads(resp.read().decode("utf-8", "replace"))


# ---- 设备指纹与密码加密（HiClaw getDeviceId 同款）-----------------------
def get_pc_code():
    try:
        cpu = subprocess.check_output(
            ["wmic", "cpu", "get", "name"], shell=False, timeout=5,
            stderr=subprocess.DEVNULL).decode(errors="ignore").strip()
        cpu = [l for l in cpu.splitlines() if l.strip() and "Name" not in l]
        cpu = cpu[0].strip() if cpu else "CPU"
    except Exception:
        cpu = "CPU"
    raw = "|".join([node() or "PC", cpu, (architecture()[0] or ""), system()])
    return hashlib.sha256(raw.encode()).hexdigest()


def encrypt_password(pc_code, password):
    """RSA_NO_PADDING(pcCode+'\\u200b'+明文) → base64（256 字节右对齐）。
    分隔符 U+200B 必须按 UTF-8（3 字节 E2 80 8B）参与加密——HiClaw 原实现
    是 Buffer.from(str)（UTF-8）；此前 encode("ascii","ignore") 把它丢了，
    密文与服务端期望不符 → 登录恒报「请求参数不正常」。"""
    from Crypto.PublicKey import RSA
    from Crypto.Util.number import bytes_to_long, long_to_bytes
    key = RSA.import_key(RSA_PUB)
    raw = (pc_code + "​" + password).encode("utf-8")
    m = bytes_to_long(raw)
    sig = pow(m, key.e, key.n)
    out = long_to_bytes(sig, 256)
    return base64.b64encode(out).decode()


def login_pc(uid, password):
    """HikLink PC 登录，返回 (token, msg)。"""
    try:
        pc = get_pc_code()
        resp = _post_urlencoded(
            LOGIN_URL + "?pcUid=" + uid,
            {"uid": uid, "password": encrypt_password(pc, password),
             "pcCode": pc, "deviceType": "pc", "needAutoLogin": "true",
             "rsaVer": "V2209"})
    except Exception as e:
        return None, "登录请求失败（需内网）: %s" % e
    if resp.get("errcode") not in (0, "0", None):
        return None, "登录失败: %s" % resp.get("errmsg")
    token = (resp.get("data") or {}).get("token")
    if not token:
        return None, "登录响应缺 token"
    return token, "已登录 %s" % uid


# ---- 机器人注册（openclaw）----------------------------------------------
def _png_1px():
    """1x1 灰 PNG（注册机器人的图标兜底）。"""
    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\x80\x80")) + chunk(b"IEND", b""))


def _icon_png():
    """app 图标 → 256px PNG（机器人头像用真身，接口只收 image/png）。"""
    try:
        import io
        from PIL import Image
        ico_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ico")
        for name in ("app.png", "app.ico"):   # png 免转换最快；ico 兜底
            p = os.path.join(ico_dir, name)
            if not os.path.isfile(p):
                continue
            img = Image.open(p).convert("RGBA")
            img.thumbnail((256, 256), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
    except Exception as e:
        log.warning("头像加载失败，退回占位图: %s", e)
    return _png_1px()


def ensure_robot(token, name=BOT_NAME):
    """确保存在本工具专用机器人（HiClaw 的机器人被它独占，不能用）。
    v2.27.9：同名多机器人时按 slogan 优先匹配——账号里常有 ClaudeDesktop
    建的同名「前端小助手」（slogan 不同），旧的名字优先匹配会把别家工具的
    机器人抢来连（用户实锤：来回换账号测试后连上 ClaudeDesktop 的机器人，
    KICK_OUT 互踢 + 消息收不到），本工具 slogan = 前端控制台远程指令通道。
    返回 (robot_num, app_secret, msg)。"""
    bases = [MOAREST_BLUE, MOAREST_RED]
    last_err = ""

    def _pick(robots):
        same = [r for r in robots if (r.get("name") or "") == name]
        if not same:
            return None
        for r in same:            # 第一优先：本工具建的（slogan 相同）
            if (r.get("slogan") or "") == "前端控制台远程指令通道":
                return r
        return same[0]            # 兜底：同名第一台（老账号兼容）

    for base in bases:
        try:
            lst = _get_json(base + "/moarestapi/robot/openclaw", token=token)
            robots = (lst.get("data") or [])
            if isinstance(robots, dict):
                robots = robots.get("list") or robots.get("records") or []
            mine = _pick(robots)
            if mine is None:
                # v2.27.14：头像创建后改不了（平台无更新接口）——图标加载失败
                # 时【拒绝创建】并明确报错，而不是建出个永远默认头像的机器人
                # （用户定调：别人设备上要一次推对，没有试错机会）。修好图标
                # 重试即可，此时什么都没建，零损失。
                png = _icon_png()
                if png == _png_1px():
                    return (None, None,
                            "机器人图标加载失败，已拒绝创建（头像创建后无法修改）——"
                            "请检查 ico/app.png 是否随包分发后重试")
                boundary = uuid.uuid4().hex
                parts = []
                for field, val in (("name", name), ("slogan", "前端控制台远程指令通道")):
                    parts.append(("--%s\r\nContent-Disposition: form-data; "
                                  "name=\"%s\"\r\n\r\n%s" % (boundary, field, val)))
                parts.append(("--%s\r\nContent-Disposition: form-data; name=\"file\"; "
                              "filename=\"icon.png\"\r\nContent-Type: image/png\r\n\r\n"
                              % boundary))
                # multipart 拼接：file 头之后紧跟字节流，最后才收边界——
                # 此前误把 png 拼在结束边界之后，服务端收到的请求没有文件，
                # 头像永远是默认灰图（图标改动"不生效"的根因）
                body = "\r\n".join(parts).encode() + png \
                    + ("\r\n--%s--\r\n" % boundary).encode()
                from urllib.request import Request
                req = _mk_req(base + "/moarestapi/robot/openclaw/create", token,
                              data=body, headers={
                                  "Content-Type": "multipart/form-data; boundary=%s" % boundary})
                resp = _opener.open(req, timeout=20)
                json.loads(resp.read().decode("utf-8", "replace"))
                lst = _get_json(base + "/moarestapi/robot/openclaw", token=token)
                robots = (lst.get("data") or [])
                if isinstance(robots, dict):
                    robots = robots.get("list") or robots.get("records") or []
                mine = _pick(robots)
            if mine is None:
                last_err = "机器人注册后未出现在列表中"
                continue
            num = mine.get("robotNum") or mine.get("robot_num")
            cred = _get_json(base + "/moarestapi/robot/openclaw/credential?robotNum=%s"
                             % num, token=token)
            cd = cred.get("data") or {}
            secret = cd.get("appSecret") or cd.get("app_secret")
            if not (num and secret):
                last_err = "拿凭据失败: %s" % str(cred)[:120]
                continue
            return num, secret, "机器人 %s 就绪" % num
        except Exception as e:
            last_err = str(e)
    return None, None, last_err or "未发现可用的机器人"


# ---- WS 客户端 -----------------------------------------------------------
try:
    import websocket
    HAS_WS = True
except ImportError:
    HAS_WS = False


class HikLinkBot:
    """HikLink 机器人 WS 客户端。
    bot.on_command = lambda text, trans_id: ...   # 收到指令回调
    bot.start() / bot.reply(text) / bot.stop()"""

    def __init__(self, robot_num, app_secret):
        self.robot_num = robot_num
        self.app_secret = app_secret
        self.ws_url = WS_BLUE
        self.ws = None
        self.session_id = None
        self.authenticated = False
        self.connected = False
        self.welcome_text = None
        self.on_command = None
        self.on_auth_failed = None   # 认证被拒（凭据失效）→ 上层自愈回调
        self.send_heartbeat = True   # False=不发心跳（诊断用）
        self._announced = False      # 上线通告进程内只推一次，防重连刷屏
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.Lock()
        self._last_trans = set()

    def _trans(self):
        return str(uuid.uuid4())

    def _send(self, obj):
        with self._lock:
            if self.ws is not None:
                try:
                    self.ws.send(json.dumps(obj, ensure_ascii=False))
                    return True
                except Exception:
                    pass
        return False

    def start(self):
        if not HAS_WS:
            return False, "websocket-client 未安装"
        if self._thread and self._thread.is_alive():
            return False, "已在运行"
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="hiklink-bot-ws")
        self._thread.start()
        return True, "已启动"

    def stop(self):
        self._stop.set()
        with self._lock:
            try:
                if self.ws is not None:
                    self.ws.close()
            except Exception:
                pass
        self.connected = False
        self.authenticated = False
        return True, "已停止"

    def _run(self):
        """连接 → 认证 → 收帧。断线/被踢自动重连（退避 3~30s）——
        同 robot 多实例会互踢（KICK_OUT），对方退出后重连即恢复。"""
        backoff = 3
        while not self._stop.is_set():
            connected = False
            for url in (WS_BLUE, WS_RED):
                if self._stop.is_set():
                    return
                try:
                    self.ws_url = url
                    self.ws = websocket.create_connection(
                        url, timeout=5,
                        sslopt={"cert_reqs": ssl.CERT_NONE},
                        header=["User-Agent: " + (UA % "")])
                    self.connected = True
                    connected = True
                    log.info("WS 已连接 %s", url)
                    break
                except Exception as e:
                    log.warning("WS 连接失败 %s: %s", url, e)
            if not connected:
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 3
            self._send({"appId": self.robot_num, "cmd": "CLIENT_AUTH",
                        "transId": self._trans(), "version": "1.0",
                        "appSecret": self.app_secret})
            threading.Thread(target=self._heartbeat, daemon=True).start()
            self.ws.settimeout(5)
            last_frame = None
            while not self._stop.is_set():
                try:
                    frame = self.ws.recv()
                    if not frame:
                        log.warning("WS 空帧断开")
                        break
                    last_frame = frame
                    self._handle(json.loads(frame))
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception as e:
                    log.warning("WS 断开（最后帧: %s）: %s",
                                (last_frame or "")[:200], e)
                    break
            self.connected = False
            self.authenticated = False
            if self._stop.is_set():
                return
            self._stop.wait(backoff)   # 断线/被踢 → 退避后重连

    def _heartbeat(self):
        while not self._stop.is_set() and self.connected and self.send_heartbeat:
            self._send({"appId": self.robot_num, "cmd": "HEART_PING",
                        "transId": self._trans(), "version": "1.0"})
            time.sleep(HEARTBEAT)

    def _save_last_session(self):
        """持久化最近活跃 session——重启后上线通告靠它找回会话上下文。"""
        cur = self.session_id

        def mutate(d):
            if d.get("last_session") != cur:
                d["last_session"] = cur

        _update_session_file(mutate)

    def _announce_online(self):
        """上线通告：复用上次活跃 session 推一条，重启后让会话「活」过来。
        实测无 session 的推送服务端 SYSTEM_ACK 但静默不投递（回复语义），
        且用户把会话关掉后连旧 session 也投不进——那种情况只能靠用户在
        HikLink 里重新发消息拉起会话，通告做不到无中生有。"""
        self._stop.wait(3)   # 错开认证瞬间，也给服务端留就绪时间
        if (self._stop.is_set() or self._announced or not self.authenticated):
            return
        if self.session_id:   # 本次已收到过消息，会话本来就在，无需通告
            return
        last = _load_session_file().get("last_session")
        if not last:
            log.info("上线通告跳过：无历史 session（用户首次发消息后建立会话）")
            return
        # v2.27.13：通告只推给当前登录账号自己的会话——换账号测试会把
        # last_session 留成上一个人（实测推给了同事 heqinglong5，本人收不到
        # 上线通知还以为通知坏了）。session 标识以 uid 起头，按前缀判归属。
        try:
            cur_uid = (_load_session_file().get("uid")
                       or (_controller._creds()[0] if _controller else "")) or ""
        except Exception:
            cur_uid = ""
        if cur_uid and not str(last).lower().startswith(str(cur_uid).lower()):
            log.info("上线通告跳过：历史 session 属于别的账号（%s… ≠ 当前 %s）",
                     str(last)[:8], cur_uid)
            return
        self._announced = True
        self.session_id = last
        self.push("前端控制台机器人已上线 ✅")
        log.info("上线通告已推（复用历史 session %s…）", str(last)[:8])

    def _handle(self, msg):
        cmd = msg.get("cmd")
        if cmd == "SERVER_AUTH_REPLY":
            self.authenticated = bool(msg.get("result"))
            log.info("WS 认证%s（uid=%s）", "成功" if self.authenticated else "失败",
                     msg.get("uid"))
            if self.authenticated:
                threading.Thread(target=self._announce_online,
                                 daemon=True).start()
            elif self.on_auth_failed:
                # 凭据失效（机器人被删/secret 轮换）——不处理就永久僵死
                threading.Thread(target=self.on_auth_failed,
                                 daemon=True).start()
        elif cmd == "HEART_PONG":
            pass
        elif cmd == "KICK_OUT":
            # 实测这是服务器的广播通知（appId 为空，有人上线/下线时推送），
            # 不是踢本连接——此前误判为被踢而主动断连重连，重连又触发下一轮
            # 广播，形成自激振荡（每 20-40s 假掉线一次）。连接仍活着，继续收帧。
            log.info("KICK_OUT 广播（忽略，连接保持）")
        elif cmd == "SERVER_MSG_PUSH":
            try:
                mj = msg.get("msgJson")
                data = json.loads(mj) if isinstance(mj, str) else (mj or {})
            except Exception:
                data = {}
            text = (data.get("asrText") or "").strip()
            # a239（第5轮B2-P1C）：发送者鉴权——此前任何能给机器人发消息的
            # HikLink 用户都可驱动本机 Claude 会话（文本直进 stdin，ask 桥还可
            # 替答确认）。session 标识以 uid 起头（_announce_online 同款判据），
            # 非本人会话一律拒绝并回执
            _sess = str(msg.get("session") or "")
            try:
                _cur_uid = (_load_session_file().get("uid")
                            or (_controller._creds()[0] if _controller else "")) or ""
            except Exception:
                _cur_uid = ""
            if _cur_uid and _sess and not _sess.lower().startswith(_cur_uid.lower()):
                log.warning("拒绝非机主会话消息: session=%s sender=%s",
                            _sess[:10], data.get("sender"))
                try:
                    self.session_id = _sess   # 回执要投回该会话才可见
                    self.reply("⚠ 该机器人仅响应机主（%s）本人的指令" % _cur_uid)
                except Exception:
                    pass
                return
            self.session_id = msg.get("session") or self.session_id
            self._save_last_session()
            log.info("收到消息: sender=%s text=%r", data.get("sender"),
                     text[:80])
            if not text and self.welcome_text:
                self.reply(self.welcome_text)
                return
            trans_id = msg.get("transId") or self._trans()
            if trans_id in self._last_trans:
                return
            self._last_trans.add(trans_id)
            if len(self._last_trans) > 200:
                self._last_trans = set(list(self._last_trans)[-100:])
            if self.on_command:
                try:
                    self.on_command(text, trans_id)
                except Exception:
                    log.exception("指令处理异常")

    def reply(self, text, finished=1):
        """回复文本到 HikLink（CLIENT_MSG_PUSH，SEG 字/段，失败重试必达）。
        帧结构照同事实现逐字段还原：业务体 JSON 序列化后放 **msgJson**（字符串）
        ——此前错放 body 对象字段，服务器不解析该字段，send 成功也被静默丢弃
        （用户实锤「推送成功但 HikLink 收不到」）。"""
        text = text or ""
        chunks = [text[i:i + SEG] for i in range(0, len(text), SEG)] or [""]
        for i, seg_text in enumerate(chunks):
            last = (i == len(chunks) - 1)
            payload = {
                "code": 0,
                "data": {"qaReply": {"credibleQa": {
                    "id": "robot%d" % int(time.time() * 1000),
                    "answerList": [{"type": "text", "text": seg_text}]}}},
                "msg": "SUCCESS"}
            frame = {
                "appId": self.robot_num, "cmd": "CLIENT_MSG_PUSH",
                "finished": 1 if (last and finished) else 0,
                "msgJson": json.dumps(payload, ensure_ascii=False),
                "msgType": "DEFAULT",
                "transId": self._trans(), "version": "1.2.0",
                "session": self.session_id}
            for attempt in range(8):
                if self._send(frame):
                    log.info("回复已推送(%d/%d 段, 尝试 %d)", i + 1, len(chunks),
                             attempt + 1)
                    break
                log.warning("回复推送失败(段 %d, 尝试 %d),3s 后重试", i + 1,
                            attempt + 1)
                time.sleep(3)
            time.sleep(0.15)

    def push(self, text):
        """进度推送：单次发送不重试（丢一条进度无伤大雅，不能因它阻塞
        事件轮询——最终回复才走带重试的 reply）。"""
        payload = {
            "code": 0,
            "data": {"qaReply": {"credibleQa": {
                "id": "robot%d" % int(time.time() * 1000),
                "answerList": [{"type": "text", "text": (text or "")[:SEG]}]}}},
            "msg": "SUCCESS"}
        frame = {"appId": self.robot_num, "cmd": "CLIENT_MSG_PUSH",
                 "finished": 0, "msgJson": json.dumps(payload, ensure_ascii=False),
                 "msgType": "DEFAULT", "transId": self._trans(),
                 "version": "1.2.0", "session": self.session_id}
        self._send(frame)

    def status(self):
        return {"running": bool(self._thread and self._thread.is_alive()),
                "connected": self.connected, "authenticated": self.authenticated,
                "robot_num": self.robot_num, "session_id": self.session_id}


# ---- 控制器：接 harness 会话 --------------------------------------------
_HIS = None


def _his():
    """同事 ClaudeDesktop 的 hiklink_bot 模块（marshal 字节码资产）。
    登录加密/设备指纹等细节以他生产验证过的实现为准——自研还原在密码
    加密处有细微差异（服务器 90000），直接复用其字节码最稳。"""
    global _HIS
    if _HIS is None:
        import marshal
        import types
        blob = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "_hiklink_his.blob"), "rb").read()
        code = marshal.loads(zlib.decompress(blob))
        _HIS = types.ModuleType("his_hiklink_bot")
        exec(code, _HIS.__dict__)
    return _HIS


class HikLinkBotController:
    """指令入口 → 固定 harness 会话执行 → 分段回推。
    任务执行中新指令排队并立即回进度；/stop 终止当前任务。
    ask_user 选择卡片桥接：问题推 HikLink 编号作答（手机端可决策）。"""

    def __init__(self, emit_log=None):
        self.bot = None
        self._lock = threading.Lock()
        self._queue = []
        self._busy_hl = False
        self._t0 = 0.0
        self._emit_log = emit_log or (lambda m: log.info(m))
        self._sid = None
        self._load_sid()
        self._pending_ask = None   # {"req_id", "qmap"} —— 待手机作答的选择卡片

    # ---- ask_user 选择卡片桥接 ----
    @staticmethod
    def _format_ask(evt):
        """harness ask 事件 → (推送文本, qmap)。
        qmap: {"题号": (问题原文, [(选项号, label)...])}——编号作答依据。"""
        qs = evt.get("questions") or []
        title = (evt.get("title") or "").strip()
        lines = ["❓ " + (title or "需要你确认")]
        qmap = {}
        for qi, q in enumerate(qs, 1):
            if not isinstance(q, dict):
                continue
            qtext = (q.get("question") or ("问题%d" % qi)).strip()
            opts = q.get("options") or []
            lines.append("%d. %s" % (qi, qtext))
            omap = []
            for oi, o in enumerate(opts, 1):
                label = (o.get("label") if isinstance(o, dict) else str(o)) or ""
                if not label:
                    continue
                lines.append("   %d=%s" % (oi, label))
                omap.append((oi, label))
            if q.get("multiSelect"):
                lines.append("   （本题可多选：多个选项号用逗号分隔，如「2,3」即选第2、3项）")
            if omap:
                qmap[str(qi)] = (qtext, omap)
        lines.append("—— 请按编号作答：单题直接回选项号（如「2」）；多题写「题号=选项号」用;隔开（如「1=2;2=1,3」）；也可直接发选项文字")
        return "\n".join(lines), qmap

    @staticmethod
    def _parse_ask_answer(text, qmap):
        """把 HikLink 文本回复解析成 ask_answer 的 {问题原文: "label[, label]"}。
        支持：标准「1=2;2=1,3」；单题纯数字「2」；直接发选项文字（包含匹配）。
        返回 (answer dict or None, 错误说明)。"""
        text = (text or "").strip()
        if not text:
            return None, "回复为空"
        if len(qmap) == 1 and text.isdigit():
            qtext, omap = list(qmap.values())[0]
            hit = next((l for n, l in omap if n == int(text)), None)
            return ({qtext: hit}, None) if hit else (None, "选项 %s 不存在" % text)
        for qtext, omap in qmap.values():
            for _, label in omap:
                if text == label or (len(text) >= 2 and text in label):
                    return {qtext: label}, None
        ans = {}
        for part in re.split(r"[;；\n]+", text):
            part = part.strip()
            if not part:
                continue
            m = re.match(r"^(\d+)\s*[=：:—-]\s*(.+)$", part)
            if not m:
                return None, "看不懂「%s」——格式如 1=2" % part[:30]
            qi, ov = m.group(1), m.group(2)
            ent = qmap.get(qi)
            if not ent:
                return None, "题号 %s 不存在" % qi
            qtext, omap = ent
            labels = []
            for piece in re.split(r"[,，、]+", ov):
                piece = piece.strip()
                if not piece:
                    continue
                hit = None
                if piece.isdigit():
                    hit = next((l for n, l in omap if n == int(piece)), None)
                else:
                    hit = next((l for _, l in omap if piece in l), None)
                if not hit:
                    return None, "题%s的「%s」不是有效选项" % (qi, piece[:20])
                labels.append(hit)
            ans[qtext] = ", ".join(labels)
        if not ans:
            return None, "未解析出任何作答"
        return ans, None

    # ---- 凭据 ----
    def _creds(self, uid=None, password=None):
        if uid and password:
            return uid, password
        d = _load_session_file()
        if d.get("uid") and d.get("password"):
            return d["uid"], d["password"]
        if d.get("uid") and not password:
            uid = d["uid"]
        # 复用 lanz SSO 凭据（同一账号体系）
        try:
            from src.lanz_quota import load_credentials
            cred = load_credentials(os.path.join(DATA_DIR, "lanz_credentials.json"))
            if cred:
                return cred["username"], cred["password"]
        except Exception:
            pass
        return (uid or None), (password or None)

    # ---- 会话 ----
    def _load_sid(self):
        self._sid = _load_session_file().get("harness_sid")

    def _save_sid(self):
        cur = self._sid

        def mutate(d):
            d["harness_sid"] = cur

        _update_session_file(mutate)

    def _session(self):
        """取/复用小助理专属会话。跨进程也能复用：测试进程/工具重启后内存
        会话表是空的——_get_or_create 会从磁盘元数据重建（--resume 续上下文），
        之前每条消息新建一个会话（用户实锤列表十几个小助理）就是缺了这步。"""
        s = None
        if self._sid:
            s = _get_or_create(self._sid)
        if s is not None:
            if not s.alive:
                s.revive_if_dead()
            if s.alive:
                return s
        new_sid = uuid.uuid4().hex
        s = HarnessSession(new_sid, cwd=os.path.expanduser("~"),
                              title="前端小助手（HikLink）")
        try:
            s.start()
        except Exception as e:
            log.error("HikLink harness 会话启动失败: %s", e)
            return None
        s.sync_meta()
        with _sessions_lock:
            _sessions[new_sid] = s
        self._sid = new_sid
        self._save_sid()
        return s

    # ---- 生命周期 ----
    def start(self, uid=None, password=None, welcome=None):
        """启动机器人。v2.27.8：串行化 + 双检——登录接口（credentials save）
        与前端的 /hiklink/activate 会几乎同时各调一次 ensure_started()，而
        SSO 登录要几十秒，旧实现无锁：第二次进来时第一个还没连上（running
        False），又走完整登录注册 → 两个 HikLinkBot 连同一机器人互踢
        KICK_OUT 死循环（2026-09-16 用户实锤，13s 周期完美匹配）。"""
        with self._lock:
            if getattr(self, "_starting", False):
                return False, "已在启动中（登录/注册进行中）"
            if self.bot and self.bot.status().get("running"):
                return False, "已在运行"
            self._starting = True
        try:
            return self._start_locked(uid, password, welcome)
        finally:
            with self._lock:
                self._starting = False

    def _start_locked(self, uid, password, welcome):
        if not HAS_WS:
            return False, "机器人模块缺失（websocket-client 未安装）"
        u, p = self._creds(uid, password)
        if not (u and p):
            return False, "需要 SSO 账号密码（首次配置写 hiklink_session.json）"
        # 已有机器人凭据 → 直接连；否则登录 + 注册（登录/注册用同事实现）
        d = _load_session_file()
        num, secret = d.get("robot_num"), d.get("app_secret")
        if num and secret and d.get("robot_name") != BOT_NAME:
            # 缓存凭据属于旧名字的机器人（改名重建场景）→ 作废，按新名重注册
            log.info("缓存凭据是旧机器人（%s ≠ %s），重新注册",
                     d.get("robot_name"), BOT_NAME)
            num = secret = None
        if num and secret and d.get("robot_uid") not in (None, u):
            # v2.27.7：机器人凭据是账号私有的——缓存属于别的账号（换人登录）
            # → 作废重注册，否则拿别人的机器人连 WS（用户实锤）
            log.info("缓存机器人凭据属于账号 %s（当前 %s），重新注册",
                     d.get("robot_uid"), u)
            num = secret = None
        if not (num and secret):
            try:
                his = _his()
                token, msg = his.login_pc(u, p)
                if not token:
                    return False, msg
                num, secret, msg2 = ensure_robot(token, name=BOT_NAME)
                if not (num and secret):
                    return False, msg2 or "机器人注册失败"
                fresh = {"uid": u, "password": p, "robot_uid": u, "robot_num": num,
                         "app_secret": secret, "robot_name": BOT_NAME}

                def mutate(d):
                    d.update(fresh)

                _update_session_file(mutate)
            except Exception as e:
                return False, "登录/注册失败: %s" % e
        # v2.27.8：换新 bot 前先停旧的并清孤儿——历史上任何竞态起过多余
        # bot（同机器人互踢元凶），这里兜底全部收掉，保证进程内机器人唯一
        with self._lock:
            old = self.bot
            self.bot = None
        if old:
            try:
                old.stop()
            except Exception:
                pass
        self.bot = HikLinkBot(num, secret)
        self.bot.welcome_text = welcome or WELCOME_TEXT
        self.bot.on_command = self._on_command
        self.bot.on_auth_failed = self._on_auth_failed
        ok, msg3 = self.bot.start()
        if ok:
            self._emit_log("HikLink 机器人已连接（%s）" % num)
        return ok, msg3

    def _on_auth_failed(self):
        """WS 认证被拒：凭据失效（机器人被删/secret 轮换）。自动登录 →
        ensure_robot 同名找回（被删则按名重建，带蓝头像）→ 换新凭据重连。
        10 分钟防抖，防止服务端反复拒绝时形成风暴。"""
        now = time.time()
        if now - getattr(self, "_last_refresh", 0) < 600:
            log.info("凭据刷新防抖中（10 分钟内已试过），跳过")
            return
        self._last_refresh = now
        log.warning("WS 认证被拒，尝试凭据自愈…")
        u, p = self._creds()
        if not (u and p):
            log.error("无 SSO 凭据，无法自愈")
            return
        try:
            his = _his()
            token, msg = his.login_pc(u, p)
            if not token:
                log.error("自愈登录失败: %s", msg)
                return
            num, secret, msg2 = ensure_robot(token, name=BOT_NAME)
            if not (num and secret):
                log.error("自愈注册失败: %s", msg2)
                return
            fresh = {"uid": u, "password": p, "robot_num": num,
                     "app_secret": secret, "robot_name": BOT_NAME}

            def mutate(d):
                d.update(fresh)

            _update_session_file(mutate)
        except Exception:
            log.exception("凭据自愈异常")
            return
        if self.bot:
            self.bot.stop()
        self.bot = HikLinkBot(num, secret)
        self.bot.welcome_text = WELCOME_TEXT
        self.bot.on_command = self._on_command
        self.bot.on_auth_failed = self._on_auth_failed
        ok, msg3 = self.bot.start()
        self._emit_log("凭据自愈%s（%s）" % ("成功" if ok else "失败", num))

    def stop(self):
        if self.bot:
            return self.bot.stop()
        return True, "机器人未在运行"

    def status(self):
        return self.bot.status() if self.bot else {"running": False}

    # ---- 指令处理 ----
    def _on_command(self, text, trans_id):
        if not text:
            return
        # 待答选择卡片在场：本条消息优先作为答案提交（不进任务队列）——
        # 手机端无法点桌面 UI 的选择卡片，编号/选项文字作答即回传
        if self._pending_ask:
            pa = self._pending_ask
            ans, err = self._parse_ask_answer(text, pa["qmap"])
            if ans is None:
                self.bot.reply("⚠ %s\n重发格式：1=选项号（多选 1=2,3）" % err)
                return
            s = self._session()
            if s and s.ask_answer(pa["req_id"], ans):
                self._pending_ask = None
                self.bot.reply("✓ 已提交：" + "; ".join(
                    "%s → %s" % (k[:24], v[:60]) for k, v in ans.items()))
            else:
                self._pending_ask = None
                self.bot.reply("该提问已失效（可能桌面端已作答），原话将按新指令处理")
            return
        with self._lock:
            if self._busy_hl:
                self._queue.append(text)
                self.bot.reply("⏳ 当前有任务在跑（已 %ds），这条已排队：%s"
                               % (int(time.time() - self._t0), text[:80]))
                return
            self._busy_hl = True
        threading.Thread(target=self._run_cmd, args=(text,), daemon=True).start()

    def _run_cmd(self, text):
        try:
            if text.strip() == "/stop":
                s = self._session()
                if s:
                    s.stop()
                self.bot.reply("⏹ 任务已停止")
                return
            s = self._session()
            if s is None:
                self.bot.reply("会话启动失败，请稍后再试")
                return
            seq0 = s._seq
            cursor = seq0
            self._t0 = time.time()
            self.bot.reply("已收到，开始处理：%s" % text[:80])
            ok, err = s.send_message(text)
            if not ok:
                # v3.5.123：busy 拒发（大回合保活期）→ 入服务端队列回「已排队」，
                # 不再回「发送失败」（用户口径：子代理在飞也算回合内，消息排队）
                if err and "正在回复" in err:
                    try:
                        s.queue_admit(text=text)
                        self.bot.reply("⏳ 当前大回合未结束，已排队，完成后自动执行")
                        return
                    except Exception:
                        pass
                self.bot.reply("消息发送失败: %s" % (err or ""))
                return
            # v2.27.15：超窗自动续命——send_message 内部已把旧历史注入新会话并
            # 紧接着发出用户本条（两个 turn）。seq0 是注入前的位点，注入轮的
            # result 会把 _saw_result 提前打满，旧逻辑会把注入轮当最终回复推
            # 空文本。这里重置基准点：只等用户本条 turn 的 result。
            if getattr(s, "renewed_at", None) and s.renewed_at > seq0:
                seq0 = s.renewed_at
                cursor = seq0
            # claude 进程偶发退出时 reader_loop 把 busy/alive 拉成 False 且
            # 无任何事件——上一条就是被这个吞成「(AI 没有返回文本回复)」的。
            # 探测到进程已死：复活（resume 续上下文）并重发一次。
            if not s.alive:
                log.warning("发送后进程已死，复活重发: %r", text[:50])
                if not s.revive_if_dead():
                    self.bot.reply("会话进程退出且复活失败，请重发")
                    return
                ok, err = s.send_message(text)
                if not ok:
                    self.bot.reply("消息发送失败: %s" % (err or ""))
                    return
            # 等待完成：**只认 result 帧（turn 终止帧）**，不信任 busy——
            # busy 是 reader 对 result 的下游缓存，时序竞态（迟到/进程退出）
            # 会让它提前翻转，把中间文本当最终回复或推空。文本只是候选，
            # 看到 result 才敲定；等待中进程死了就复活重发一次。
            deadline = time.time() + CMD_TIMEOUT
            last_push = 0.0
            answer = ""
            while time.time() < deadline:
                time.sleep(2)
                now = time.time()
                try:
                    for e in s.get_events_after(cursor):
                        cursor = e.get("seq", cursor)
                        k = e.get("kind")
                        if k == "ask":
                            text_, qmap = self._format_ask(e)
                            self._pending_ask = {"req_id": e.get("req_id"),
                                                 "qmap": qmap}
                            self.bot.reply(text_)
                            last_push = time.time()
                            continue
                        if k == "ask_done":
                            self._pending_ask = None
                            continue
                        if k != "event":
                            continue
                        d = e.get("data") or {}
                        if d.get("type") != "tool_use":
                            continue
                        if now - last_push >= 5:
                            self.bot.push("🔧 " + self._tool_brief(d))
                            last_push = now
                except Exception:
                    pass
                answer = self._last_assistant(s, seq0)
                if self._saw_result(s, seq0):
                    break       # result = turn 终止帧，此刻最后文本即最终回复
                if not s.alive and not answer:
                    log.warning("等待中进程死亡，复活重发: %r", text[:50])
                    if not s.revive_if_dead():
                        break
                    ok, err = s.send_message(text)
                    if not ok:
                        log.warning("复活重发失败: %s", err)
                        break
            self.bot.reply(answer or "（AI 没有返回文本回复）")
        except Exception as e:
            log.exception("指令执行失败")
            try:
                self.bot.reply("处理出错: %s" % e)
            except Exception:
                pass
        finally:
            with self._lock:
                self._busy_hl = False
                nxt = self._queue.pop(0) if self._queue else None
            if nxt:
                self._on_command(nxt, self.bot._trans())

    @staticmethod
    def _saw_result(s, after_seq):
        """after_seq 之后是否已出现 result 帧（turn 的终止标志）。
        v3.5.123（用户口径「子代理在飞不许结束大回合」）：hold 期的中间
        result 不算完——bg_in_flight 为真时继续等（手机不收半截答案）。"""
        try:
            for e in s.get_events_after(after_seq):
                if e.get("kind") == "event" \
                        and (e.get("data") or {}).get("type") == "result":
                    try:
                        if s.bg_in_flight():
                            continue   # hold：后台子代理还在跑，回合未终
                    except Exception:
                        pass
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def _tool_brief(d):
        """工具调用的单行摘要（推给 HikLink 好读）。"""
        name = d.get("name") or "工具"
        inp = d.get("input") or {}
        for k in ("command", "file_path", "path", "pattern", "url", "query",
                  "description", "prompt"):
            v = inp.get(k)
            if v:
                return "%s: %s" % (name, str(v)[:70].replace("\n", " "))
        return name

    @staticmethod
    def _last_assistant(s, after_seq):
        """after_seq 之后最后一条非空 assistant 文本（stream-json 解析，前端同源）。"""
        out = ""
        try:
            for e in s.get_events_after(after_seq):
                if e.get("kind") != "event":
                    continue
                d = e.get("data") or {}
                if d.get("type") != "assistant":
                    continue
                for blk in (d.get("message") or {}).get("content") or []:
                    if isinstance(blk, dict) and blk.get("type") == "text" \
                            and (blk.get("text") or "").strip():
                        out = blk["text"].strip()
        except Exception:
            pass
        return out


_controller = None


def _autostart():
    """模块导入即尝试自动连接（有凭据才启；失败静默不影响主工具）。"""
    global _controller
    try:
        _controller = HikLinkBotController()
        u, p = _controller._creds()
        if u and p:
            def _go():
                ok, msg = _controller.start()
                log.info("HikLink 机器人自启: %s", msg if not ok else "OK")
            threading.Thread(target=_go, daemon=True).start()
    except Exception:
        log.exception("HikLink 机器人初始化失败")


def controller():
    return _controller


def ensure_started():
    """统一登录后激活机器人（幂等）：有统一凭据才起，运行中直接返回。
    未登录（无凭据）→ 明确不激活——机器人与登录绑定。"""
    global _controller
    if _controller is None:
        _controller = HikLinkBotController()
    u, p = _controller._creds()
    if not (u and p):
        return False, "未登录（无统一凭据），机器人不激活"
    if _controller.status().get("running"):
        return True, "机器人已在运行"
    return _controller.start()


def ensure_stopped():
    """登出时停用机器人（幂等）——登录与机器人绑定，登出即停。"""
    if _controller and _controller.bot:
        return _controller.stop()
    return True, "机器人未在运行"


def clear_account():
    """登出清账号相关凭据（v2.27.6）：uid/password 不清则状态接口继续报
    「已登录」藏起登录表单（用户实锤）；robot_num/app_secret 不清则换
    账号登录时直接拿旧账号的机器人连 WS——机器人身份跟人走（用户实锤：
    同事登录自己的号，机器人还是别人的）。机器人凭据清了无损失：下次
    登录 ensure_robot 按账号列同名机器人自动找回。只保留 harness_sid
    （小助理会话绑定，丢了会另起新会话）。"""
    def mutate(d):
        for k in ("uid", "password", "robot_num", "app_secret", "robot_name"):
            d.pop(k, None)
    return _update_session_file(mutate)


def status_snapshot():
    """统一登录 UI 的状态聚合：登录名 + 机器人运行态。"""
    username = None
    st = {}
    if _controller:
        username, _ = _controller._creds()
        if _controller.bot:
            st = _controller.bot.status()
    return {"username": username, "running": bool(st.get("running")),
            "connected": bool(st.get("connected")),
            "robot_num": st.get("robot_num")}


_autostart()
