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
            "notes": (m.get("notes") or "")[:4000],
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
    v3.5.292（同事升级失败现场：嵌套目录+文件占用+误删，三图实锤）修复：
    ① taskkill 自家残留实例（防双开实例占文件）
    ② ren 重试循环 30s（旧 3s 固定等待撞 claude 子进程占用=「另一个程序
       正在使用此文件」，ren 失败目录即残）
    ③ fail 分支绝不删原目录（旧 rd /s /q 在半损目录上反复蹂躏=只剩
       _internal 惨案），只做「bak 存在才回退+校验」
    ④ 全程写升级日志（update_log.txt）——失败截图日志即可远程定位
    """
    ts = time.strftime("%Y%m%d-%H%M%S")
    bak = "%s.bak-%s" % (app_name, ts)
    app_rel = app_name                       # 应用目录相对父目录名
    new_rel = os.path.relpath(staging_root, parent_dir)
    bat = os.path.join(parent_dir, _BAT)
    log = "update_log.txt"
    BS = '\\'
    NL = '\\r\\n'
    DBSN = '\\\\'
    body = NL.join([
        '@echo off',
        'chcp 936 >nul',
        'cd /d "' + parent_dir + '"',
        'if exist "' + log + '" del "' + log + '"',
        '>> "' + log + '" echo === 升级开始 ===',
        # 杀残留自家实例（主进程已请求退出；兜底双开/僵尸进程占文件）
        'taskkill /f /im "' + exe_name + '" 2>nul',
        # ren 重试循环：最长 30s（15x2s）——等 claude 子进程/杀软释放文件
        'set /a tries=0',
        ':retry',
        'set /a tries+=1',
        'if exist "' + app_rel + '" ren "' + app_rel + '" "' + bak + '" 2>nul',
        'if exist "' + bak + '" goto ok_renamed',
        'if %tries% GEQ 15 goto fail_busy',
        'timeout /t 2 /nobreak >nul',
        'goto retry',
        ':ok_renamed',
        '>> "' + log + '" echo 旧目录已改名 ' + bak,
        'move "' + new_rel + '" "' + app_rel + '" >nul',
        'if errorlevel 1 goto fail_move',
        '>> "' + log + '" echo 新版本已就位',
        # data/（用户数据：凭据/会话/命令库）从备份搬回——没有则跳过
        'if exist "' + bak + DBSN + 'data" move "' + bak + DBSN + 'data" "' + app_rel + DBSN + 'data" >nul',
        # offline_runtime/（v4.1：离线资源包解出的 WebView2 运行时 + .fcpk.json
        # 安装凭据）也必须搬回。全审 B6 实锤：早前只搬 data/，升级后新目录里
        # 没有运行时 → 硬拦再次触发，用户每升一次版就要重装 700MB 资源包。
        'if exist "' + bak + DBSN + 'offline_runtime" move "' + bak + DBSN + 'offline_runtime" "' + app_rel + DBSN + 'offline_runtime" >nul',
        # 对抗审 P1：旧包（≤2.4.0-a133 形态）的随包 runtime/WebView2Fixed
        # 也要搬回——否则 v2.3.7「无条件随包」保护的无网机器升级后
        # runtime/ 没了、offline_runtime/ 又不存在 → 被闸门硬拦，而可用
        # 运行时正躺在备份目录里没人认（重下 674MB 是唯一出路）
        'if exist "' + bak + DBSN + 'runtime" move "' + bak + DBSN + 'runtime" "' + app_rel + DBSN + 'runtime" >nul',
        'start "" "' + app_rel + DBSN + exe_name + '"',
        'rd /s /q "' + app_name + '.update" 2>nul',
        '>> "' + log + '" echo 升级完成',
        'del "%~f0"',
        'exit /b 0',
        # —— 失败分支：绝不删原目录（v3.5.290 惨案：rd 在半损目录上雪上
        # 加霜最终只剩 _internal）。bak 在=回退；不在=原目录未动，如实报错
        ':fail_move',
        'if exist "' + new_rel + '" rd /s /q "' + new_rel + '" 2>nul',
        ':fail_busy',
        'if exist "' + bak + '" (',
        '  ren "' + bak + '" "' + app_rel + '" 2>nul',
        '  >> "' + log + '" echo 已回退到旧版本',
        ')',
        'if exist "' + app_rel + '" >> "' + log + '" echo 原目录完好未改动',
        '>> "' + log + '" echo [升级失败] 文件被占用无法完成替换——请关闭所有'
        '前端控制台窗口（含 Claude 会话）后重新点升级',
        'echo [升级失败] 文件被占用——请关闭所有前端控制台窗口（含 Claude 会'
        '话）后重新点升级；详见 ' + log,
        'pause',
        'del "%~f0"',
    ]) + NL
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
