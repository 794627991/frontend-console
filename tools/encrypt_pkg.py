# -*- coding: utf-8 -*-
"""发布包资源加密器（v2.3.1，build.py 在打 zip 发布前调用）。

对 dist/前端控制台/_internal 下的自有资产逐文件 AES-256-GCM 加密：
- web/**（前端源码）与 src/*（自有资源）→ 同名 .enc，明文删除
- 写 .fcenc 清单（相对路径列表），exe 启动时 src/secure_boot.decrypt_all
  按清单解密还原（首启一次，此后零开销）
第三方库不碰。幂等：已是全密文状态（.fcenc 在且无明文）时跳过。
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.secure_boot import _MAGIC, _VER, _derive_key   # noqa: E402

_TARGET_DIRS = ("web", "src")       # _internal 下要加密的自有目录
_TARGET_EXT = (".html", ".js", ".css", ".json", ".blob", ".md", ".txt")
# v2.3.2：.pyc 不再外置（Cython .pyd 路线，机器码无需加密）；pyd 后缀也不加密
_SKIP_NAMES = {"_internal"}         # 目录级排除（src/ 下无子目录场景无此问题）


def _stage_src_pyd(app_dir, project_root):
    """v2.3.2：自有模块以 Cython .pyd 外置（用户定调治本：pyd 是机器码，
    磁盘不存在可反编译形态，无需加密）。tools/cythonize_build 产物 → 拷到
    _internal/src/ 平铺。返回拷入的 pyd 数。"""
    import shutil
    from tools.cythonize_build import build_all, OUT
    ok, fails = build_all()          # 增量编译（改动过的才重编）
    if fails:
        raise RuntimeError("Cython 编译失败：%s" % fails[:3])
    dst_root = os.path.join(app_dir, "_internal", "src")
    os.makedirs(dst_root, exist_ok=True)
    n = 0
    for f in os.listdir(OUT):
        if f.endswith(".pyd"):
            shutil.copy2(os.path.join(OUT, f), os.path.join(dst_root, f))
            n += 1
    # 资源文件（blob 等）随包外置（走加密）
    for f in os.listdir(os.path.join(project_root, "src")):
        if os.path.splitext(f)[1].lower() in _TARGET_EXT and f != "main.py":
            shutil.copy2(os.path.join(project_root, "src", f),
                         os.path.join(dst_root, f))
    return n


def encrypt_pkg(app_dir, project_root=None):
    """app_dir=dist/前端控制台。返回加密文件数（0=无需处理）。
    v2.3.2：先外置自有 pyd（_stage_src_pyd，不加密——机器码），再加密 web/blob。"""
    internal = os.path.join(app_dir, "_internal")
    manifest = os.path.join(internal, ".fcenc")
    if project_root is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not os.path.isfile(manifest):
        _stage_src_pyd(app_dir, project_root)
    enc_files = []
    for d in _TARGET_DIRS:
        base = os.path.join(internal, d)
        if not os.path.isdir(base):
            continue
        for r, _ds, fs in os.walk(base):
            for f in fs:
                p = os.path.join(r, f)
                if p.endswith(".enc"):
                    continue
                if os.path.splitext(f)[1].lower() not in _TARGET_EXT:
                    continue
                enc_files.append(p)
    if not enc_files:
        return 0
    from Crypto.Cipher import AES
    key = _derive_key()
    rels = []
    for p in enc_files:
        blob = open(p, "rb").read()
        nonce = os.urandom(12)
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        ct, tag = cipher.encrypt_and_digest(blob)
        with open(p + ".enc", "wb") as f:
            f.write(_MAGIC + bytes([_VER]) + nonce + tag + ct)
        os.remove(p)
        rels.append(os.path.relpath(p + ".enc", internal).replace("\\", "/"))
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump({"files": rels}, f, ensure_ascii=False)
    return len(rels)


if __name__ == "__main__":
    _app = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "dist", "前端控制台")
    n = encrypt_pkg(_app)
    print("加密 %d 个资源文件 → %s/_internal/.fcenc" % (n, _app))
