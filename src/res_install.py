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

from src import fcpk

# 各 kind 在包内的目录前缀（与打包侧一致）
_KIND_DIRS = {"webview2": "webview2/", "dotnet": "install/",
              "node": "install/", "git": "install/",
              "claude": "claude-code/", "pydeps": "pydeps/"}

# 安装顺序：先决条件在前
ORDER = ["dotnet", "webview2", "node", "git", "claude", "pydeps"]


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

    返回 {"installed": [...], "skipped": [...], "errors": {kind: msg}}
    单个资源装失败**不中断**其余——某个装不上（比如无管理员装不了 .NET）
    不该把已经装好的 Node 也回滚。
    """
    say = log or (lambda _m: None)
    cur = [0]

    def prog(done, total, label=""):
        cur[0] = done
        if progress:
            progress(done, total, label)

    info = fcpk.inspect(path)
    if not info.get("ok"):
        raise InstallError(info.get("err") or "资源包无法读取")
    say("资源包：%.0f MB，%d 个文件" % (info["size"] / 1048576.0,
                                       info.get("entries", 0)))

    want = [k for k in ORDER if (kinds is None or k in kinds)]
    res = {"installed": [], "skipped": [], "errors": {}}

    def _ck():
        if should_cancel and should_cancel():
            raise InstallCancelled("用户取消安装")

    reader = fcpk.FcpkReader(path)
    staging = None
    try:
        have = {e["kind"] for e in reader.entries}
        plan = [k for k in want if k in have]
        for k in want:
            if k not in have:
                res["skipped"].append(k)
                say("跳过 %s：包内不含该资源" % k)

        staging = tempfile.mkdtemp(prefix="fcpk_stage_")
        _ck()
        if "webview2" in plan:
            _install_webview2(reader, staging, cur, say, prog, res,
                              should_cancel=should_cancel)
            plan.remove("webview2")
        # 其余资源解到同一 staging（安装器需要同目录，如 node zip 与 msi 同层）
        rest = [k for k in plan]
        if rest:
            say("解包安装资源（%s）…" % "/".join(rest))
            reader.extract_all(staging, kinds=rest,
                               progress=lambda d, t, p: prog(d, t, p),
                               should_cancel=should_cancel)
        total = info.get("plain_len") or 1
        for k in rest:
            _ck()
            fn = _INSTALLERS.get(k)
            if not fn:
                res["skipped"].append(k)
                continue
            try:
                if fn(staging, say, force):
                    res["installed"].append(k)
                    say("✓ %s 完成" % k)
                else:
                    res["skipped"].append(k)
                    say("· %s 已存在或无需安装" % k)
            except Exception as e:
                res["errors"][k] = str(e)[:300]
                say("✗ %s 失败：%s" % (k, e))
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


# ------------------------------------------------------------------ 各资源

WV2_MARKER = ".wv2ok"          # 完整性标记：解包全程成功才写（对抗审 P0）


def _install_webview2(reader, staging, cur, say, prog, res, should_cancel=None):
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
        got = reader.extract_all(root, kinds=["webview2"],
                                 progress=lambda d, t, p: prog(d, t, p),
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
    r = subprocess.run([exe, "/q", "/norestart"], timeout=1200,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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


def _install_claude(staging, say, force=False):
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
        _copy_tree_with_links(src, dst)
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
                say("  ⚠ 回滚失败：%s（原备份仍在 %s）" % (e, bak))
        raise
    if bak:
        shutil.rmtree(bak, ignore_errors=True)
    return True


def _copy_tree_with_links(src, dst):
    """复制目录树，**保留包内的同内容去重**（fcpk 写入时的 link entry）。

    打包侧对两个字节相同的 claude.exe 只存一份、另一条标 link；解到
    staging 时用 os.link 落地。这里如果直接 copytree 就会把硬链接拆成
    两份独立文件（270MB×2）。做法：先按 size+inode 记录「已复制源」，
    目标树上遇到同 inode 的源就 os.link 到已落地的那个；跨卷失败退
    化 copy2。绝不因链接失败阻断安装。
    """
    os.makedirs(dst, exist_ok=True)
    seen = {}       # (st_dev, st_ino) -> 已落地的目标路径
    for r, ds, fs in os.walk(src):
        ds.sort()
        rel = os.path.relpath(r, src)
        out_dir = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(out_dir, exist_ok=True)
        for f in sorted(fs):
            sp = os.path.join(r, f)
            dp = os.path.join(out_dir, f)
            try:
                st = os.stat(sp)
            except OSError:
                continue
            key = (st.st_dev, st.st_ino)
            prev = seen.get(key)
            if prev and os.path.isfile(prev):
                try:
                    os.link(prev, dp)
                    continue
                except OSError:
                    pass        # 跨卷/不支持 → 落到下面正常复制
            shutil.copy2(sp, dp)
            seen[key] = dp


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


_INSTALLERS = {"dotnet": _install_dotnet, "node": _install_node,
               "git": _install_git, "claude": _install_claude,
               "pydeps": _install_pydeps}


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
