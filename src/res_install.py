# -*- coding: utf-8 -*-
"""统一离线资源安装执行器（v4.1）。

职责边界（刻意的）：本模块**只做编排**，不重复实现安装动作——具体的
「msiexec 装 Node / Inno 装 Git / 铺 claude-code / pip 补 wheel」全部
复用 claude_setup 里的既有函数（那些逻辑经过多轮实机验证，重写只会引入
回归）。这里负责：

  1. 打开 `.fcpk` → 解到临时 staging（按 kind 只解需要的）
  2. 按「先决条件优先」的顺序调用对应安装器
  3. 进度/日志回调转给调用方（启动闸门的 IProgressDialog 或前端的轮询）
  4. 装完清理 staging（WebView2 除外——它是常驻运行时）

安装顺序（有真实先决依赖）：
  dotnet → webview2(纯解包) → node → git → claude → pydeps

dotnet 必须在最前：它不是给工具用的，而是给 pywebview 的 pythonnet
后端用的，缺了连窗口都建不出来。
"""
import os
import shutil
import tempfile
import threading
import time

# a595：fcpk 不再顶层导入——它带 pycryptodome（Crypto）依赖，顶层 import
# 会让「缺 Crypto 的源码机器」连在线安装都起不来（在线安装根本不碰 .fcpk，
# pydeps 在线装完 Crypto 后离线包功能自愈）。fcpk 改在真正用它读包的
# read_manifest / install_from 内惰性导入。

# 各 kind 在包内的目录前缀（与打包侧一致）
# 对抗审 a206B P3：_KIND_DIRS 全仓无消费（死配置）——包内前缀与释放路径
# 的一致性由打包/安装两侧约定保证（build.py 的 arc 前缀 ↔ 各 installer
# 的落位），此处删除防误导。约定备忘：webview2→webview2/、bili→bili/、
# dotnet/node/git→install/、claude→claude-code/、pydeps→pydeps/

# 安装顺序：先决条件在前
# a407（用户令）：billion-context 移出安装库——内网装不上是常态，
# 唯一入口=代理面板联网下载（proxy.py /api/proxy/bili_install）。旧资源包
# 里的 bili/ 段随 ORDER 摘除而自然跳过（不解包不报错）
ORDER = ["dotnet", "webview2", "node", "git", "claude",
           "codegraph", "onlyoffice", "pydeps"]


class InstallError(Exception):
    pass


class InstallCancelled(Exception):
    """用户点了进度条取消。外层据此报「已取消」而不是失败。"""


def runtime_root():
    """离线资源解包落点。与 res_boot.wv2_fixed_dir 的探测点一致。"""
    from src.res_boot import app_dir
    return os.path.join(app_dir(), "offline_runtime")


def read_manifest(path):
    """只读包内元信息（段表要口令，但这份是公开的包描述）。

    返回 fcpk.FcpkReader.table 的 resources 段；打不开则抛 FcpkError。
    """
    from src import fcpk
    r = fcpk.FcpkReader(path)
    try:
        return {"entries": [e["path"] for e in r.entries],
                "resources": r.table.get("resources") or [],
                "created": r.table.get("created") or ""}
    finally:
        r.close()


def install_from(path, kinds=None, log=None, progress=None, should_cancel=None,
                 force=False):
    """从 `.fcpk` 安装资源。

    path     : 资源包文件
    kinds    : 只装这些（None=全部）。顺序仍按 ORDER。
    log      : callable(str)，阶段日志
    progress : callable(done, total, label)
    should_cancel : callable() -> bool，每个 kind 开始前与解包块之间查询；
                    返回 True 则抛 InstallCancelled（全审 C1：早前进度条的
                    「取消」按钮完全没接线，用户点了安装照跑还自动重启）
    force    : 强制重装（用户需求「一键重装对应依赖」）。只对 node/git 生效：
               它们平时「已存在就跳过」，force 时重跑安装器。
               dotnet **始终忽略 force**——已满足时强装要管理员 + 重启，
               收益为零；webview2/claude/pydeps 本就恒覆盖/幂等，无需区分。

    返回 {"installed": [...], "skipped": [...], "errors": {kind: msg},
          "absent": [...]}
    其中 absent 是「请求了但包内根本没有」的 kind（与 skipped 里「已存在
    无需安装」的项区分）——调用方必须据此判失败，否则子集包会被误判成功。
    单个资源装失败**不中断**其余——某个装不上（比如无管理员装不了 .NET）
    不该把已经装好的 Node 也回滚。
    """
    say = log or (lambda _m: None)
    from src import fcpk
    # a32x（对抗审 P1）：cs._log 的旧读者（/api/claude/setup_poll）已随 zip
    # 通道退役删除，但 _install_node_from/_install_git_from/_install_pydeps/
    # _download 里 27 处排障日志仍在走 _log。把 say 灌进它的 sink，这些
    # "msiexec 退出码 1603""改用免安装 zip""pip 尾部输出"才会显示在安装面板
    from src import claude_setup as _cs
    # a325R（第2轮对抗审 P1）：保存旧值并在 finally 恢复。原来无条件置 None，
    # 且注入点在同 try 之外——inspect 失败 / FcpkReader 构造抛错时 finally 根本
    # 不执行，sink 永久残留指向已结束任务的 say，后续日志全灌进死回调。
    _prev_sink = _cs._log_sink
    _cs._log_sink = say
    cur = [0]

    def prog(done, total, label=""):
        # a355R（第21轮）：done=None 表示「不确定进度」阶段（跑外部安装器、
        # 复制上万小文件），前端显示流动条纹而不是一个不动的百分比。
        if done is not None:
            cur[0] = done
        if progress:
            progress(done, total, label)

    info = fcpk.inspect(path)
    if not info.get("ok"):
        _cs._log_sink = _prev_sink
        raise InstallError(info.get("err") or "资源包无法读取")
    say("资源包：%.0f MB，%d 个文件" % (info["size"] / 1048576.0,
                                       info.get("entries", 0)))

    want = [k for k in ORDER if (kinds is None or k in kinds)]
    res = {"installed": [], "skipped": [], "errors": {}, "absent": []}

    def _ck():
        if should_cancel and should_cancel():
            raise InstallCancelled("用户取消安装")

    try:
        reader = fcpk.FcpkReader(path)
    except Exception:
        _cs._log_sink = _prev_sink
        raise
    staging = None
    try:
        have = {e["kind"] for e in reader.entries}
        plan = [k for k in want if k in have]
        for k in want:
            if k not in have:
                res["skipped"].append(k)
                # a325R：单独记「包内根本没有」，与「已存在无需安装」区分开。
                # 调用方（res_boot 的启动闸门）必须能看出"这个包装不全"，
                # 否则会误判成功 → 重启 → 再拦 → 死循环。
                res["absent"].append(k)
                say("跳过 %s：包内不含该资源" % k)

        # 全审 N5：进度总量必须按**本次要装的子集**算。早前一律用整包
        # plain_len，只装 pydeps（10MB）时分母是 1.07GB → 进度条几乎停在
        # 0%，最后一跳才硬拉满，形同虚设。
        # mode=link 的 entry 不产生进度字节（只做硬链接，见 fcpk.extract_all），
        # 计入分母会让进度永远到不了 100%（实测全量包 link 重复计重 258MB）。
        sub_total = sum(int(e.get("size") or 0) for e in reader.entries
                        if e.get("kind") in set(plan)
                        and e.get("mode") != "link") or 1

        # 对抗审 a206B P2/P3：staging 挪到 exe 同盘——原 %TEMP% 跨盘时
        # claude-code 长路径（实测树内最长 175 字符 + TEMP 前缀 60 = 236/260，
        # 内网默认 LongPaths=0 时再长一点即爆）且任何整目录 move 必跨卷；
        # 同盘短前缀双防。exe 目录不可写时回退 TEMP（降级不阻断）
        try:
            from src.res_boot import app_dir as _ad
            _stage_base = os.path.join(_ad(), ".fcpk_stage")
            os.makedirs(_stage_base, exist_ok=True)
            staging = tempfile.mkdtemp(prefix="s_", dir=_stage_base)
        except OSError:
            staging = tempfile.mkdtemp(prefix="fcpk_stage_")
        _ck()
        # 对抗审 a206B P1：staging 在 %TEMP%（常为 C 盘）而工具常解压在
        # D/E 盘——整目录 os.replace 跨卷必炸（WinError 17 实测）。bili 改
        # webview2 同款：直接解到 runtime_root()（arc 前缀 bili/ 天然落
        # offline_runtime/bili/），不经 staging 不 move
        # a407：bili 解包分支移除（移出安装库）
        if "webview2" in plan:
            # 返回值 False = 已完成跳过（没解包，不产生进度字节）→ 把它
            # 的体量从分母里扣掉，否则单装 webview2 时进度条只能到 ~0%
            # 再被末尾硬拉满（复审实测跳过时 557MB 白占分母）
            if not _install_webview2(reader, staging, cur, say, prog, res,
                                     should_cancel=should_cancel,
                                     total=sub_total):
                sub_total = max(1, sub_total - sum(
                    int(e.get("size") or 0) for e in reader.entries
                    if e.get("kind") == "webview2"
                    and e.get("mode") != "link"))
            plan.remove("webview2")
        # 其余资源解到同一 staging（安装器需要同目录，如 node zip 与 msi 同层）
        rest = [k for k in plan]
        if rest:
            say("解包安装资源（%s）…" % "/".join(rest))
            # 从已解出的字节起步——extract_all 内部 done 从 0 计，不加重
            # 基准的话 webview2 解完后再解 rest，进度条会往回跳（N5 实测
            # 4MB → 1MB）
            base = cur[0]
            _rest_pct = [-1]
            def _rest_prog(d, t, p):
                prog(base + d, sub_total, p)
                if t > 0:
                    _p = int(d * 10 // t) * 10
                    if _p > _rest_pct[0] and _p < 100:
                        _rest_pct[0] = _p
                        prog(base + d, sub_total,
                             "解包其余 %d%%（%.0f / %.0f MB）" % (
                                 _p, d / 1048576, t / 1048576))
            reader.extract_all(staging, kinds=rest,
                               progress=_rest_prog,
                               should_cancel=should_cancel)
        total = sub_total or 1
        for k in rest:
            _ck()
            fn = _INSTALLERS.get(k)
            if not fn:
                res["skipped"].append(k)
                continue
            try:
                # a355R（第21轮）：安装器阶段没有字节进度可报（跑外部 exe /
                # 复制上万小文件，几分钟到十几分钟），此前前端进度条一动不动，
                # 形同卡死。这里先推一条「不确定进度」（done=None），装完再
                # 回到字节口径。只有支持回调的安装器才传，其余保持原签名。
                if fn in _PROGRESSIVE:
                    ok = fn(staging, say, force, prog=prog)
                else:
                    _beat = _Heartbeat(prog, k)
                    _beat.start()
                    try:
                        ok = fn(staging, say, force)
                    finally:
                        _beat.stop()
                if ok:
                    res["installed"].append(k)
                    say("✓ %s 完成" % k)
                else:
                    res["skipped"].append(k)
                    say("· %s 已存在或无需安装" % k)
            except Exception as e:
                res["errors"][k] = str(e)[:300]
                say("✗ %s 失败：%s" % (k, e))
            finally:
                # 回到字节口径：下个 kind 的进度从真实累计值继续
                prog(cur[0], total, "")
        prog(total, total, "完成")
        writer_state = {"installed_at": _now(),
                        "package": os.path.basename(path),
                        "installed": res["installed"],
                        "skipped": res["skipped"],
                        "errors": res["errors"]}
        _merge_state(writer_state)
        return res
    except fcpk.Cancelled:
        raise InstallCancelled("用户取消安装")
    finally:
        reader.close()
        if staging and os.path.isdir(staging):
            shutil.rmtree(staging, ignore_errors=True)
        # a325R：恢复而不是置 None——嵌套/重复调用时不误摘外层 sink
        _cs._log_sink = _prev_sink


# ------------------------------------------------------------------ 各资源

WV2_MARKER = ".wv2ok"          # 完整性标记：解包全程成功才写（对抗审 P0）


def _install_webview2(reader, staging, cur, say, prog, res, should_cancel=None,
                      total=None):
    """WebView2 是纯解包——不跑安装器（Fixed Version 免安装，设环境变量即用）。

    对抗审 P0 修正：早前直落 runtime_root()，断电/取消/坏段留下「exe 在
    DLL 缺」的半棵树——而闸门只探测 msedgewebview2.exe 存在性，半装被
    判「已装」后**永无自愈路径**（建窗深处无声崩溃）。现改为：旧目录先
    备份让位 → 解包 → 校验关键文件 → 写完成标记；失败恢复备份并清半成品。
    闸门侧（res_boot）只认标记。

    落点：包内 arcname 已是 `webview2/...`，解到 runtime_root() 本身
    （不是 runtime_root()/webview2，那会多套一层 webview2/webview2/）。"""
    root = runtime_root()
    os.makedirs(root, exist_ok=True)
    mark = os.path.join(root, WV2_MARKER)
    cur_dir = os.path.join(root, "webview2")
    if os.path.isfile(mark) and os.path.isdir(cur_dir):
        say("· WebView2 已完整安装，跳过（删 offline_runtime/.wv2ok 可重装）")
        return False
    bak = ""
    if os.path.isdir(cur_dir):
        import time
        bak = cur_dir + ".old-%d" % int(time.time())
        say("  现有运行时已备份 → %s" % os.path.basename(bak))
        try:
            os.replace(cur_dir, bak)
        except OSError as e:
            raise InstallError("无法替换现有运行时（可能正在使用）：%s" % e)
    try:
        if os.path.isfile(mark):
            os.remove(mark)
        say("解出 WebView2 运行时 → %s …" % cur_dir)
        # a337R（第8轮 P3-1）：进度必须从当前累计字节起算。bili 分支在
        # webview2 之前跑（解完 cur[0]≈200MB），原先这里 `d` 从 0 起 →
        # 进度条从 ~12% 跳回 0%（对比 rest 分支的 `base = cur[0]`）。
        _base = cur[0]
        _wv2_pct = [-1]
        def _wv2_prog(d, t, p):
            prog(_base + d, total or t, p)
            if t > 0:
                _p = int(d * 10 // t) * 10
                if _p > _wv2_pct[0] and _p < 100:
                    _wv2_pct[0] = _p
                    prog(_base + d, total or t,
                         "解包 WebView2 %d%%（%.0f / %.0f MB）" % (
                             _p, d / 1048576, t / 1048576))
        got = reader.extract_all(root, kinds=["webview2"],
                                 progress=_wv2_prog,
                                 should_cancel=should_cancel)
        if not any(p.endswith("msedgewebview2.exe") for p in got):
            raise InstallError("包内 WebView2 运行时不完整（缺 msedgewebview2.exe）")
        _verify_wv2_tree(root)
        with open(mark, "w", encoding="utf-8") as f:
            f.write("ok")
    except BaseException:
        # 半成品清理（对抗审 P0：半装骗闸门）——尽力而为，恢复优先
        shutil.rmtree(cur_dir, ignore_errors=True)
        try:
            if os.path.isfile(mark):
                os.remove(mark)
        except OSError:
            pass
        if bak and os.path.isdir(bak) and not os.path.isdir(cur_dir):
            try:
                os.replace(bak, cur_dir)
                say("  已恢复原运行时")
            except OSError:
                pass
        raise
    if bak:
        shutil.rmtree(bak, ignore_errors=True)
    res["installed"].append("webview2")
    say("✓ webview2 完成（%d 个文件）" % len(got))
    return True


def _verify_wv2_tree(root):
    """切换前校验关键文件在场（配合 GCM 段验签，防「exe 在 DLL 缺」）。"""
    import glob as _gl
    hits = _gl.glob(os.path.join(root, "webview2", "*",
                                 "msedgewebview2.exe"))
    if not hits:
        raise InstallError("WebView2 解包校验失败（未找到 msedgewebview2.exe）")
    ver_dir = os.path.dirname(hits[0])
    for key in ("EBWebView", "msedge.dll"):
        if not (_gl.glob(os.path.join(ver_dir, key))
                or _gl.glob(os.path.join(ver_dir, "*", key))):
            raise InstallError("WebView2 解包校验失败（缺 %s）——疑似损坏包"
                               % key)


def _install_dotnet(staging, say, force=False):
    """跑 ndp481 安装器。已满足则跳过。
    装 .NET 需要管理员；失败不致命——res_boot 下次探测仍会判缺失。

    force 刻意**不生效**：已满足时强装要管理员 + 可能要重启，收益为零。
    这条不要「优化」掉。"""
    from src.res_boot import probe_dotnet
    st = probe_dotnet()[0]
    if st == "ok":
        if force:
            say("· .NET 不支持强制重装（需管理员且可能要重启），按缺失安装")
        else:
            say("· .NET Framework 已满足当前版本，跳过")
        return False
    exe = _find(staging, "ndp481")
    if not exe:
        raise InstallError("包内无 .NET 安装器（ndp481*.exe）")
    say("安装 .NET Framework 4.8.1（1-2 分钟，可能需要管理员）…")
    import subprocess
    try:
        r = subprocess.run([exe, "/q", "/norestart"], timeout=1200,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        # WinError 740 = 安装器清单要求提权，CreateProcess 拒起（非 1603 的
        # 另一种「没管理员」形态）——给人话，别让用户看到裸 WinError
        if getattr(e, "winerror", None) == 740:
            raise InstallError(
                ".NET 安装器需要管理员权限——请以管理员身份运行工具后重试，"
                "或手动安装 .NET Framework 4.8.1")
        raise
    say("安装器退出码 %d" % r.returncode)
    # 3010 = 成功但需重启（对抗审 P2：早前 3010 也立即复验——重启前注册表
    # 必然未更新必报失败，把用户锁进重试循环；现 3010 直接判成功并明说）
    if r.returncode == 3010:
        say("✓ .NET 安装成功（需重启 Windows 后生效）")
        return True
    if r.returncode != 0:
        if r.returncode in (1603, 5, 740):
            raise InstallError(
                ".NET 安装被拒（退出码 %d，多因无管理员权限）——请以管理员"
                "身份运行工具后重试，或手动安装 .NET Framework 4.8.1"
                % r.returncode)
        raise InstallError("安装器退出码 %d（0/3010 为成功）" % r.returncode)
    if probe_dotnet()[0] != "ok":
        raise InstallError(".NET 装完仍未检测到——可能要重启后再试")
    return True


def _install_node(staging, say, force=False):
    from src import claude_setup as cs
    if not force and (shutil.which("node.exe") or shutil.which("node")):
        say("· Node 已存在，跳过")
        return False
    if force and (shutil.which("node.exe") or shutil.which("node")):
        say("· Node 已存在，强制重装（MSI 就地升级；无权限时退化为解压覆盖）")
    msi = _find(staging, "node-v", ".msi")
    if not msi:
        raise InstallError("包内无 Node 安装器")
    cs._install_node_from(msi)      # 内部含 MSI 1603 → zip 免安装版兜底
    if not (shutil.which("node.exe") or shutil.which("node")):
        raise InstallError("Node 安装失败（MSI 无权限且包内无 zip）")
    return True


def _install_git(staging, say, force=False):
    from src import claude_setup as cs
    if not force and cs._git_ok():
        say("· Git 已存在，跳过")
        return False
    if force and cs._git_ok():
        say("· Git 已存在，强制重装（Inno 静默覆盖）")
    exe = _find(staging, "Git-", ".exe")
    if not exe:
        raise InstallError("包内无 Git 安装器")
    cs._install_git_from(exe)
    if not cs._git_ok():
        raise InstallError("Git 安装失败")
    return True


def _install_codegraph(staging, say, force=False, prog=None):
    """a360（用户令工具内置）：codegraph 平台 bundle 铺到 %APPDATA%\\npm\\
    node_modules\\@colbymchenry\\codegraph-win32-x64（npm 标准位——用户日后
    npm install -g 可无缝覆盖升级；bundle 自带 node.exe，零 npm 依赖运行）。
    幂等：版本相同跳过；旧版本先备份成功后删（claude 同款 B4 教训）。"""
    import json
    import time
    src = os.path.join(staging, "codegraph")
    if not os.path.isfile(os.path.join(src, "node.exe")):
        raise InstallError("包内无 codegraph 目录（缺 node.exe）——资源包版本过旧")

    def _ver(d):
        try:
            with open(os.path.join(d, "lib", "package.json"), encoding="utf-8") as f:
                return json.load(f).get("version") or ""
        except Exception:
            return ""

    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        raise InstallError("无 APPDATA 环境变量")
    dst = os.path.join(appdata, "npm", "node_modules", "@colbymchenry",
                       "codegraph-win32-x64")
    if not force and _ver(src) and _ver(src) == _ver(dst):
        say("codegraph %s 已是最新，跳过" % _ver(dst))
        return
    say("复制 codegraph → %s（约 250MB）…" % dst)
    bak = ""
    if os.path.isdir(dst):
        bak = dst + ".old-%d" % int(time.time())
        try:
            os.replace(dst, bak)
        except OSError as e:
            raise InstallError("无法替换现有 codegraph（可能正在运行）：%s" % e)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        if prog:
            prog(None, 0, "复制 codegraph（%d 个文件）" % _count_files(src))
        _copy_tree_with_links(
            src, dst,
            progress=(lambda n, t: prog(n, t, "复制 codegraph")) if prog else None)
    except Exception:
        # R34-3R（复验维持实锤：node.exe 是 walk+sorted 复制顺序第一个文件，
        # 多数失败形态它已落盘 →「缺 node.exe」判定恒 False 不还原——残缺
        # 安装被幂等判断读残缺 package.json 误判「已是最新」永久化）。
        # 失败分支无条件清场：有 bak 恒还原；无 bak 清掉残缺 dst（下次
        # 重装全新复制，不落半成品）
        try:
            import shutil as _sh2
            if os.path.isdir(dst):
                _sh2.rmtree(dst, ignore_errors=True)
            if bak and os.path.isdir(bak):
                os.replace(bak, dst)   # 失败自动搬回（claude B4 同款）
                say("  安装失败，已还原原有 codegraph")
            else:
                say("  安装失败，已清除残缺副本")
        except OSError:
            pass
        raise
    if bak:
        import shutil as _sh
        try:
            _sh.rmtree(bak)
        except OSError:
            pass
    say("✓ codegraph %s 安装完成" % _ver(dst))


def _install_claude(staging, say, force=False, prog=None):
    """铺 claude-code 包到 %APPDATA%\\npm\\node_modules（npm 标准位）+ shim。

    全审 B4/B5 实锤（严重）两处修正：
    - 早前先 rmtree 目标再 copytree，装出空壳（包内只有 exe）时等于把
      用户**现有可用安装**替换成坏的；改为先搬到 .old-<ts> 备份，成功后
      删，失败自动搬回。
    - 早前经 shutil.copytree 从 staging 复制，硬链接不保留 → claude.exe
      两份 540MB 各自落盘，"省空间"承诺失效。改为自己遍历，按 fcpk 的
      link 语义在同卷用 os.link（跨卷自动退化 copy2）。
    - 补 _verify_claude_runs 硬验证：装上≠能跑，装坏的必须报错而不是报成功。
    """
    from src import claude_setup as cs
    src = os.path.join(staging, "claude-code")
    if not os.path.isdir(os.path.join(src, "bin")):
        raise InstallError("包内无 claude-code 目录（或含 bin 子目录）")
    if not os.path.isfile(os.path.join(src, "package.json")):
        raise InstallError("包内 claude-code 不完整（缺 package.json）——"
                           "资源包版本过旧，请用新版工具重新打包")

    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        raise InstallError("无 APPDATA 环境变量")
    dst = os.path.join(appdata, "npm", "node_modules", "@anthropic-ai",
                       "claude-code")

    say("复制 claude-code → %s（几百 MB，需几分钟）…" % dst)
    bak = ""
    if os.path.isdir(dst):
        import time
        bak = dst + ".old-%d" % int(time.time())
        say("  现有安装已备份 → %s" % os.path.basename(bak))
        try:
            os.replace(dst, bak)
        except OSError as e:
            raise InstallError("无法替换现有 claude-code（可能正在运行）：%s" % e)
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    try:
        # a355R（第21轮）：复制 685MB / 12000+ 小文件在 Windows 上要几分钟，
        # 此前没有任何反馈。按文件数报进度（字节口径在这里失真：硬链接不
        # 产生字节，剩下几万个 link 会让百分比永远差一截）。
        if prog:
            prog(None, 0, "复制 claude-code（%d 个文件）" % _count_files(src))
        _copy_tree_with_links(
            src, dst,
            progress=(lambda n, t: prog(n, t, "复制 claude-code"))
            if prog else None)
        cs._make_npm_shims(dst)
        cs._ensure_npm_path()
        try:
            import src.claude_conn as cc
            cc._exe_cache = None
        except Exception:
            pass
        say("  验证 claude --version …")
        cs._verify_claude_runs(os.path.join(dst, "bin", "claude.exe"))
    except Exception:
        # 失败回滚（对抗审 P1）：早前 rmtree(ignore_errors) 后目录非空时
        # os.replace(目录) 必败且被静默吞——现有安装被毁还不报。现：清不净
        # 就把半成品改名让路，恢复失败必须说出来
        shutil.rmtree(dst, ignore_errors=True)
        if bak and os.path.isdir(bak):
            try:
                if os.path.isdir(dst):
                    import time as _t
                    os.replace(dst, dst + ".broken-%d" % int(_t.time()))
                os.replace(bak, dst)
                say("  已回滚到原有安装")
            except OSError as e:
                say("  回滚失败：%s（原备份仍在 %s）" % (e, bak))
        raise
    if bak:
        shutil.rmtree(bak, ignore_errors=True)
    return True


def _count_files(root):
    """目录树里的文件数（进度分母用；数不清按 0 处理，只影响显示）。"""
    n = 0
    try:
        for _r, _d, fs in os.walk(root):
            n += len(fs)
    except OSError:
        pass
    return n


def _copy_tree_with_links(src, dst, progress=None):
    """复制目录树，**保留包内的同内容去重**（fcpk 写入时的 link entry）。

    打包侧对两个字节相同的 claude.exe 只存一份、另一条标 link；解到
    staging 时用 os.link 落地。这里如果直接 copytree 就会把硬链接拆成
    两份独立文件（270MB×2）。做法：先按 size+inode 记录「已复制源」，
    目标树上遇到同 inode 的源就 os.link 到已落地的那个；跨卷失败退
    化 copy2。绝不因链接失败阻断安装。

    a355R（第21轮）：加 progress(n, total)——claude 685MB / 12000+ 小文件
    的复制在 Windows 上要几分钟，此前**零反馈**，用户只能硬等（实锤：
    设置页进度条停在解包完成的位置一动不动）。按文件数推进，不按字节——
    os.link 不产生字节、按字节算末尾几万个链接会让进度永远差一点。
    """
    os.makedirs(dst, exist_ok=True)
    total = _count_files(src)
    done = 0
    seen = {}       # (st_dev, st_ino) -> 已落地的目标路径
    for r, ds, fs in os.walk(src):
        ds.sort()
        rel = os.path.relpath(r, src)
        out_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out_dir, exist_ok=True)
        for f in sorted(fs):
            sp = os.path.join(r, f)
            dp = os.path.join(out_dir, f)
            done += 1
            try:
                st = os.stat(sp)
            except OSError:
                if progress:
                    progress(done, total)
                continue
            key = (st.st_dev, st.st_ino)
            prev = seen.get(key)
            if prev and os.path.isfile(prev):
                try:
                    os.link(prev, dp)
                    if progress:
                        progress(done, total)
                    continue
                except OSError:
                    pass        # 跨卷/不支持 → 落到下面正常复制
            shutil.copy2(sp, dp)
            seen[key] = dp
            if progress:
                progress(done, total)


def _install_pydeps(staging, say, force=False):
    from src import claude_setup as cs
    d = os.path.join(staging, "pydeps")
    if not os.path.isdir(d):
        return False
    before = os.listdir(d)
    if not any(f.endswith((".whl", ".tar.gz")) for f in before):
        return False
    cs._install_pydeps(d)
    return True



def _bili_reprobe(say=None):
    """装完即时重探（对抗审 a206B P2）：proxy 的 BILI_NODE/ENTRY/ERR 是
    模块加载时一次性赋值——不重探则装完仍报"未安装"，需重启工具。"""
    try:
        from src import proxy as _px
        _px.bili_reprobe()
        if say: say("· 压缩引擎检测已刷新（无需重启工具）")
    except Exception as e:
        if say: say("· 压缩引擎检测刷新失败（重启工具后生效）：%s" % e)


def _install_onlyoffice(staging, say, force=False):
    """OnlyOffice DS（a309R：word/excel/ppt 全功能编辑）。可选组件——
    已装跳过；包内安装器静默装（Inno /VERYSILENT，弹 UAC 确认框约 10 分钟
    含字体生成）。失败只记 errors 不阻断其余资源（res_install 编排语义）"""
    from src.res_boot import probe_onlyoffice
    st, _v, _m = probe_onlyoffice()
    if st == "ok":
        say("· OnlyOffice DS 已安装（localhost:80 在线），跳过")
        return False
    if force:
        say("· OnlyOffice 强制重装（静默覆盖）")
    exe = _find(staging, "onlyoffice-documentserver", ".exe")
    if not exe:
        raise InstallError("包内无 OnlyOffice 安装器")
    import subprocess as _sp
    say("静默安装 OnlyOffice DS（873MB，含字体生成约 10 分钟）…")
    say("  将弹 UAC 提权确认框，请点「是」")
    rc = _sp.call([exe, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
                  creationflags=0x08000000, timeout=1800)
    st2, _v2, _m2 = probe_onlyoffice()
    if rc != 0 and st2 != "ok":
        raise InstallError("OnlyOffice 安装失败（退出码 %s）——可手动安装：%s"
                           % (rc, exe))
    return True


# ------------------------------------------------------------------ 工具

def _find(root, *parts):
    """在 staging 里按**文件名片段**找（包内文件名带版本号）。

    全审 A4 实锤（致命）：早前 `pat = "".join(parts)` 把 ("node-v",".msi")
    拼成 `node-v.msi` 再 `*node-v.msi*`——真实文件名 `node-v24.19.0-x64.msi`
    永远不匹配，node/git 离线安装 100% 失败。正确做法是每段都当独立片段
    做 `*片段*` 再串联。"""
    import glob
    pat = "*" + "*".join(parts) + "*"
    hits = [h for h in glob.glob(os.path.join(root, "**", pat),
                                 recursive=True) if os.path.isfile(h)]
    return sorted(hits)[-1] if hits else ""


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


def _merge_state(d):
    from src import res_boot
    res_boot._write_state(d)


_INSTALLERS = {"dotnet": _install_dotnet, "node": _install_node,
               "git": _install_git, "claude": _install_claude,
               "codegraph": _install_codegraph,
               "onlyoffice": _install_onlyoffice,
               "pydeps": _install_pydeps}
# a355R（第21轮）：支持进度回调的安装器（claude 是逐文件复制，能报真实
# 文件数；其余是跑外部安装器或 pip，只能报「不确定进度」+ 心跳）。
_PROGRESSIVE = {_install_claude}

# 安装器名称（前端「不确定进度」提示用）
_INSTALL_LABEL = {"dotnet": ".NET Framework", "node": "Node.js", "git": "Git",
                  "codegraph": "Claude 代码图引擎（codegraph）",
                  "onlyoffice": "OnlyOffice（约 10 分钟，请留意 UAC 弹窗）",
                  "pydeps": "Python 依赖"}


class _Heartbeat:
    """跑外部安装器期间的「心跳」：每 2 秒推一次不确定进度。

    a355R（第21轮）：`subprocess.call(exe, /VERYSILENT)` 会阻塞 10 分钟，
    期间零进度事件，前端进度条静止不动，用户以为卡死。心跳只改文案里的
    秒数，不碰百分比（done=None）。
    """
    def __init__(self, prog, kind):
        self.prog = prog
        self.label = _INSTALL_LABEL.get(kind, kind)
        self._stop = threading.Event()
        self._th = None

    def start(self):
        def _run():
            t0 = time.time()
            while not self._stop.wait(2.0):
                self.prog(None, 0, "%s · 已等待 %d 秒"
                          % (self.label, int(time.time() - t0)))
        self._th = threading.Thread(target=_run, daemon=True)
        self._th.start()

    def stop(self):
        self._stop.set()
        if self._th:
            self._th.join(timeout=2.0)
# 注：bili 不走这张表——它的落点在 runtime_root()（不经 staging/move），
# 由 install_from 单独分支处理（a336R 第7轮 P3-1：原表里的 bili 是死路径）


# ------------------------------------------------------------------ 在线安装
# a322 批2（用户需求：有网时工具内直接装，不强制离线包）。URL 与
# offline_assets/MANIFEST.json 同源；离线包通道不受任何影响。

ONLINE_URLS = {
    "node": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi",
    "node_zip": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip",
    "git": ("https://github.com/git-for-windows/git/releases/download/"
            "v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe"),
    # a595（用户定调「在线安装必须可靠」）：dotnet 换 fwlink 稳定跳转。
    # 原来写死 download.visualstudio.microsoft.com/pr/<guid>/<hash>/ 直链——
    # 微软会轮换 PR 路径令牌，链接死了（实测直连+代理都 400，非用户网络
    # 问题，winget-pkgs#278129 同款）。fwlink 是微软永久重定向，实测
    # 200 → download.microsoft.com 稳定路径。
    "dotnet": "https://go.microsoft.com/fwlink/?linkid=2203305",
    # WebView2 Evergreen standalone 引导器（微软官方稳定 fwlink；Fixed 版
    # 直链 2025-01 起下架，在线场景 Evergreen 由系统自更新维护）
    "webview2": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
}
# 无稳定官方直链的 kind（在线通道明确跳过并指路离线包）
ONLINE_UNSUPPORTED = {"bili", "onlyoffice"}


def net_check(kinds=None):
    """在线安装预检：**镜像感知**（a595 二批）。

    每个 kind 探「实际会用的候选源」：解析后的首位源（镜像档位决定）+
    官方直链，任一可达即 ok——镜像通、官方被墙的机器不再被误报「源不可
    达」。npm/pip 作为独立键返回（claude/codegraph/pydeps 的真实网络面，
    前端 netOk 据此映射）。缓存 60s，改镜像档时由 mirror 端点清缓存。
    返回 {kind: {"ok": bool, "code": int, "err": str, "via": url}}。
    """
    import urllib.request
    want = list(kinds) if kinds else ["node", "git", "dotnet", "webview2",
                                      "npm", "pip"]
    out = {}
    for k in want:
        if k in ONLINE_UNSUPPORTED:
            out[k] = {"ok": False, "code": 0, "via": "",
                      "err": "无官方稳定直链——请用离线包安装"}
            continue
        if k == "claude":   # npm registry（走 install 时的 node/npm）
            sub = out.get("npm") or net_check(["npm"]).get("npm", {})
            out[k] = dict(sub)
            continue
        if k == "npm":
            regs = _mirrors().npm_registry_list()
            urls = _dedup([regs[0], regs[-1]])   # 首选源 + 官方兜底
        elif k == "pip":
            urls = _dedup([_mirrors().pip_index_list()[0],
                           _mirrors().pip_index_list()[-1]])
        elif k == "node":
            c = cs_node_candidates()
            urls = _dedup([c[0], c[-1]])
        elif k == "git":
            c = cs_git_candidates()
            urls = _dedup([c[0], c[-1]])
        else:
            url = ONLINE_URLS.get(k)
            urls = [url] if url else []
            if not url:
                out[k] = {"ok": False, "code": 0, "via": "",
                          "err": "未知资源"}
                continue
        ok, code, err, via = False, 0, "", ""
        for u in urls:
            code, err = 0, ""
            try:
                req = urllib.request.Request(
                    u, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    code = resp.status
            except Exception as e:
                # 有些 CDN 拒 HEAD（400/405）——range 小 GET 再判
                try:
                    req = urllib.request.Request(
                        u, headers={"Range": "bytes=0-0",
                                    "User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        code = resp.status
                except Exception as e2:
                    err = str(getattr(e2, "reason", e2) or e2)[:120]
            if code in (200, 206, 302, 301):
                ok, via = True, u
                break
        out[k] = {"ok": ok, "code": code, "err": err, "via": via}
    return out


def _dedup(seq):
    seen, out = set(), []
    for x in seq:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def cs_node_candidates():
    """node 安装器候选 URL（镜像档位序）——claude_setup 单一真源。"""
    from src import claude_setup as cs
    return cs._node_msi_candidates()


def cs_git_candidates():
    from src import claude_setup as cs
    return cs._git_exe_candidates()


def _mirrors():
    """src/mirrors 注册表访问（惰性；档位实时读 config，改档即时生效）。"""
    from src import mirrors
    return mirrors


def install_online(kinds, log=None, progress=None, should_cancel=None,
                   force=False):
    """在线安装依赖（有网直接装）。镜像源按 src/mirrors.py 档位
    （默认智能镜像优先），下载失败自动逐源重试。镜像 install_from 的约定：
    log/progress/should_cancel/单 kind 容错/返回结构。

    - node/git：cs._install_*_if_missing（本地 offline_assets 资源优先，
      缺则镜像/官方直链下载；MSI 提权失败自动 zip 兜底）
    - claude/codegraph：确保 node → npm 逐源重试 → 运行/探测验证
    - dotnet：下载 ndp481 → 复用 _install_dotnet 静默装（微软 fwlink 官方直链）
    - webview2：下载 Evergreen standalone → /silent /install（同上）
    - pydeps：源码形态 pip 逐源装；exe 形态不支持（引导离线包）
    - bili/onlyoffice：无稳定直链，skipped 指路离线包
    """
    from src import claude_setup as cs
    say = log or (lambda _m: None)
    # 镜像计划先说清楚（用户定调「优先镜像加速，给出提示」）——安装面板
    # 日志首行即当前下载源策略，改档后这里跟着变
    say(_mirrors().describe())
    cur = [0]

    def prog(done, total, label=""):
        cur[0] = done
        if progress:
            progress(done, total, label)

    def _ck():
        if should_cancel and should_cancel():
            raise InstallCancelled("用户取消安装")

    want = [k for k in ORDER if k in set(kinds)]
    # a332R（P3-2）：与 install_from 保持同一返回结构（含 absent），
    # 否则调用方要做两套判定。在线通道不存在"包内缺资源"，恒为空。
    res = {"installed": [], "skipped": [], "errors": {}, "absent": []}
    dl_dir = os.path.join(tempfile.gettempdir(), "fc_online_install")
    os.makedirs(dl_dir, exist_ok=True)

    # claude_setup 的日志/下载进度接到本次 say（monkeypatch，finally 还原）
    orig_log = cs._log
    cs._log = say
    try:
        import subprocess as _sp
        total = len(want) or 1
        for k in want:
            _ck()
            try:
                ok = False
                if k == "bili" or k == "onlyoffice":
                    # a325R（第2轮对抗审 P2）：原来只 say 一句，ok=False 又
                    # 被下面的显式排除挡住——三项结果都不记，res.result 里
                    # 凭空消失，落盘的 installed/skipped 与实际不符。
                    say("跳过 %s：官方无稳定直链——请用离线包装（四档预设含该项）" % k)
                    res["skipped"].append(k)
                elif k == "pydeps":
                    if getattr(__import__("sys"), "frozen", False):
                        raise InstallError("exe 形态不支持在线装 pydeps——请用离线包")
                    # a595 二批：装 _TOOL_DEPS_ONLINE（含 pycryptodome，装完
                    # 资源包功能自愈）；index 候选按用户镜像档位排出
                    # （默认清华优先）逐个重试，全部失败才判失败
                    import sys as _sys
                    _pip_base = [_sys.executable, "-m", "pip", "install",
                                 "--no-input", "--timeout", "30"]
                    indexes = _mirrors().pip_index_list()
                    r = None
                    for i, idx in enumerate(indexes):
                        say("pip 安装工具依赖 %s（源 %d/%d：%s）…"
                            % (", ".join(cs._TOOL_DEPS_ONLINE),
                               i + 1, len(indexes), idx))
                        r = _sp.run(_pip_base + ["-i", idx]
                                    + list(cs._TOOL_DEPS_ONLINE),
                                    capture_output=True, text=True, timeout=900)
                        if r.returncode == 0:
                            break
                        say("  该源失败（退出码 %s）%s"
                            % (r.returncode,
                               "，换下一源…" if i < len(indexes) - 1 else "，无更多源"))
                    for line in (r.stdout or "").splitlines()[-5:]:
                        say("  " + line)
                    if r.returncode != 0:
                        raise InstallError("pip 退出码 %s" % r.returncode)
                    ok = True
                elif k == "node":
                    say("在线安装 Node（本地资源优先，缺则官方直链）…")
                    # a325R（对抗审 P2）：_install_node_if_missing 一看到已装就
                    # return True，force 完全无效。force 走 _install_node_from
                    # 真跑安装器。R12-2（实锤：装好却报失败）：不再回头
                    # _find_installer（dl_dir 不在其搜索位且下载名对不上
                    # pattern 必 miss）——本地 miss 直接官方直链下到明确
                    # 路径并用它装
                    if force:
                        say("  强制重装：重跑 Node 安装器（可能弹管理员提示）")
                        _msi = cs._find_installer("node-v*.msi")
                        if not (_msi and os.path.isfile(_msi)):
                            _msi = os.path.join(dl_dir, "node-v24.19.0-x64.msi")
                            if not os.path.isfile(_msi):
                                cs._download(cs._NODE_URL, _msi,
                                             mirrors=cs._node_msi_candidates())
                        cs._install_node_from(_msi)
                        ok = bool(shutil.which("node.exe") or shutil.which("node"))
                    else:
                        ok = bool(cs._install_node_if_missing(dl_dir))
                elif k == "git":
                    say("在线安装 Git（本地资源优先，缺则官方直链）…")
                    if force:
                        say("  强制重装：重跑 Git 安装器（可能弹管理员提示）")
                        # R12-2：同 node——直链兜底，不问 _find_installer
                        _gx = cs._find_installer("Git-*.exe")
                        if not (_gx and os.path.isfile(_gx)):
                            _gx = os.path.join(dl_dir, "Git-64-bit.exe")
                            if not os.path.isfile(_gx):
                                cs._download(cs._GIT_URL, _gx,
                                             mirrors=cs._git_exe_candidates())
                        cs._install_git_from(_gx)
                        ok = bool(cs._git_ok())
                    else:
                        ok = bool(cs._install_git_if_missing(dl_dir))
                elif k == "claude":
                    # a450：已装则走 npm update（只拉版本差异），不再每次全量
                    # install -g；强制重装才走 install。
                    if force:
                        say("强制重装 Claude CLI：确保 Node → npm install -g …")
                    else:
                        say("在线安装/更新 Claude CLI：确保 Node → npm update -g …")
                    cs._install_node_if_missing(dl_dir)
                    cs._npm_install_global(force=force)
                    # a452（第二轮审计 P2）：清缓存必须放在 install **之后**。
                    # 原来清在 install 之前（分钟级），安装期间任何线程
                    # （server 状态接口、前端打开 Claude 会话）解析一次就把
                    # 旧路径重新填回缓存，装后 probe 复用的还是它。
                    try:
                        import src.claude_conn as _cc
                        _cc._exe_cache = None
                    except Exception:
                        pass
                    from src.res_boot import probe_claude
                    st, v, _m = probe_claude()
                    # a452：unknown=探测没跑出结论（超时/杀毒首扫），不是失败。
                    # 把慢机上的好安装报成 InstallError 会让用户白白重装。
                    if st == "unknown":
                        say("Claude CLI 已装，--version 探测超时（%s）——"
                            "首次运行/杀毒扫描常见，稍后可在资源状态里复查" % _m)
                        ok = True
                    elif st != "ok":
                        raise InstallError("npm 装完但 claude 不可用（%s）"
                                           % (_m or v or "未知原因"))
                    else:
                        ok = True
                elif k == "dotnet":
                    say("下载 .NET 4.8.1 安装器（微软 fwlink 稳定直链，约 74MB）…")
                    exe = os.path.join(dl_dir, "ndp481-online.exe")
                    cs._download(ONLINE_URLS["dotnet"], exe)
                    ok = bool(_install_dotnet(dl_dir, say, force))
                elif k == "codegraph":
                    # a595（用户定调「在线安装必须可靠，无条件能装」）：
                    # codegraph=npm 平台包 @colbymchenry/codegraph-win32-x64
                    # （自带 node.exe 的 bundle），npm 全局装即 nav_codegraph
                    # ._cg_argv 命中①位（%APPDATA%\npm\node_modules）。
                    # 此前 install_online 无此分支——勾选后被静默 skip（实锤）。
                    # 免提权同 claude 分支：npm_config_prefix 钉到用户目录。
                    say("在线安装 codegraph：确保 Node → npm install -g 平台包 …")
                    cs._install_node_if_missing(dl_dir)
                    _, npm = cs._node_ok()
                    if not npm:
                        raise InstallError("node/npm 不可用——先装 Node")
                    appdata = os.environ.get("APPDATA", "")
                    env = dict(os.environ)
                    env["npm_config_prefix"] = os.path.join(appdata, "npm")
                    env["npm_config_cache"] = os.path.join(appdata, "npm-cache")
                    # a595 二批：registry 候选按用户镜像档位（默认 npmmirror
                    # 优先）逐个重试；列表循环外定死一次防中途改档漂移
                    regs = _mirrors().npm_registry_list()
                    r = None
                    for i, reg in enumerate(regs):
                        r = _sp.run([npm, "install", "-g",
                                     "@colbymchenry/codegraph-win32-x64",
                                     "--registry=" + reg],
                                    capture_output=True, text=True,
                                    timeout=900, env=env,
                                    creationflags=0x08000000)
                        if r.returncode == 0:
                            break
                        say("  registry %s 失败（退出码 %s）%s"
                            % (reg, r.returncode,
                               "，换下一源…" if i < len(regs) - 1 else "，无更多源"))
                    for line in (r.stdout or "").splitlines()[-3:]:
                        say("  " + line)
                    if r.returncode != 0:
                        raise InstallError(
                            "npm 退出码 %s：%s" % (r.returncode,
                            (r.stderr or r.stdout or "")[-160:]))
                    from src.res_boot import _PROBES as _PB
                    st, v, _m = _PB["codegraph"]()
                    if st != "ok":
                        raise InstallError("npm 装完但 codegraph 探测未通过（%s）"
                                           % (_m or v or "未知"))
                    say("✓ codegraph %s" % (v or "安装完成"))
                    ok = True
                elif k == "webview2":
                    say("下载 WebView2 Evergreen 引导器（微软 fwlink）…")
                    exe = os.path.join(dl_dir, "MicrosoftEdgeWebview2Setup.exe")
                    cs._download(ONLINE_URLS["webview2"], exe)
                    say("静默安装 WebView2 Evergreen …")
                    try:
                        rc = _sp.call([exe, "/silent", "/install"],
                                      creationflags=0x08000000, timeout=600)
                    except OSError as e:
                        # WinError 740 = 安装器要求提权（Evergreen 是 per-machine
                        # 安装），CreateProcess 直接拒起——给人话而非裸 WinError
                        if getattr(e, "winerror", None) == 740:
                            raise InstallError(
                                "WebView2 安装器需要管理员权限——请以管理员身份"
                                "运行工具后重试，或改用离线资源包（Fixed Version "
                                "免提权）")
                        raise
                    from src.res_boot import probe_webview2
                    st, v, _m = probe_webview2()
                    if st != "ok" and rc != 0:
                        raise InstallError("WebView2 安装失败（退出码 %s）" % rc)
                    ok = st == "ok"
                if ok:
                    res["installed"].append(k)
                    say("✓ %s 完成" % k)
                elif k not in res["errors"] and k not in ("bili", "onlyoffice"):
                    res["skipped"].append(k)
            except InstallCancelled:
                raise
            except Exception as e:
                res["errors"][k] = str(e)[:300]
                say("✗ %s 失败：%s（无网/被代理拦请改用离线包安装）" % (k, e))
            prog(min(cur[0] + 1, total), total, k)
        prog(total, total, "完成")
        _merge_state({"installed_at": _now(), "package": "在线安装",
                      "installed": res["installed"],
                      "skipped": res["skipped"],
                      "errors": res["errors"]})
        return res
    finally:
        cs._log = orig_log
        # 下载目录留给后续增量安装复用（几 MB~百 MB 级，TEMP 自清理范畴）

