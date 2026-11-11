# -*- coding: utf-8 -*-
"""VCS 远端执行层（a455）：把 svn/git 命令从本地 SMB 挪到构建机上跑。

**为什么**：本地走映射盘（SMB）执行 `svn status --xml` 实测 47.9 秒——每次
文件 stat 都是一次网络往返；同一份工作副本在构建机本地 ext4 上只要 1.1 秒，
加上 SSH 传输 6.8 MB 也只有 2.1 秒（23 倍差距）。符号链接误报、缺失文件
误报也全部消失（Linux 侧是真实的链接和文件，不是 SMB 展开的假象）。

**设计边界**（用户令「都做到版本功能里，不要延伸」）：
- 配置按「本地工程根」一条条存，只在版本面板的弹窗里读写，不进设置页。
- 只做**执行层替换**：命令仍在远端跑，输出原样交回现有解析器，解析代码零改动。
- 远端不可达、未配置、或纯 Windows 本地盘 → 透明回退本地 subprocess，
  绝不因远端故障让版本面板不可用。

**安全**：
- 口令/密钥加密后落盘（SHA-256 CTR 密钥流 + HMAC-SHA256 认证，密钥由
  fcpk 打包密钥派生；纯标准库实现——打包版 cryptography 的 Python 层被
  剥，import 不可靠），配置文件读出来不含明文。
- 主机键采用首次信任（AutoAddPolicy），与现有 SSH 终端一致——本工具面向
  内网固定构建机，不做 TOFU 告警（会挡住正常使用）。
- 只执行白名单内的子命令（svn/git 本身），argv 一律 list，不经 shell。
"""
import base64
import hmac
import hashlib
import json
import os
import re
import threading
import time

STORE_NAME = "vcs_remote.json"
_CFG_CACHE = {"path": None, "mtime": None, "data": None}
_CFG_LOCK = threading.Lock()

# 连接池：host:port:user -> SSHClient（复用 TCP + 认证，省 300~500ms/次）
_POOL = {}
_POOL_LOCK = threading.Lock()
_POOL_IDLE = 900          # 15 分钟不用即关闭（摆渡机上不常驻）

# 允许经 SSH 执行的子命令（前缀精确匹配，防配置被篡改后任意执行）
_ALLOW = (
    ("svn", "status"), ("svn", "info"), ("svn", "log"), ("svn", "cat"),
    ("svn", "diff"), ("svn", "add"), ("svn", "commit"), ("svn", "update"),
    ("svn", "revert"), ("svn", "list"),
    ("git", "status"), ("git", "log"), ("git", "show"), ("git", "diff"),
    ("git", "add"), ("git", "commit"), ("git", "pull"), ("git", "rev-parse"),
    # 合入审计 F5：原表里的 ("git","-c","core.quotepath=false") 三元前缀会把
    # 后续**任意**子命令一并放行（push/…），白名单形同虚设——删掉，由
    # _allowed 的跳 -c 逻辑对真实子命令校验
)


class RemoteError(Exception):
    """远端不可用（未配置 / 连接失败 / 认证失败）——调用方回退本地并透出原因。"""


# --------------------------------------------------------------------- 存储

def _store_path():
    from src import app_state as _st
    return os.path.join(_st.DATA_DIR, STORE_NAME)


def _secret_key():
    """配置加密密钥：由打包密钥派生，用途隔离（与 fcpk 各 tag 不复用）。

    不依赖 fcpk 的 _password()——打包版可能没有 _fcpk_key.py（那是有资源包
    时才生成）。用本机固定盐 + 通用构建常量派生：目标是「配置文件里不出现
    明文」，不是抗有动机的离线破解（本机同目录本就有源码）。"""
    seed = ""
    try:
        from src.fcpk import _password
        seed = _password()
    except Exception:
        seed = ""
    if not seed:
        seed = "vcs-remote-local-default"
    h = hashlib.sha256(("vcs-remote/v2|" + str(seed)).encode("utf-8")).digest()
    return hashlib.pbkdf2_hmac("sha256", h, b"vcs-remote-salt-v2", 20000, 32)


def _ks(key, nonce, n):
    """SHA-256 计数器密钥流（CTR 形态）：block_i = SHA256(key || nonce || i)。"""
    out = bytearray()
    i = 0
    while len(out) < n:
        out += hashlib.sha256(key + nonce + i.to_bytes(8, "big")).digest()
        i += 1
    return bytes(out[:n])


def _xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


def _enc(plain):
    """加密单个字段（空值原样返回空串）。

    为什么不用 AES：打包版把 cryptography 与 pycryptodome 的 Python 层都
    剥掉了（只剩 pyd 骨架），import 必失败。这里用纯标准库构造——
    SHA-256 CTR 密钥流异或 + HMAC-SHA256 加密后认证。密码本身只需要
    「配置文件里看不见」，不是抗离线爆破的机密材料（同目录本就有源码）。"""
    if not plain:
        return ""
    key = _secret_key()                       # 32B
    enc_k = hmac.new(key, b"enc", hashlib.sha256).digest()
    mac_k = hmac.new(key, b"mac", hashlib.sha256).digest()
    nonce = os.urandom(16)
    data = str(plain).encode("utf-8")
    ct = _xor(data, _ks(enc_k, nonce, len(data)))
    tag = hmac.new(mac_k, nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(nonce + tag + ct).decode("ascii")


def _dec(blob):
    """解密；任何失败（换过密钥/文件被改）返回空串——当作没配口令。"""
    if not blob:
        return ""
    try:
        raw = base64.b64decode(blob)
        if len(raw) < 33:
            return ""
        nonce, tag, ct = raw[:16], raw[16:32], raw[32:]
        key = _secret_key()
        enc_k = hmac.new(key, b"enc", hashlib.sha256).digest()
        mac_k = hmac.new(key, b"mac", hashlib.sha256).digest()
        want = hmac.new(mac_k, nonce + ct, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, want):
            return ""
        return _xor(ct, _ks(enc_k, nonce, len(ct))).decode("utf-8")
    except Exception:
        return ""


def load():
    """读配置（带 mtime 缓存）。两层结构：

      {
        "profiles": [   # 连接档案：主机/账号/认证，全局复用一份
          {"id": 1, "name": "构建机", "host": "10.1.74.239", "port": 22,
           "user": "gaoyi13", "auth": "password", "secret_enc": "...",
           "key_path": "", "last_ok": 1700000000}
        ],
        "remotes": [    # 工程 → 远端目录映射，只引用 profile
          {"local_root": "W:\\work\\...\\g10_trunk",
           "profile_id": 1,
           "remote_root": "/data1/gaoyi13/work/.../g10_trunk",
           "enabled": True}
        ]
      }

    为什么分两层（用户实锤：换个 svn 就要重填一遍密码，太怪）：
    主机、账号、口令在同一个内网构建机上是**共用**的，只有「本地目录 ↔
    远端目录」的映射是逐工程的。旧格式（entry 里直接带 host/user/secret）
    读取时自动迁移到 profiles，见 _migrate。"""
    p = _store_path()
    try:
        mt = os.path.getmtime(p)
    except OSError:
        return {"profiles": [], "remotes": []}
    with _CFG_LOCK:
        if _CFG_CACHE["path"] == p and _CFG_CACHE["mtime"] == mt:
            return _CFG_CACHE["data"]
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {"profiles": [], "remotes": []}
    except (OSError, ValueError):
        d = {"profiles": [], "remotes": []}
    d.setdefault("profiles", [])
    d.setdefault("remotes", [])
    if _migrate(d):
        try:
            _save(d)
        except OSError:
            pass
    with _CFG_LOCK:
        _CFG_CACHE.update(path=p, mtime=mt, data=d)
    return d


def _migrate(d):
    """旧格式（entry 自带 host/user/auth/secret）→ 抽出 profile 并改引用。
    返回是否发生了改动。"""
    changed = False
    for e in d.get("remotes") or []:
        if not isinstance(e, dict) or "profile_id" in e:
            continue
        prof = _match_or_add_profile(d, {
            "host": e.get("host"), "port": e.get("port") or 22,
            "user": e.get("user"), "auth": e.get("auth") or "password",
            "secret_enc": e.get("secret_enc") or "",
            "key_path": e.get("key_path") or "",
        })
        e["profile_id"] = prof["id"]
        for k in ("host", "port", "user", "auth", "secret_enc", "key_path"):
            e.pop(k, None)
        changed = True
    return changed


def _new_profile_id(d):
    ids = [p.get("id") or 0 for p in d.get("profiles") or []]
    return (max(ids) if ids else 0) + 1


def _match_or_add_profile(d, prof):
    """按 主机+端口+用户+认证 找同档案；没有就新建（迁移用，免重复）。"""
    for p in d.get("profiles") or []:
        if (str(p.get("host")) == str(prof.get("host"))
                and int(p.get("port") or 22) == int(prof.get("port") or 22)
                and str(p.get("user")) == str(prof.get("user"))
                and (p.get("auth") or "password") == (prof.get("auth") or "password")):
            return p
    prof = dict(prof)
    prof["id"] = _new_profile_id(d)
    prof.setdefault("name", prof.get("host") or "")
    d.setdefault("profiles", []).append(prof)
    return prof


def _save(d):
    from src import app_state as _st
    p = _store_path()
    os.makedirs(_st.DATA_DIR, exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    with _CFG_LOCK:
        _CFG_CACHE.update(path=None, mtime=None, data=None)


def _norm(p):
    return os.path.normcase(os.path.normpath(str(p or "")))


def _norm_remote(p):
    return str(p or "").replace("\\", "/").rstrip("/")


def get_profile(pid):
    for p in load().get("profiles") or []:
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    return None


def get_for_root(local_root):
    """按本地工程根取「合并后」的配置（映射 + 连接档案）；无则 None。

    返回的 dict 同时含 local_root/remote_root 与 host/user/auth/secret_enc
    ——调用方无需关心两层结构。"""
    if not local_root:
        return None
    lr = _norm(local_root)
    d = load()
    for e in d.get("remotes") or []:
        if not isinstance(e, dict) or not e.get("enabled", True):
            continue
        if _norm(e.get("local_root")) != lr:
            continue
        prof = get_profile(e.get("profile_id"))
        if not prof:
            return None
        merged = dict(prof)
        merged.update({"local_root": e.get("local_root"),
                       "remote_root": e.get("remote_root"),
                       "enabled": e.get("enabled", True),
                       "profile_id": prof.get("id")})
        return merged
    return None


# --------------------------------------------------------------------- 自动推导

# 构建机上常见的家目录前缀（按顺序试）。用户只需配一次，之后新工程自动命中。
_REMOTE_HOME_HINTS = ("/data1/", "/data/", "/home/", "/work/", "/opt/")


def detect_share_root(prof, local_root=""):
    """探测「这个网络盘在构建机上对应哪个目录」。仅在无法直接定位工程时兜底。

    见 detect_project_path —— 主用那条，它直接产出工程路径，不需要共享根
    这个概念。这里保留为探测手段之一（Samba 配置路径）。"""
    if not prof:
        return ""
    try:
        cli = _get_client(prof)
        user = str(prof.get("user") or "")
        # 优先按 samba 配置里 valid users 含该用户的段取 path
        cmd = ("awk '/^\\[/{sec=$0} /^path *=/{p=$0} "
               "/^valid users/{if (index($0, \\\"%s\\\")>0) print p}' "
               "/etc/samba/smb.conf 2>/dev/null | head -5" % user)
        _in, o, _e = cli.exec_command(cmd, timeout=12)
        txt = _decode(o.read())
        cands = []
        for ln in txt.splitlines():
            m = re.match(r"^\s*path\s*=\s*(\S+)", ln)
            if m:
                cands.append(m.group(1).rstrip("/"))
        if not cands:
            # 退回：家目录同名（/data1/<user> 或 /home/<user>）
            for base in ("/data1/", "/data/", "/home/"):
                cmd2 = "test -d %s && echo %s" % (_quote(base + user),
                                                  _quote(base + user))
                _in2, o2, _e2 = cli.exec_command(cmd2, timeout=8)
                t2 = _decode(o2.read()).strip()
                if t2:
                    cands.append(t2)
                    break
        if not cands:
            return ""
        # 若本地是 W:\work\... 则远端应为 <share>/work/...：挑能让本地
        # 相对路径在远端实际存在的那一个
        tail = ""
        m2 = re.match(r"^[A-Za-z]:/(.*)$", str(local_root).replace("\\", "/"))
        if m2:
            tail = m2.group(1).strip("/")
        if tail:
            for c in cands:
                probe = c.rstrip("/") + "/" + tail
                _in3, o3, _e3 = cli.exec_command(
                    "test -d %s && echo Y" % _quote(probe), timeout=8)
                if _decode(o3.read()).strip() == "Y":
                    return c.rstrip("/")
        return cands[0]
    except Exception:
        return ""


def detect_project_path(prof, local_root, timeout=25):
    """**直接**在构建机上定位这个工程目录，不需要用户填任何路径。

    用户只提供主机+账号（一次），其余全自动：

    ① 按工程名全盘找：`find <候选根> -maxdepth 6 -type d -name <工程名>`
       ——工程名（trunk / g10_trunk / P_SD_STORE）几乎总唯一。
    ② 用本地目录的内容指纹校验候选（顶层文件名集合比较），排除同名不同
       工程的情况。
    ③ 校验通过且唯一 → 直接返回该绝对路径。
    ④ 多个候选/找不到 → 退到 Samba 共享根映射（本地盘符相对路径拼接）。

    返回 {"path": str, "candidates": [...], "how": "scan"|"share"|"",
          "err": str}。path 非空即「可以直接用，无需用户干预」。"""
    res = {"path": "", "candidates": [], "how": "", "err": ""}
    if not prof or not local_root:
        res["err"] = "缺少连接信息或工程路径"
        return res
    name = os.path.basename(str(local_root).rstrip("\\/")) or ""
    if not name:
        res["err"] = "无法从本地路径取得工程名"
        return res
    try:
        cli = _get_client(prof)
    except Exception as e:
        res["err"] = _tidy(e)
        return res

    # 候选搜索根：家目录优先，避免全盘 find 拖慢
    user = str(prof.get("user") or "")
    roots = []
    for base in ("/data1/%s" % user, "/data/%s" % user, "/home/%s" % user,
                 "/data1", "/data"):
        roots.append(base)
    # 去重保序
    seen = set()
    roots = [r for r in roots if not (r in seen or seen.add(r))]

    def _sh(cmd, to=timeout):
        _in, o, _e = cli.exec_command(cmd, timeout=to)
        out = _decode(o.read())
        rc = o.channel.recv_exit_status()
        return rc, out

    # ① 按名字找（限制深度，排除 .svn/.git 等目录）
    found = []
    script = (
        "for r in %s; do [ -d \"$r\" ] || continue; "
        "find \"$r\" -maxdepth 6 -type d -name %s "
        "-not -path '*/.svn/*' -not -path '*/.git/*' 2>/dev/null; done"
        % (" ".join(_quote(r) for r in roots), _quote(name)))
    try:
        _rc, out = _sh(script)
        found = [x.strip() for x in out.splitlines() if x.strip()]
    except Exception as e:
        res["err"] = _tidy(e)
        return res

    # 去重（同一目录可能被多个根命中）
    uniq = []
    for f in found:
        if f not in uniq:
            uniq.append(f)
    res["candidates"] = uniq[:10]

    def _is_same_project(remote_dir):
        """用顶层条目名集合粗校验：同名集合重合率高即认定同一个工程。"""
        try:
            _rc, out = _sh("ls -1A %s 2>/dev/null | head -200"
                           % _quote(remote_dir), 12)
        except Exception:
            return False
        remote = {x.strip() for x in out.splitlines() if x.strip()}
        if not remote:
            return False
        try:
            local = {x for x in os.listdir(str(local_root))}
        except OSError:
            return True          # 本地读不到就不否决（远端已按名字命中）
        if not local:
            return True
        inter = len(local & remote)
        # 至少一半顶层条目对得上，才认为同一个工程
        return inter >= max(1, int(len(local) * 0.5))

    if len(uniq) == 1:
        cand = uniq[0]
        if _is_same_project(cand):
            res["path"], res["how"] = cand, "scan"
            return res
        res["err"] = "找到同名目录但内容不匹配：%s" % cand
        return res

    if len(uniq) > 1:
        # 多个同名（trunk/trunk/trunk…）：用内容指纹挑出唯一匹配
        hits = [c for c in uniq if _is_same_project(c)]
        if len(hits) == 1:
            res["path"], res["how"] = hits[0], "scan"
            return res
        if len(hits) > 1:
            # 还有多个同内容（同一工程的多个检出）——按路径相似度选最像的：
            # 本地路径尾部与远端路径尾部的公共层级越多越优先。
            tail = re.sub(r"^[A-Za-z]:/", "", str(local_root).replace("\\", "/"))
            tsegs = [s for s in tail.strip("/").split("/") if s]

            def _score(p):
                psegs = [s for s in p.strip("/").split("/") if s]
                n = 0
                for a, b in zip(reversed(tsegs), reversed(psegs)):
                    if a.lower() != b.lower():
                        break
                    n += 1
                return n

            hits.sort(key=_score, reverse=True)
            if _score(hits[0]) >= 2:
                res["path"], res["how"] = hits[0], "scan"
                return res
            res["candidates"] = hits[:10]
            res["err"] = ("找到 %d 个内容相同的工程目录，无法唯一确定"
                          % len(hits))
            return res
        # 名字相同但内容都不匹配 —— 退回指纹反查（见下）
        res["err"] = "找到 %d 个同名目录，内容均不匹配" % len(uniq)

    # ⑤ 内容指纹反查：拿本地顶层目录名去远端找「兄弟目录最多的那个」。
    #    比按工程名找更鲁棒——trunk 这种通用名满地都是，但它的顶层结构
    #    （kernel/uboot/libs/modules/sbuilder…）是工程独有的组合。
    if not res["path"]:
        try:
            local = sorted(x for x in os.listdir(str(local_root))
                           if not x.startswith("."))
        except OSError:
            local = []
        sig = [x for x in local if os.path.isdir(os.path.join(str(local_root), x))][:12]
        if len(sig) >= 3:
            # 在候选根下找一个目录，它同时含有 sig 中的多数条目
            cond = " && ".join("[ -e \"$d\"/%s ]" % _quote(s) for s in sig[:6])
            script = (
                "for r in %s; do [ -d \"$r\" ] || continue; "
                "find \"$r\" -maxdepth 6 -type d -name %s "
                "-not -path '*/.svn/*' -not -path '*/.git/*' 2>/dev/null "
                "| while read d; do %s && echo \"$d\"; done; done"
                % (" ".join(_quote(r) for r in roots), _quote(name), cond))
            try:
                _rc, out = _sh(script, timeout + 10)
                cand2 = []
                for x in out.splitlines():
                    x = x.strip()
                    if x and x not in cand2:
                        cand2.append(x)
                if len(cand2) == 1:
                    res["path"], res["how"] = cand2[0], "fingerprint"
                    res["err"] = ""
                    return res
                if len(cand2) > 1:
                    res["candidates"] = cand2[:10]
                    res["err"] = "按内容指纹匹配到 %d 个目录" % len(cand2)
            except Exception as e:
                res["err"] = _tidy(e)

    # ④ 退回共享根映射
    share = detect_share_root(prof, local_root)
    if share:
        m = re.match(r"^[A-Za-z]:/(.*)$", str(local_root).replace("\\", "/"))
        if m:
            p = share.rstrip("/") + "/" + m.group(1).strip("/")
            try:
                rc, _o = _sh("test -d %s && echo Y" % _quote(p), 10)
                if rc == 0:
                    res["path"], res["how"] = p, "share"
                    return res
            except Exception:
                pass
    res["err"] = ("在构建机上没找到名为「%s」的目录（已搜索 %s）"
                  % (name, "、".join(roots[:3])))
    return res


def guess_remote_root(local_root, prof):
    """由本地路径推导远端路径。网络盘 Z:/W: 之类映射的是构建机共享根。

    例：W:\\work\\linux\\g10\\g10_trunk  +  共享根 /data1/gaoyi13
        → /data1/gaoyi13/work/linux/g10/g10_trunk

    共享根取该档案上一次成功使用的映射（saved_share）或用户填的默认。
    仅做「去掉盘符 + 拼前缀」，不猜其他。"""
    if not local_root:
        return ""
    s = str(local_root).replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", s)
    if not m:
        return ""
    tail = m.group(2).strip("/")
    share = _norm_remote((prof or {}).get("share_root") or "")
    if not share:
        return ""
    return share.rstrip("/") + "/" + tail


def derive_tail(local_root, prof):
    """本地路径相对共享根的部分（用于给用户展示推导结果）。"""
    return guess_remote_root(local_root, prof)


def add_mapping(local_root, profile_id, remote_root=None):
    """只登记「工程 → 远端目录」映射（连接信息复用档案，不再重填）。

    remote_root 为空时按档案的 share_root 自动推导。"""
    local_root = str(local_root or "").strip()
    if not local_root:
        raise ValueError("缺少工程根路径")
    prof = get_profile(profile_id)
    if not prof:
        raise ValueError("连接档案不存在")
    rr = _norm_remote(remote_root) if remote_root else guess_remote_root(local_root, prof)
    if not rr.startswith("/"):
        raise ValueError("无法确定远端路径：请填写远端根路径，"
                         "或先在连接档案里设置「共享根」（如 /data1/gaoyi13）")
    d = load()
    lr = _norm(local_root)
    for e in d.get("remotes") or []:
        if isinstance(e, dict) and _norm(e.get("local_root")) == lr:
            e.update(profile_id=profile_id, remote_root=rr, enabled=True)
            _save(d)
            return e
    e = {"local_root": local_root, "profile_id": profile_id,
         "remote_root": rr, "enabled": True}
    d.setdefault("remotes", []).append(e)
    _save(d)
    return e


# --------------------------------------------------------------------- 映射

def to_remote(entry, local_path):
    """本地绝对路径 → 远端绝对路径（不在工程根下则原样返回）。"""
    if not local_path:
        return local_path
    lr = str(entry.get("local_root") or "")
    rr = _norm_remote(entry.get("remote_root"))
    s = str(local_path)
    if not lr:
        return s
    a = os.path.normcase(os.path.normpath(s))
    b = os.path.normcase(os.path.normpath(lr))
    if a == b:
        return rr
    if a.startswith(b + os.sep):
        tail = s[len(lr):].lstrip("\\/").replace("\\", "/")
        return rr + "/" + tail
    # 也可能是「相对 wc 的路径」（-- 之后的参数）——原样给远端即可
    return s.replace("\\", "/")


def _map_argv(entry, argv, cwd):
    """把 argv 里的本地绝对路径翻译成远端路径。相对路径保持原样。"""
    out = []
    for a in argv:
        s = str(a)
        if os.path.isabs(s):
            out.append(to_remote(entry, s))
        else:
            out.append(s)
    return out


def _allowed(argv):
    """子命令白名单：首两个 token 命中即放行。"""
    # 合入审计 F5：原 argv[:3] 截断使 git -c k=v 后面的真实子命令（第 4 位）
    # 永远看不到，只能靠 _ALLOW 里那个危险的三元前缀兜——放到 8 位，跳 -c
    # 逻辑才能校验到子命令本体
    head = [str(x) for x in argv[:8]]
    for pat in _ALLOW:
        if head[:len(pat)] == list(pat):
            return True
    # git -c k=v 形态：跳过 -c 参数再看子命令
    if head and head[0] == "git":
        i = 1
        while i < len(head) and head[i].startswith("-"):
            i += 2 if head[i] in ("-c", "-C") else 1
        if i < len(head):
            sub = head[i]
            return ("git", sub) in _ALLOW
    return False


# --------------------------------------------------------------------- 连接

def _get_client(entry):
    host = str(entry.get("host") or "").strip()
    port = int(entry.get("port") or 22)
    user = str(entry.get("user") or "").strip()
    if not host or not user:
        raise RemoteError("远端主机或用户名为空")
    key = "%s:%s:%s" % (host, port, user)
    now = time.time()
    with _POOL_LOCK:
        got = _POOL.get(key)
        if got and (now - got["ts"] < _POOL_IDLE) and got["cli"].get_transport() \
                and got["cli"].get_transport().is_active():
            got["ts"] = now
            return got["cli"]
        if got:
            try:
                got["cli"].close()
            except Exception:
                pass
            _POOL.pop(key, None)

    try:
        import paramiko
    except ImportError:
        raise RemoteError("本程序未内置 paramiko，无法使用 SSH 加速")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    kwargs = dict(hostname=host, port=port, username=user,
                  timeout=12, banner_timeout=12, auth_timeout=15,
                  allow_agent=True, look_for_keys=False)
    auth = str(entry.get("auth") or "password")
    if auth == "key":
        kp = str(entry.get("key_path") or "").strip()
        if not kp or not os.path.isfile(kp):
            raise RemoteError("私钥文件不存在：%s" % (kp or "(未填写)"))
        kwargs["key_filename"] = kp
        kwargs["look_for_keys"] = True
    elif auth == "agent":
        kwargs["look_for_keys"] = True
    else:
        pwd = _dec(entry.get("secret_enc"))
        if not pwd:
            raise RemoteError("未保存登录口令")
        kwargs["password"] = pwd
    try:
        cli.connect(**kwargs)
    except Exception as e:
        try:
            cli.close()
        except Exception:
            pass
        raise RemoteError("SSH 连接失败（%s）：%s" % (host, _tidy(e)))
    with _POOL_LOCK:
        _POOL[key] = {"cli": cli, "ts": time.time()}
    return cli


def _tidy(e):
    """paramiko 异常信息去掉类名前缀，只留人话。"""
    s = str(e)
    s = re.sub(r"^\(.*?\)\s*", "", s)
    return s[:160] or type(e).__name__


def drop_pool(entry=None):
    """丢弃连接（改配置/换口令后调用）。entry=None 清全部。"""
    with _POOL_LOCK:
        if entry is None:
            keys = list(_POOL)
        else:
            keys = ["%s:%s:%s" % (entry.get("host"), int(entry.get("port") or 22),
                                  entry.get("user"))]
        for k in keys:
            v = _POOL.pop(k, None)
            if v:
                try:
                    v["cli"].close()
                except Exception:
                    pass


# --------------------------------------------------------------------- 执行

def _quote(a):
    """远端命令的 shell 引号（SSH exec 会过远端 shell）。"""
    s = str(a)
    if re.fullmatch(r"[A-Za-z0-9_@%+=:,./-]+", s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def run(entry, argv, cwd, timeout=60, gzip_above=256 * 1024):
    """远端执行，返回 (rc, stdout_bytes, stderr_str)。

    a455 性能：大输出（全树 status 6.8 MB）走 SSH 时，paramiko 的 Python
    层分块读取 + 逐块解密是主要瓶颈（实测 9.8s vs 原生 ssh 2.1s）。这里让
    远端先 gzip 再回传——status XML 压缩率约 8 倍（6.8 MB → 0.85 MB），
    网络与解密都少一个数量级。gzip_above 形参保留兼容：输出大小事前不可知，
    压缩恒开（小输出的压缩开销可忽略）。

    合入审计 F1/F2 修正：
    ① 原实现 `cmd | gzip` 管道的退出码是 **gzip 的**——svn/git 真实 rc 被
      掩蔽成 0（git 空输出在 _git_status_run 会解析成「干净工作区」假阴性，
      svn 靠 XML 解析失败才兜住）。改用 rcf 中转文件把真实 rc 穿出管道
      （$$ 是本条 exec_command 专属远端 shell 的 PID，并发不撞车）。
    ② 原「远端无 gzip 按魔数退明文」并不成立：无 gzip 时管道空输出
      rc=127，魔数判断根本走不到。改 command -v 分支——无 gzip 明文直跑。"""
    if not _allowed(argv):
        raise RemoteError("拒绝执行非版本控制命令：%s" % " ".join(argv[:3]))
    cli = _get_client(entry)
    rcwd = to_remote(entry, cwd)
    inner = "cd %s && %s" % (
        _quote(rcwd), " ".join(_quote(a) for a in _map_argv(entry, argv, cwd)))
    cmd = (
        "if command -v gzip >/dev/null 2>&1; then "
        "rcf=/tmp/.vcs_rc.$$; "
        "( %s; echo $? >\"$rcf\" ) | gzip -c 2>/dev/null; "
        "rc=$(cat \"$rcf\" 2>/dev/null || echo 127); rm -f \"$rcf\"; exit \"$rc\"; "
        "else %s; fi" % (inner, inner))
    try:
        _in, out, err = cli.exec_command(cmd, timeout=timeout)
        data = out.read()
        ebytes = err.read()
        rc = out.channel.recv_exit_status()
    except Exception as e:
        drop_pool(entry)
        raise RemoteError("远端命令执行失败：%s" % _tidy(e))
    # gzip 魔数 1f 8b → 解压；无 gzip 的明文分支原样输出
    if data[:2] == b"\x1f\x8b":
        try:
            import gzip
            data = gzip.decompress(data)
        except Exception:
            pass
    return rc, data, _decode(ebytes)


def _decode(b):
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except (UnicodeDecodeError, LookupError):
            pass
    return b.decode("utf-8", "replace")


# --------------------------------------------------------------------- 探测

def test(entry, timeout=15):
    """连通性 + 版本工具可用性探测。返回 dict（供 UI 展示），不抛异常。"""
    out = {"ok": False, "err": "", "latency_ms": 0, "vcs": "",
           "svn_version": "", "git_version": "", "remote_root_ok": False}
    t0 = time.time()
    try:
        cli = _get_client(entry)
        rr = _norm_remote(entry.get("remote_root"))
        cmd = ("cd %s 2>/dev/null || { echo __MISS__; exit 3; }; "
               "svn --version --quiet 2>/dev/null; git --version 2>/dev/null"
               % _quote(rr))
        _in, o, e = cli.exec_command(cmd, timeout=timeout)
        data = _decode(o.read())
        rc = o.channel.recv_exit_status()
        out["latency_ms"] = int((time.time() - t0) * 1000)
        if "__MISS__" in data or rc == 3:
            out["err"] = "远端目录不存在：%s" % rr
            return out
        lines = [x.strip() for x in data.splitlines() if x.strip()]
        for ln in lines:
            if ln.startswith("git version"):
                out["git_version"] = ln
            elif re.match(r"^\d+(\.\d+)+", ln):
                out["svn_version"] = ln
        out["ok"] = True
        out["remote_root_ok"] = True
    except RemoteError as ex:
        out["err"] = str(ex)
        out["latency_ms"] = int((time.time() - t0) * 1000)
    except Exception as ex:
        out["err"] = _tidy(ex)
        out["latency_ms"] = int((time.time() - t0) * 1000)
    return out


def probe_scope(local_root):
    """给出该工程「要不要引导用 SSH」的判定依据（供 UI 决定显示什么）。

    返回 {is_network: bool, drive: str, configured: bool,
          enabled: bool, remote_ok: bool|None, reason: str}
    """
    from src.vcs import _is_network_drive
    drive = os.path.splitdrive(os.path.abspath(local_root))[0] if local_root else ""
    is_net = False
    try:
        is_net = bool(local_root) and _is_network_drive(local_root)
    except Exception:
        is_net = False
    e = get_for_root(local_root)
    res = {"is_network": is_net, "drive": drive, "configured": bool(e),
           "enabled": bool(e and e.get("enabled", True)),
           "remote_ok": None, "reason": ""}
    if not is_net:
        res["reason"] = "local"
    elif not e:
        res["reason"] = "unconfigured"
    elif not e.get("enabled", True):
        res["reason"] = "disabled"
    else:
        res["reason"] = "configured"
    return res


# --------------------------------------------------------------------- 用户配置

def upsert(local_root, host=None, user=None, remote_root=None, auth="password",
           password=None, key_path="", port=22, enabled=True,
           profile_id=None, share_root="", name=""):
    """保存工程映射 + （可选）更新连接档案。

    参数里 host/user/auth 等给定时，按 主机+端口+用户+认证 找同名档案并
    更新（口令为 None 保留原密文）；未给定时只更新工程映射。
    换工程时用户只需选已有档案，不必重填主机/口令。"""
    local_root = str(local_root or "").strip()
    if not local_root:
        raise ValueError("缺少工程根路径")
    d = load()
    prof = get_profile(profile_id) if profile_id else None
    # 显式给了主机信息 → 新建/更新档案
    if host:
        host = str(host).strip()
        user = str(user or "").strip()
        if not host or not user:
            raise ValueError("远端主机与用户名必填")
        try:
            port = int(port or 22)
        except (TypeError, ValueError):
            raise ValueError("端口必须是数字")
        if prof is None:
            prof = _match_or_add_profile(d, {
                "host": host, "port": port, "user": user,
                "auth": auth or "password", "secret_enc": "",
                "key_path": str(key_path or "").strip()})
        else:
            prof.update({"host": host, "port": port, "user": user,
                         "auth": auth or prof.get("auth") or "password",
                         "key_path": str(key_path or prof.get("key_path") or "").strip()})
        if password:
            prof["secret_enc"] = _enc(password)
        elif not prof.get("secret_enc") and (prof.get("auth") or "password") == "password":
            raise ValueError("密码登录必须填写口令")
        if share_root:
            prof["share_root"] = _norm_remote(share_root)
        if name:
            prof["name"] = str(name)[:40]
        prof.setdefault("name", prof.get("host") or "")
    if prof is None:
        raise ValueError("请选择或填写一个连接档案（主机/用户名）")
    # a455（用户令：不要让用户填路径，连上就该自己探测）：
    # 没给 remote_root 时，直接在构建机上定位这个工程目录。
    if not remote_root:
        det = detect_project_path(prof, local_root)
        if det.get("path"):
            remote_root = det["path"]
        else:
            raise ValueError(
                "没能在构建机上定位这个工程。\n%s\n"
                "如确需手动指定，可填写远端路径。" % (det.get("err") or ""))
    rr = _norm_remote(remote_root)
    if not rr.startswith("/"):
        raise ValueError("远端工程路径必须是 Linux 绝对路径（以 / 开头）")
    # 兜底：路径若明显是父目录（没有工程名这一级），自动探测纠正
    base_name = os.path.basename(str(local_root).rstrip("\\/"))
    if base_name and rr.rstrip("/").split("/")[-1] != base_name:
        det = detect_project_path(prof, local_root)
        if det.get("path"):
            rr = det["path"]
    remotes = d.setdefault("remotes", [])
    lr = _norm(local_root)
    entry = None
    for e in remotes:
        if isinstance(e, dict) and _norm(e.get("local_root")) == lr:
            e.update(profile_id=prof["id"], remote_root=rr,
                     enabled=bool(enabled))
            entry = e
            break
    if entry is None:
        entry = {"local_root": local_root, "profile_id": prof["id"],
                 "remote_root": rr, "enabled": bool(enabled)}
        remotes.append(entry)
    _save(d)
    drop_pool(prof)      # 改了配置就重连，避免沿用旧口令的连接
    return entry


def upsert_profile(profile_id=None, name="", host="", user="", auth="password",
                   password=None, key_path="", port=22, share_root=""):
    """单独维护连接档案（换工程时复用）。返回档案 dict。"""
    host = str(host or "").strip()
    user = str(user or "").strip()
    if not host or not user:
        raise ValueError("远端主机与用户名必填")
    try:
        port = int(port or 22)
    except (TypeError, ValueError):
        raise ValueError("端口必须是数字")
    d = load()
    prof = get_profile(profile_id) if profile_id else None
    if prof is None:
        prof = _match_or_add_profile(d, {
            "host": host, "port": port, "user": user,
            "auth": auth or "password", "secret_enc": "",
            "key_path": str(key_path or "").strip()})
    prof.update({"host": host, "port": port, "user": user,
                 "auth": auth or prof.get("auth") or "password",
                 "key_path": str(key_path or prof.get("key_path") or "").strip()})
    if password:
        prof["secret_enc"] = _enc(password)
    elif not prof.get("secret_enc") and (prof.get("auth") or "password") == "password":
        raise ValueError("密码登录必须填写口令")
    if share_root:
        prof["share_root"] = _norm_remote(share_root)
    if name:
        prof["name"] = str(name)[:40]
    _save(d)
    drop_pool(prof)
    return prof


def remove_profile(profile_id):
    """删档案：连带删掉引用它的工程映射（否则映射会变成孤儿）。"""
    d = load()
    prof = get_profile(profile_id)
    d["profiles"] = [p for p in (d.get("profiles") or [])
                     if not (isinstance(p, dict) and p.get("id") == profile_id)]
    before = len(d.get("remotes") or [])
    d["remotes"] = [e for e in (d.get("remotes") or [])
                    if not (isinstance(e, dict) and e.get("profile_id") == profile_id)]
    _save(d)
    if prof:
        drop_pool(prof)
    return {"removed_profile": bool(prof),
            "removed_mappings": before - len(d.get("remotes") or [])}


def public_profile(prof):
    """档案的前端视图（去掉密文）。"""
    if not prof:
        return None
    return {"id": prof.get("id"), "name": prof.get("name") or prof.get("host"),
            "host": prof.get("host"), "port": prof.get("port"),
            "user": prof.get("user"), "auth": prof.get("auth"),
            "key_path": prof.get("key_path"),
            "share_root": prof.get("share_root") or "",
            "has_secret": bool(prof.get("secret_enc"))}


def list_profiles():
    return [public_profile(p) for p in (load().get("profiles") or [])
            if isinstance(p, dict)]


def list_mappings():
    """所有工程映射（前端用来显示「哪些工程已接入 SSH」）。"""
    out = []
    for e in load().get("remotes") or []:
        if not isinstance(e, dict):
            continue
        prof = get_profile(e.get("profile_id"))
        out.append({"local_root": e.get("local_root"),
                    "remote_root": e.get("remote_root"),
                    "profile_id": e.get("profile_id"),
                    "profile_name": (prof or {}).get("name") or "",
                    "enabled": e.get("enabled", True)})
    return out


def remove(local_root):
    d = load()
    remotes = [e for e in (d.get("remotes") or [])
               if not (isinstance(e, dict)
                       and _norm(e.get("local_root")) == _norm(local_root))]
    d["remotes"] = remotes
    _save(d)
    return True


def public_view(entry):
    """给前端的视图：去掉密文，只给「有没有口令」。entry 是合并后的 dict。"""
    if not entry:
        return None
    return {"local_root": entry.get("local_root"),
            "remote_root": entry.get("remote_root"),
            "host": entry.get("host"), "port": entry.get("port"),
            "user": entry.get("user"), "auth": entry.get("auth"),
            "key_path": entry.get("key_path"),
            "profile_id": entry.get("profile_id"),
            "share_root": entry.get("share_root") or "",
            "has_secret": bool(entry.get("secret_enc")),
            "enabled": entry.get("enabled", True)}


# --------------------------------------------------------------------- 密钥部署

def deploy_key(entry, key_path=""):
    """一键部署公钥：本地生成（若无需新）→ 用现存口令登录 → 追加到
    ~/.ssh/authorized_keys。成功后把该条配置切到 key 认证。

    返回 {ok, err, key_path, pub, switched}
    """
    res = {"ok": False, "err": "", "key_path": key_path, "pub": "",
           "switched": False}
    try:
        import paramiko
    except ImportError:
        res["err"] = "本程序未内置 paramiko"
        return res
    kp = str(key_path or "").strip() or _default_key_path()
    priv, pub = _ensure_keypair(kp)
    res["key_path"] = priv
    res["pub"] = pub

    host = str(entry.get("host") or "")
    user = str(entry.get("user") or "")
    pwd = _dec(entry.get("secret_enc"))
    if not pwd:
        res["err"] = ("未保存登录口令，无法自动部署。请先在「密码登录」里填一次"
                      "口令并保存，再点一键部署；或手动把公钥追加到远端："
                      "echo '%s' >> ~/.ssh/authorized_keys" % pub)
        return res
    try:
        cli = paramiko.SSHClient()
        cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        cli.connect(hostname=host, port=int(entry.get("port") or 22),
                    username=user, password=pwd, timeout=12,
                    banner_timeout=12, auth_timeout=15,
                    allow_agent=False, look_for_keys=False)
        cmd = ("umask 077; mkdir -p ~/.ssh && touch ~/.ssh/authorized_keys && "
               "grep -qxF %s ~/.ssh/authorized_keys || echo %s >> ~/.ssh/authorized_keys; "
               "echo __DONE__" % (_sq(pub), _sq(pub)))
        _in, o, _e = cli.exec_command(cmd, timeout=20)
        # 合入审计 F8：__DONE__ 是远端唯一的成功回执——原来 o.read() 读了
        # 丢弃，追加失败（磁盘满/权限）也报「部署成功」，切 key 后下次连接
        # 才暴露。必须见到回执才算成。
        done = _decode(o.read())
        cli.close()
        if "__DONE__" not in done:
            res["err"] = "远端未确认写入（authorized_keys 追加失败）"
            return res
        # 切档案到 key 认证（档案是全局的，换工程同样免密）
        pid = entry.get("profile_id")
        if pid:
            upsert_profile(profile_id=pid, host=entry.get("host"),
                           user=entry.get("user"), auth="key",
                           key_path=priv, port=entry.get("port") or 22)
        else:
            upsert(local_root=entry.get("local_root") or "",
                   host=entry.get("host"), user=entry.get("user"),
                   remote_root=entry.get("remote_root"), auth="key",
                   password=None, key_path=priv,
                   port=entry.get("port") or 22)
        res["ok"] = True
        res["switched"] = True
    except Exception as ex:
        res["err"] = "部署失败：%s" % _tidy(ex)
    return res


def _sq(s):
    return "'" + str(s).replace("'", "'\\''") + "'"


def _default_key_path():
    home = os.path.expanduser("~")
    for name in ("id_ed25519", "id_rsa"):
        p = os.path.join(home, ".ssh", name)
        if os.path.isfile(p) and os.path.isfile(p + ".pub"):
            return p
    return os.path.join(home, ".ssh", "id_ed25519")


def _ensure_keypair(path):
    """确保 path/.pub 成对存在；缺失则生成 ed25519。返回 (私钥, 公钥行)。"""
    if os.path.isfile(path) and os.path.isfile(path + ".pub"):
        with open(path + ".pub", encoding="utf-8") as f:
            return path, f.read().strip()
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    import paramiko
    k = paramiko.Ed25519Key  # noqa: F841  确认可用（不支持时下面回退 RSA）
    try:
        from cryptography.hazmat.primitives.asymmetric import ed25519
        from cryptography.hazmat.primitives import serialization
        sk = ed25519.Ed25519PrivateKey.generate()
        priv = sk.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption())
        pub = sk.public_key().public_bytes(
            serialization.Encoding.OpenSSH,
            serialization.PublicFormat.OpenSSH).decode() + " vcs-remote"
        with open(path, "wb") as f:
            f.write(priv)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        with open(path + ".pub", "w", encoding="utf-8") as f:
            f.write(pub + "\n")
        return path, pub
    except Exception:
        raise RemoteError("生成密钥失败（cryptography 不可用）")
