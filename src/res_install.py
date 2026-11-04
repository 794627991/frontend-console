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
# 对抗审 a206B P3：_KIND_DIRS 全仓无消费（死配置）——包内前缀与释放路径
# 的一致性由打包/安装两侧约定保证（build.py 的 arc 前缀 ↔ 各 installer
# 的落位），此处删除防误导。约定备忘：webview2→webview2/、bili→bili/、
# dotnet/node/git→install/、claude→claude-code/、pydeps→pydeps/

# 安装顺序：先决条件在前
ORDER = ["dotnet", "webview2", "node", "git", "claude", "bili",
           "onlyoffice", "pydeps"]


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
        if "bili" in plan:
            bili_root = runtime_root()
            os.makedirs(bili_root, exist_ok=True)
            say("解包 billion-context（Node 运行时 + 依赖树）…")
            reader.extract_all(bili_root, kinds=["bili"],
                               progress=lambda d, t, p2: prog(
                                   cur[0] + d, sub_total, p2),
                               should_cancel=should_cancel)
            _install_bili(bili_root, say, force)
            plan.remove("bili")
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
            reader.extract_all(staging, kinds=rest,
                               progress=lambda d, t, p: prog(
                                   base + d, sub_total, p),
                               should_cancel=should_cancel)
        total = sub_total or 1
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
        got = reader.extract_all(root, kinds=["webview2"],
                                 progress=lambda d, t, p: prog(
                                     d, total or t, p),
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


def _install_bili(root, say, force=False):
    """billion-context 安装收尾：extract_all 已把 bili/ 树解到 runtime_root()
    （对抗审 a206B：不再从 staging 整目录 move——跨卷必炸）。本函数做三件事：
    ①运行中拒绝（bili 在跑时升级=从运行进程脚下抽走 node_modules，实测
    exe 镜像锁不阻止目录改名，其余 12k 文件会被 rmtree 删光——压缩链路
    静默损坏）；②关键文件校验 + .biliok 标记；③让 proxy 重探（装完即可
    用，不重启）。"""
    mark = os.path.join(root, ".biliok")
    cur_dir = os.path.join(root, "bili")
    if os.path.isfile(mark) and os.path.isdir(cur_dir) and not force:
        say("· billion-context 已完整安装，跳过（删 offline_runtime/.biliok 可重装）")
        _bili_reprobe(say)
        return False
    node_exe = os.path.join(cur_dir, "node.exe")
    entry = os.path.join(cur_dir, "node_modules", "billion-context",
                         "dist", "index.js")
    if not (os.path.isfile(node_exe) and os.path.isfile(entry)):
        # extract_all 半途（取消/坏段）——清残不写标记，下次自愈重装
        import shutil
        shutil.rmtree(cur_dir, ignore_errors=True)
        raise InstallError("bili 资源不完整（缺 node.exe 或 dist/index.js）")
    # 运行中升级防护：18788 活着 = bili 在跑（升级=抽梯，先拒）
    import socket as _sk
    try:
        with _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM) as _s:
            _s.settimeout(0.4)
            if _s.connect_ex(("127.0.0.1", 18788)) == 0:
                raise InstallError("billion-context 正在运行——请先在代理面板"
                                   "把压缩模式切为关闭（或退出工具）再升级")
    except OSError:
        pass
    with open(mark, "w", encoding="utf-8") as f:
        f.write(_now())
    say("✓ billion-context 就位（Node 运行时 + 依赖树）")
    _bili_reprobe(say)
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
    say("  ⚠ 将弹 UAC 提权确认框，请点「是」")
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
               "bili": _install_bili,
               "git": _install_git, "claude": _install_claude,
               "onlyoffice": _install_onlyoffice,
               "pydeps": _install_pydeps}


# ------------------------------------------------------------------ 在线安装
# a326 批2（用户需求：有网时工具内直接装，不强制离线包）。URL 与
# offline_assets/MANIFEST.json 同源；离线包通道不受任何影响。

ONLINE_URLS = {
    "node": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-x64.msi",
    "node_zip": "https://nodejs.org/dist/v24.19.0/node-v24.19.0-win-x64.zip",
    "git": ("https://github.com/git-for-windows/git/releases/download/"
            "v2.55.0.windows.5/Git-2.55.0.5-64-bit.exe"),
    "dotnet": ("https://download.visualstudio.microsoft.com/download/pr/"
               "6a893f45-0810-4b11-9051-3b9ef0d1cf0e/4d6923c759e4cc4d34438f2b"
               "57f4c06/ndp481-x86-x64-allos-enu.exe"),
    # WebView2 Evergreen standalone 引导器（微软官方稳定 fwlink；Fixed 版
    # 直链 2025-01 起下架，在线场景 Evergreen 由系统自更新维护）
    "webview2": "https://go.microsoft.com/fwlink/p/?LinkId=2124703",
}
# 无稳定官方直链的 kind（在线通道明确跳过并指路离线包）
ONLINE_UNSUPPORTED = {"bili", "onlyoffice"}


def net_check(kinds=None):
    """在线安装预检：各 URL 小超时 HEAD（部分 CDN 拒 HEAD 时小 GET 兜底）。
    返回 {kind: {"ok": bool, "code": int, "err": str}}。给前端禁用态用。"""
    import urllib.request
    want = list(kinds) if kinds else ["node", "git", "dotnet", "webview2"]
    out = {}
    for k in want:
        if k in ONLINE_UNSUPPORTED:
            out[k] = {"ok": False, "code": 0,
                      "err": "无官方稳定直链——请用离线包安装"}
            continue
        if k == "claude":   # npm registry（走 install 时的 node）；预检含 node
            out[k] = net_check(["node"]).get("node", {"ok": False, "code": 0,
                                                      "err": "?"})
            continue
        url = ONLINE_URLS.get(k)
        if not url:
            out[k] = {"ok": False, "code": 0, "err": "未知资源"}
            continue
        code, err = 0, ""
        try:
            req = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                code = resp.status
        except Exception as e:
            # 有些 CDN 拒 HEAD（400/405）——range 小 GET 再判
            try:
                req = urllib.request.Request(
                    url, headers={"Range": "bytes=0-0",
                                  "User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    code = resp.status
            except Exception as e2:
                err = str(getattr(e2, "reason", e2) or e2)[:120]
        out[k] = {"ok": code in (200, 206), "code": code, "err": err}
    return out


def install_online(kinds, log=None, progress=None, should_cancel=None,
                   force=False):
    """在线安装依赖（有网直接装）。镜像 install_from 的约定：
    log/progress/should_cancel/单 kind 容错/返回结构。

    - node/git：cs._install_*_if_missing（本地 offline_assets 资源优先，
      缺则官方直链下载；MSI 提权失败自动 zip 兜底）
    - claude：确保 node → npm install -g @anthropic-ai/claude-code（免提权
      prefix）→ 运行验证
    - dotnet：下载 ndp481 → 复用 _install_dotnet 静默装
    - webview2：下载 Evergreen standalone → /silent /install
    - pydeps：源码形态 pip 在线装；exe 形态不支持（引导离线包）
    - bili/onlyoffice：无稳定直链，skipped 指路离线包
    """
    from src import claude_setup as cs
    say = log or (lambda _m: None)
    cur = [0]

    def prog(done, total, label=""):
        cur[0] = done
        if progress:
            progress(done, total, label)

    def _ck():
        if should_cancel and should_cancel():
            raise InstallCancelled("用户取消安装")

    want = [k for k in ORDER if k in set(kinds)]
    res = {"installed": [], "skipped": [], "errors": {}}
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
                    say("pip 在线安装工具依赖 %s …" % cs._TOOL_DEPS)
                    import sys as _sys
                    r = _sp.run([_sys.executable, "-m", "pip", "install",
                                 *cs._TOOL_DEPS],
                                capture_output=True, text=True, timeout=900)
                    for line in (r.stdout or "").splitlines()[-5:]:
                        say("  " + line)
                    if r.returncode != 0:
                        raise InstallError("pip 退出码 %s" % r.returncode)
                    ok = True
                elif k == "node":
                    say("在线安装 Node（本地资源优先，缺则官方直链）…")
                    # a325R（对抗审 P2）：_install_node_if_missing 一看到已装就
                    # return True，force 完全无效，却报「✓ node 完成」。force
                    # 时改走 _install_node_from（真跑安装器）。
                    if force:
                        say("  强制重装：重跑 Node 安装器（可能弹管理员提示）")
                        _msi = cs._find_installer("node-v*.msi")
                        if not (_msi and os.path.isfile(_msi)):
                            cs._install_node_if_missing(dl_dir)   # 缺安装器先补
                            _msi = cs._find_installer("node-v*.msi")
                        if _msi and os.path.isfile(_msi):
                            cs._install_node_from(_msi)
                        else:
                            raise InstallError(
                                "强制重装 Node 需要安装器（node-v*.msi）——"
                                "本地资源目录没有，请改用离线资源包")
                        ok = bool(shutil.which("node.exe") or shutil.which("node"))
                    else:
                        ok = bool(cs._install_node_if_missing(dl_dir))
                elif k == "git":
                    say("在线安装 Git（本地资源优先，缺则官方直链）…")
                    if force:
                        say("  强制重装：重跑 Git 安装器（可能弹管理员提示）")
                        _gx = cs._find_installer("Git-*.exe")
                        if not (_gx and os.path.isfile(_gx)):
                            cs._install_git_if_missing(dl_dir)
                            _gx = cs._find_installer("Git-*.exe")
                        if _gx and os.path.isfile(_gx):
                            cs._install_git_from(_gx)
                        else:
                            raise InstallError(
                                "强制重装 Git 需要安装器（Git-*.exe）——"
                                "本地资源目录没有，请改用离线资源包")
                        ok = bool(cs._git_ok())
                    else:
                        ok = bool(cs._install_git_if_missing(dl_dir))
                elif k == "claude":
                    say("在线安装 Claude CLI：确保 Node → npm install -g …")
                    cs._install_node_if_missing(dl_dir)
                    cs._npm_install_global()
                    from src.res_boot import probe_claude
                    st, v, _m = probe_claude()
                    if st != "ok":
                        raise InstallError("npm 装完但 claude 不可用（%s）" % v)
                    ok = True
                elif k == "dotnet":
                    say("下载 .NET 4.8.1 安装器（约 74MB，内网代理可能拦微软 CDN）…")
                    exe = os.path.join(dl_dir, "ndp481-online.exe")
                    cs._download(ONLINE_URLS["dotnet"], exe)
                    ok = bool(_install_dotnet(dl_dir, say, force))
                elif k == "webview2":
                    say("下载 WebView2 Evergreen 引导器（微软 fwlink）…")
                    exe = os.path.join(dl_dir, "MicrosoftEdgeWebview2Setup.exe")
                    cs._download(ONLINE_URLS["webview2"], exe)
                    say("静默安装 WebView2 Evergreen …")
                    rc = _sp.call([exe, "/silent", "/install"],
                                  creationflags=0x08000000, timeout=600)
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

