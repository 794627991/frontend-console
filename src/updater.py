# -*- coding: utf-8 -*-
"""客户端升级器（v2.3.0 zip 形态）：检查 / 下载 / 校验 / 解压 / 整目录替换。

链路：升级服务器（发布机的 dist/releases/，见 update_server.py）放
manifest.json + 版本化 zip（onedir 应用目录打包，见 build.py）；本模块
GET manifest → semver 比对 → 下载 zip 到应用目录旁 .update/ → sha1 校验
→ 安全解压 → 写 update.bat（等旧进程退出 → 旧应用目录整体改名为
.bak-时间戳 → 新目录就位 → data/ 用户数据迁移 → 拉起新版 → 自删）。

- 回退通道：翻车时把 .bak-时间戳 目录改回原名即可
- data/ 是用户数据（凭据/会话/命令库），升级必保全——替换后从 .bak 搬回
- staging 放应用目录同级（同盘 move 原子；放应用目录内会被随目录改名带走）
- dev 模式（python 源码跑，非 PyInstaller frozen）拒绝自升级——替换的是
  python.exe 没有意义
- manifest 的 file 字段是相对名，完整 URL = update_url + file：发布机换
  IP 只需同事端改 update_url 一处（设置页），manifest 不用动
- v2.2.x 及更早 onefile 旧版没有 zip 升级能力，升级到本版需手动换装一次
"""
import os, sys, json, time, shutil, hashlib, threading
import urllib.parse
import urllib.request

from src.version import APP_VERSION

_DL_DIR = ".update"          # 应用目录旁的暂存目录（同级，非应用目录内）
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
    if not str(m.get("file", "")).lower().endswith(".zip"):
        raise ValueError("发布包不是 zip 形态（v2.3.0 起仅支持 zip）")
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


def _safe_unzip(zip_path, dest):
    """解压到 dest（zip slip 防护：拒绝绝对路径/../ 越界条目）。"""
    import zipfile
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            name = os.path.normpath(info.filename).replace("\\", "/")
            if name.startswith("/") or name.split("/")[0] == "..":
                raise ValueError("非法压缩包条目: %s" % info.filename)
            z.extract(info, dest)


def _locate_app_root(staging_root, exe_name):
    """定位应用根：解压根直接含 exe → 根；唯一子目录含 exe → 该子目录
    （发布 zip 顶层带「前端控制台/」壳）。找不到返回 None。"""
    if os.path.isfile(os.path.join(staging_root, exe_name)):
        return staging_root
    subs = [d for d in os.listdir(staging_root)
            if os.path.isdir(os.path.join(staging_root, d))]
    if len(subs) == 1 and os.path.isfile(os.path.join(staging_root, subs[0], exe_name)):
        return os.path.join(staging_root, subs[0])
    return None


def _write_bat(parent_dir, app_name, exe_name, staging_root):
    """整目录替换脚本（GBK 写，中文路径/文件名在 chcp 936 下可靠）。
    流程：等旧进程退出（3s）→ 旧应用目录改名 .bak-时间戳（回退通道）→
    新目录 move 就位（同级同盘，原子）→ data/ 用户数据从 .bak 搬回 →
    拉起新版 → 清理 staging → 自删。失败分支自动回退改名。"""
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-%s" % (app_name, ts)
    app_rel = app_name                       # 应用目录相对父目录名
    new_rel = os.path.relpath(staging_root, parent_dir)
    bat = os.path.join(parent_dir, _BAT)
    body = "\r\n".join([
        "@echo off",
        "chcp 936 >nul",
        'cd /d "%s"' % parent_dir,
        "timeout /t 3 /nobreak >nul",
        'if exist "%s" ren "%s" "%s"' % (app_rel, app_rel, bak),
        'if not exist "%s" goto fail' % app_rel,
        'move "%s" "%s" >nul' % (new_rel, app_rel),
        "if errorlevel 1 goto fail",
        # data/（用户数据：凭据/会话/命令库）从备份搬回——没有则跳过
        'if exist "%s\\data" move "%s\\data" "%s\\data" >nul' % (bak, bak, app_rel),
        'start "" "%s\\%s"' % (app_rel, exe_name),
        'rd /s /q "%s.update" 2>nul' % app_name,
        'del "%%~f0"',
        "exit /b 0",
        ":fail",
        'if exist "%s" rd /s /q "%s" 2>nul' % (app_rel, app_rel),
        'if exist "%s" ren "%s" "%s"' % (bak, bak, app_rel),
        "echo [升级失败] 已回退到旧版本，请联系发布者或手动重试",
        "pause",
        'del "%%~f0"',
    ]) + "\r\n"
    with open(bat, "w", encoding="gbk") as f:
        f.write(body)
    return bat


def apply_update():
    """下载 zip + 校验 + 解压 + 写 update.bat。返回 (ok, err/bat)。"""
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

    # onedir：exe 在应用目录内，父目录是安装位置（staging 与应用同级同盘）
    app_dir = os.path.dirname(exe)
    app_name = os.path.basename(app_dir)
    exe_name = os.path.basename(exe)
    parent_dir = os.path.dirname(app_dir)
    staging = os.path.join(parent_dir, app_name + _DL_DIR)
    if os.path.isdir(staging):
        shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging, exist_ok=True)
    dst = os.path.join(staging, m["file"])
    # v3.5.32（用户实锤「下载失败 ascii codec can't encode position 5-9」）：
    # 包文件名含中文（前端控制台-v2.3.4.zip）——URL 必须百分号编码，裸中文
    # urllib 直接 ascii 编码崩溃。quote 保留 /（路径分隔），仅编码非 ASCII
    url = base + urllib.parse.quote(m["file"], safe="/")
    # 下载（带重试一次：内网偶发 reset）
    last_err = None
    for attempt in (1, 2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "frontend-console-updater"})
            with urllib.request.urlopen(req, timeout=60) as r, open(dst + ".part", "wb") as f:
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
        shutil.rmtree(staging, ignore_errors=True)
        return False, "校验失败（sha1 不符），已丢弃下载文件——请重试或联系发布者"
    # 解压 + 定位应用根（校验通过才落盘展开）
    try:
        pkg_root = os.path.join(staging, "pkg")
        _safe_unzip(dst, pkg_root)
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        return False, "升级包解压失败：%s" % str(e)[:150]
    app_root = _locate_app_root(pkg_root, exe_name)
    if not app_root:
        shutil.rmtree(staging, ignore_errors=True)
        return False, "升级包结构异常（找不到 %s），已放弃" % exe_name
    bat = _write_bat(parent_dir, app_name, exe_name, app_root)
    return True, bat


def run_update():
    """执行升级：拉起 update.bat（独立进程）+ 请求本进程真退出。
    bat 等 3s 完成整目录替换后自动启动新版——用户视角：确认 → 黑窗一闪
    → 新版起来。回退：安装目录旁的 前端控制台.bak-时间戳 改回原名即可。"""
    exe = _exe_path()
    if not exe:
        return False, "开发模式不支持"
    bat = os.path.join(os.path.dirname(os.path.dirname(exe)), _BAT)
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
    os._exit(0)   # 兜底：窗口已死/异常路径也必须退，让 bat 完成替换
