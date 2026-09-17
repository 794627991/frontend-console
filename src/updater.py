# -*- coding: utf-8 -*-
"""客户端升级器（v2.1.0）：检查 / 下载 / 校验 / 自替换。

链路：升级服务器（发布机的 dist/releases/，见 update_server.py）放
manifest.json + 版本化 exe；本模块 GET manifest → semver 比对 → 下载到
exe 旁 .update/ → sha1 校验 → 写 update.bat（等旧进程退出→move 覆盖→
拉起新版→自删）→ 请求真退出，bat 完成替换。

- 旧 exe 备份为 .bak（覆盖式），升级翻车手动改名即可回退
- dev 模式（python 源码跑，非 PyInstaller frozen）拒绝自升级——替换的是
  python.exe 没有意义
- manifest 的 file 字段是相对名，完整 URL = update_url + file：发布机换
  IP 只需同事端改 update_url 一处（设置页），manifest 不用动
"""
import os, sys, json, time, shutil, hashlib, threading
import urllib.request

from src.version import APP_VERSION

_DL_DIR = ".update"
_BAT = "update.bat"


def _cfg_url(new_url=None):
    """读写升级服务器地址（config.update_url，形如 http://10.33.x.x:8765/）。"""
    from src.app_state import _load_config, _save_config
    cfg = _load_config()
    if new_url is not None:
        u = (new_url or "").strip()
        if u and not u.endswith("/"):
            u += "/"
        cfg["update_url"] = u
        _save_config(cfg)
        return u
    u = (cfg.get("update_url") or "").strip()
    return u if not u or u.endswith("/") else u + "/"


def _ver_tuple(v):
    """'2.1.0' → (2,1,0)。非法段按 0 处理，永不抛——比较用途足够。"""
    out = []
    for seg in str(v or "").split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        out.append(int(digits) if digits else 0)
    while len(out) < 3:
        out.append(0)
    return tuple(out[:3])


def _fetch_manifest(base, timeout=5):
    url = base + "manifest.json"
    req = urllib.request.Request(url, headers={"User-Agent": "frontend-console-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
    m = json.loads(data.decode("utf-8"))
    for k in ("version", "file", "sha1"):
        if not m.get(k):
            raise ValueError("manifest 缺字段 %s" % k)
    return m


def check_update():
    """拉 manifest 并与当前版本比对。返回前端直接可用的 dict（永不抛）。"""
    cur = APP_VERSION
    base = _cfg_url()
    if not base:
        return {"ok": True, "current": cur, "configured": False}
    try:
        m = _fetch_manifest(base)
    except Exception as e:
        # 连不上发布机是常态（发布机关机/换网）——ok=True + unreachable 标记，
        # 前端区分「服务器不在」和「接口炸了」
        return {"ok": True, "current": cur, "configured": True,
                "unreachable": True, "err": str(e)[:200]}
    latest = str(m.get("version") or "")
    has = _ver_tuple(latest) > _ver_tuple(cur)
    return {"ok": True, "current": cur, "configured": True,
            "latest": latest, "has_update": has,
            "notes": (m.get("notes") or "")[:500],
            "size": m.get("size") or 0, "date": m.get("date") or "",
            "file": m.get("file") or ""}


def _exe_path():
    """当前主程序 exe 完整路径（frozen）。dev 模式返回 None。"""
    if not getattr(sys, "frozen", False):
        return None
    return sys.executable


def _write_bat(exe_dir, exe_name, new_file):
    """自替换脚本（GBK 写，中文路径/文件名在 chcp 936 下可靠）。
    流程：等旧进程退出（3s）→ move 覆盖 → 拉起新版 → 自删。"""
    bat = os.path.join(exe_dir, _BAT)
    body = "\r\n".join([
        "@echo off",
        "chcp 936 >nul",
        'cd /d "%s"' % exe_dir,
        "timeout /t 3 /nobreak >nul",
        'move /y "%s" "%s"' % (os.path.join(_DL_DIR, new_file), exe_name),
        "if errorlevel 1 goto fail",
        'start "" "%s"' % exe_name,
        'del "%%~f0"',
        "exit /b 0",
        ":fail",
        "echo [升级失败] 无法覆盖主程序（程序可能还在运行），关掉后重试",
        "pause",
        'del "%%~f0"',
    ]) + "\r\n"
    with open(bat, "w", encoding="gbk") as f:
        f.write(body)
    return bat


def apply_update():
    """下载 + 校验 + 备份 + 写 update.bat。返回 (ok, err/bat)。"""
    exe = _exe_path()
    if not exe:
        return False, "开发模式（源码运行）不支持自升级，仅打包版可用"
    base = _cfg_url()
    if not base:
        return False, "未配置升级服务器地址"
    try:
        m = _fetch_manifest(base)
    except Exception as e:
        return False, "获取升级信息失败：%s" % str(e)[:150]
    if _ver_tuple(m.get("version")) <= _ver_tuple(APP_VERSION):
        return False, "已是最新版本（v%s）" % APP_VERSION

    exe_dir = os.path.dirname(exe)
    exe_name = os.path.basename(exe)
    dl_dir = os.path.join(exe_dir, _DL_DIR)
    os.makedirs(dl_dir, exist_ok=True)
    dst = os.path.join(dl_dir, m["file"])
    url = base + m["file"]
    # 下载（带重试一次：内网偶发 reset）
    last_err = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "frontend-console-updater"})
            with urllib.request.urlopen(req, timeout=30) as r, open(dst + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(dst + ".part", dst)
            last_err = None
            break
        except Exception as e:
            last_err = e
            time.sleep(1)
    if last_err is not None:
        return False, "下载失败：%s" % str(last_err)[:150]
    # sha1 校验（防损坏/防篡改——发布端 build.py 算的指纹）
    h = hashlib.sha1()
    with open(dst, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest().lower() != str(m["sha1"]).lower():
        try:
            os.remove(dst)
        except OSError:
            pass
        return False, "校验失败（sha1 不符），已丢弃下载文件——请重试或联系发布者"
    # 备份旧版（回退通道：翻车时把 .bak 改回原名即可）
    try:
        shutil.copy2(exe, exe + ".bak")
    except OSError:
        pass   # 备份失败不阻断——升级本身仍可进行
    bat = _write_bat(exe_dir, exe_name, m["file"])
    return True, bat


def run_update():
    """执行升级：拉起 update.bat（独立进程）+ 请求本进程真退出。
    bat 等 3s 覆盖后自动启动新版——用户视角：确认 → 黑窗一闪 → 新版起来。"""
    exe = _exe_path()
    if not exe:
        return False, "开发模式不支持"
    bat = os.path.join(os.path.dirname(exe), _BAT)
    if not os.path.isfile(bat):
        return False, "未找到升级脚本（先执行 apply）"
    os.startfile(bat)   # noqa: startfile 仅 Windows；detached 拉起
    threading.Timer(0.8, _request_quit).start()
    return True, None


def _request_quit():
    """请求真退出（跳过托盘）。main._real_quit/_win 由 main.run() 挂模块级。"""
    try:
        import src.main as main
        q = getattr(main, "_real_quit", None)
        if isinstance(q, dict):
            q["flag"] = True
        w = getattr(main, "_win", None)
        if w is not None:
            w.destroy()   # 走 closing 回调：flag 已置 → 真退出清理链
            return
    except Exception:
        pass
    os._exit(0)   # 兜底：窗口已死/异常路径也必须退，让 bat 完成覆盖
