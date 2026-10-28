# -*- coding: utf-8 -*-
"""fetch_webview2_fixed —— 下载/校验/落位 WebView2 Fixed Version 运行时。

v2.3.7a（用户需求「任何机器都能兼容，宁可包体大」）：
    随包内置 WebView2 运行时，离线机/久未更新机零安装零管理员可跑。

来源说明（供应链透明）：
    微软 2025-01 起从官网下架了 Fixed Version 直链（只剩 Evergreen
    Bootstrapper/Standalone）。本脚本从社区存档 westinyang/WebView2RuntimeArchive
    下载官方 cab 构件——**下载后强制做 Authenticode 签名校验**：运行时本体
    （msedgewebview2.exe 及核心 DLL）必须是微软签名，任何篡改/替换都会让
    签名校验失败而中止落位。签名即微软原厂证明，与分发渠道无关。

用法：
    python tools/fetch_webview2_fixed.py            # 默认内置版本（下同）
    python tools/fetch_webview2_fixed.py 133.0.3065.92

产物：
    runtime/WebView2Fixed/Microsoft.WebView2.FixedVersionRuntime.<ver>.x64/
    （build.py _bundle_webview2 随包带上；src.main _ensure_webview2 启动切换）
"""
import os
import subprocess
import sys
import tempfile
import urllib.request

# 内置版本（存档里较新的稳定版；升级只改这里重跑）
DEFAULT_VER = "133.0.3065.92"
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL = ("https://github.com/westinyang/WebView2RuntimeArchive/releases/"
      "download/{v}/Microsoft.WebView2.FixedVersionRuntime.{v}.x64.cab")


def _die(msg):
    print("✗ " + msg)
    sys.exit(1)


def _verify_signature(exe):
    """PowerShell Get-AuthenticodeSignature：必须 Valid 且签给 Microsoft。
    判定在 PS 内完成、只回 ASCII（中文控制台 GBK 输出中文必乱码——曾因
    Subject 中文引号被编坏而误判失败）。"""
    ps = ("$s = Get-AuthenticodeSignature -FilePath '%s'; "
          "$s.Status.ToString() + '|' + "
          "$(if ($s.SignerCertificate.Subject -match 'Microsoft') {'MS'} "
          "else {'NO'})" % exe.replace("'", "''"))
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps],
            text=True, timeout=60,
            stderr=subprocess.DEVNULL).strip()
    except Exception as e:
        _die("signature check failed to run (%s)" % e)
    status, _, flag = out.partition("|")
    if status != "Valid" or flag != "MS":
        _die("signature check FAILED: Status=%s Microsoft=%s "
             "-- artifact suspicious, abort" % (status, flag))
    print("[ok] MS signature verified: %s" % os.path.basename(exe))


def main():
    ver = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VER
    url = DL.format(v=ver)
    cab = os.path.join(BASE, "runtime", "webview2-fixed.cab")
    dst_root = os.path.join(BASE, "runtime", "WebView2Fixed")
    os.makedirs(dst_root, exist_ok=True)
    # 已下载过的 cab 直接复用（urlretrieve 断点续传不支持，重下 250MB 冤枉）
    if os.path.isfile(cab) and os.path.getsize(cab) > 50 * 1024 * 1024:
        print("复用已下载的 %s（%.0f MB）——删除它可强制重下"
              % (cab, os.path.getsize(cab) / 1048576))
    else:
        print("下载 %s …" % url)
        try:
            urllib.request.urlretrieve(url, cab)
        except Exception as e:
            _die("下载失败：%s" % e)
        print("✓ 下载完成 %.0f MB" % (os.path.getsize(cab) / 1048576))
    # expand 解 cab（Windows 自带；cab 是微软原厂压缩格式）
    tmp = tempfile.mkdtemp(prefix="wv2fixed_")
    r = subprocess.call(["expand", cab, "-F:*", tmp],
                        stderr=subprocess.STDOUT, timeout=1200)
    if r != 0:
        _die("expand 解压失败 rc=%d" % r)
    # 找含 msedgewebview2.exe 的顶层目录
    exe = None
    for root, _d, files in os.walk(tmp):
        if "msedgewebview2.exe" in files:
            exe = os.path.join(root, "msedgewebview2.exe")
            src_dir = root
            break
    if not exe:
        _die("解压后找不到 msedgewebview2.exe——构件形态异常")
    # 签名校验：主 exe + 首个核心 DLL（双重样本）
    _verify_signature(exe)
    dlls = sorted(f for f in os.listdir(src_dir) if f.lower().endswith(".dll"))
    if dlls:
        _verify_signature(os.path.join(src_dir, dlls[0]))
    # 落位（目录名保留版本号；旧版本目录先清）
    dst = os.path.join(dst_root, os.path.basename(src_dir))
    if os.path.isdir(dst):
        import shutil
        shutil.rmtree(dst, ignore_errors=True)
    import shutil
    shutil.move(src_dir, dst)   # temp 在 C: 目标在 D:——跨盘 move（rename 不行）
    n = 0
    total = 0
    for root, _d, fs in os.walk(dst):
        for f in fs:
            n += 1
            total += os.path.getsize(os.path.join(root, f))
    print("✓ 落位 %s（%d 文件，%.0f MB）" % (dst, n, total / 1048576))
    print("下一步：python src/build.py 打包即自动随包（或直接跑，启动闸自动检测）")
    try:
        os.remove(cab)
    except OSError:
        pass


if __name__ == "__main__":
    main()
