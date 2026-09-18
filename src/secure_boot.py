# -*- coding: utf-8 -*-
"""发布包资源自解密（v2.3.1，用户需求：包内除 exe 外自有资源加密，
拿到包的人不能直接看到源码；exe 运行自解密，代价最小化——仅首次启动
解密落盘，之后零开销）。

加密对象（tools/encrypt_pkg.py 在打包后处理）：
- _internal/web/**：前端源码（html/js/css，真正的"源码"暴露面）
- _internal/src/*：自有资源（blob 等）
第三方依赖库（flask/paramiko/…公开代码）不加密——最小化代价。
自有 Python 模块本就打进 exe 内嵌 PYZ（pyc），按用户口径 exe 之外再说。

文件格式：b'FCEN' + ver(1) + nonce(12) + tag(16) + AES-256-GCM 密文。
密钥：PBKDF2-HMAC-SHA256(口令, 固定盐, 12 万轮)。口令不落明文——
分段异或混淆存（防 strings 直接抠出，专业逆向不在防御目标内）。
"""
import os, sys, json, hashlib

_MAGIC = b"FCEN"
_VER = 1

# v2.3.6：web/** 解密进内存（Flask 从内存 serve）——磁盘永远保持密文。
# 此前 decrypt_all 把解密结果落盘，运行过一次的机器 web/js 全明文（用户
# 实锤「还是源码」）。blob 等运行时随机读的资源仍落盘。
MEM_WEB = {}   # {"web/index.html": bytes, ...}（server.py 优先从这里 serve）

# 口令混淆（'940810' 逐字符 ^ 0x5A）
_KX = 0x5A
_KM = [0x6D, 0x6E, 0x6A, 0x6E, 0x6B, 0x6A]
# 盐混淆（16B，^ 0x3C）
_SX = 0x3C
_SM = [0x1C, 0x1D, 0x19, 0x1D, 0x58, 0x59, 0x5D, 0x59,
       0x0D, 0x0C, 0x08, 0x0C, 0x49, 0x48, 0x4C, 0x48]


def _derive_key():
    pwd = "".join(chr(b ^ _KX) for b in _KM)
    salt = bytes(b ^ _SX for b in _SM)
    return hashlib.pbkdf2_hmac("sha256", pwd.encode(), salt, 120000)


def _internal_dir():
    """frozen 的 _internal 目录；dev 模式返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    return os.path.dirname(sys.executable) and \
        os.path.join(os.path.dirname(sys.executable), "_internal") or None


def decrypt_all():
    """启动自解密：_internal/.fcenc 清单在 → 逐文件解密。
    v2.3.7：web .enc 永久保留（每次启动重新解密进内存），仅落盘型删 .enc；
    清单保留。个别失败抛 RuntimeError（main 捕获后报错退出，别让加密资源
    缺席的工具半死不活地跑起来）。"""
    root = _internal_dir()
    if not root:
        return
    manifest = os.path.join(root, ".fcenc")
    if not os.path.isfile(manifest):
        return
    try:
        from Crypto.Cipher import AES
        key = _derive_key()
        with open(manifest, encoding="utf-8") as f:
            files = json.load(f).get("files") or []
        bad = []
        for rel in files:
            enc = os.path.join(root, rel)
            try:
                if not os.path.isfile(enc):
                    continue   # v2.3.7：web .enc 永久保留反复解密；落盘型已处理的跳过
                with open(enc, "rb") as f:
                    blob = f.read()
                if blob[:4] != _MAGIC or blob[4] != _VER:
                    raise ValueError("坏密文头")
                nonce, tag, ct = blob[5:17], blob[17:33], blob[33:]
                pt = AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag)
                if rel.startswith("web/"):
                    # v2.3.7：前端资源进内存且 .enc 永久保留（每次启动都要
                    # 重新解密——删了下次就无密可解，用户抓到的致命缺陷）
                    MEM_WEB[rel[:-4]] = pt
                else:
                    # blob 等落盘型：解密覆盖落盘，.enc 同样永久保留
                    # （用户定调：永远不删；重复解密覆盖落盘，幂等无害）
                    plain = enc[:-4] if rel.endswith(".enc") else enc
                    os.makedirs(os.path.dirname(plain) or ".", exist_ok=True)
                    with open(plain, "wb") as f:
                        f.write(pt)
            except Exception as e:
                bad.append("%s (%s)" % (rel, e))
        if bad:
            # v2.3.6 带定位信息：哪个文件坏、应用在哪——MAC fail 多半是
            # 下载截断/解压不全（重下 zip）或拷贝丢块，一眼判断
            raise RuntimeError(
                "资源解密失败（包损坏或口令不符）\n应用目录: %s\n失败文件: %s\n"
                "→ 若为下载截断，重新下载 zip 并完整解压即可"
                % (root, "; ".join(bad[:4])))
        # v2.3.7：清单不再删除——web .enc 每次启动都要重新解密进内存
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError("资源解密失败（包损坏或口令不符）：%s\n应用目录: %s" % (e, root))
