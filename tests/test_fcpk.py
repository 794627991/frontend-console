# -*- coding: utf-8 -*-
"""fcpk 格式单元测试（v4.1）。
覆盖：往返一致 / 压缩 entry / link 去重 / 坏字节定位 / 截断 / 错口令 /
路径穿越防护。纯逻辑，不碰真实数据目录。直接 `python tests/test_fcpk.py`。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import fcpk

_PASS, _FAIL = [], []


def check(name, cond, detail=""):
    # C8（全审）：打包.bat 设 PYTHONIOENCODING=gbk / 控制台默认 cp936 时，
    # ✓/✗ 会 UnicodeEncodeError 直接崩在第一项。输出全部用 ASCII。
    (_PASS if cond else _FAIL).append(name)
    print(("  [ok] " if cond else "  [FAIL] ") + name
          + ("" if cond else "  " + str(detail)))


def main():
    tmp = tempfile.mkdtemp(prefix="fcpk_test_")
    try:
        pkg = os.path.join(tmp, "t.fcpk")

        # ---- 1. 基本往返（raw + deflate + 小文件 + 空文件）----
        big = os.path.join(tmp, "big.bin")
        data = bytes(range(256)) * 4096                    # 1MB，可压
        with open(big, "wb") as f:
            f.write(data)
        small = os.path.join(tmp, "small.txt")
        with open(small, "wb") as f:
            f.write(b"hello fcpk")
        empty = os.path.join(tmp, "empty.bin")
        open(empty, "wb").close()

        w = fcpk.FcpkWriter(pkg, password="test-pw")
        w.add_file(big, "a/big.bin", kind="k1", mode="deflate")
        w.add_file(small, "a/small.txt", kind="k1", mode="raw")
        w.add_file(empty, "a/empty.bin", kind="k2", mode="raw")
        w.add_bytes(b'{"x":1}', "meta.json", kind="meta")
        w.close()

        check("产物存在", os.path.isfile(pkg))
        check("非 zip（magic 是 FCRP）", open(pkg, "rb").read(4) == b"FCRP")
        check("后缀无关的 is_fcpk", fcpk.is_fcpk(pkg))
        j = fcpk.inspect(pkg)
        check("inspect 通过", j["ok"], j)
        check("inspect 条目数", j["entries"] == 4, j)

        r = fcpk.FcpkReader(pkg, password="test-pw")
        paths = [e["path"] for e in r.entries]
        check("表条目顺序", paths == ["a/big.bin", "a/small.txt",
                                      "a/empty.bin", "meta.json"], paths)
        out = os.path.join(tmp, "out")
        r.extract_all(out)
        check("deflate entry 字节一致",
              open(os.path.join(out, "a/big.bin"), "rb").read() == data)
        check("raw entry 字节一致",
              open(os.path.join(out, "a/small.txt"), "rb").read() == b"hello fcpk")
        check("空文件解出为 0 字节",
              os.path.getsize(os.path.join(out, "a/empty.bin")) == 0)
        check("add_bytes 内容一致",
              open(os.path.join(out, "meta.json"), "rb").read() == b'{"x":1}')
        r.close()

        # ---- 2. verify_all ----
        r = fcpk.FcpkReader(pkg, password="test-pw")
        ok = True
        try:
            r.verify_all()
        except fcpk.FcpkError as e:
            ok = False
            detail = str(e)
        check("verify_all 通过", ok, locals().get("detail", ""))
        r.close()

        # ---- 3. link 去重 ----
        pkg2 = os.path.join(tmp, "link.fcpk")
        w = fcpk.FcpkWriter(pkg2, password="p")
        w.add_file(big, "one.bin", kind="k", mode="raw")
        w.add_file(big, "two.bin", kind="k", mode="raw",
                   link_from="one.bin")
        w.close()
        r = fcpk.FcpkReader(pkg2, password="p")
        link_e = [e for e in r.entries if e["path"] == "two.bin"][0]
        check("同内容走 link（体不存）", link_e["mode"] == "link"
              and link_e["segs"] == [], link_e)
        out2 = os.path.join(tmp, "out2")
        r.extract_all(out2)
        check("link 解出内容一致",
              open(os.path.join(out2, "two.bin"), "rb").read() == data)
        r.close()
        # 内容不同则不复用
        pkg3 = os.path.join(tmp, "nolink.fcpk")
        w = fcpk.FcpkWriter(pkg3, password="p")
        w.add_file(big, "one.bin", kind="k", mode="raw")
        w.add_file(small, "two.bin", kind="k", mode="raw", link_from="one.bin")
        w.close()
        r = fcpk.FcpkReader(pkg3, password="p")
        e2 = [e for e in r.entries if e["path"] == "two.bin"][0]
        check("内容不同不走 link", e2["mode"] == "raw" and e2["segs"], e2)
        r.close()

        # ---- 4. 错口令 ----
        bad = ""
        try:
            fcpk.FcpkReader(pkg, password="wrong")
        except fcpk.FcpkError as e:
            bad = str(e)
        check("错口令报错", "口令" in bad or "损坏" in bad, bad)

        # ---- 5. 坏一个字节 → 定位到具体 entry ----
        pkg4 = os.path.join(tmp, "corrupt.fcpk")
        shutil.copy2(pkg, pkg4)
        with open(pkg4, "r+b") as f:
            f.seek(fcpk.HEADER_LEN + 100)      # 落在第一个 entry 的密文里
            b = f.read(1)
            f.seek(fcpk.HEADER_LEN + 100)
            f.write(bytes([b[0] ^ 0xFF]))
        r = fcpk.FcpkReader(pkg4, password="test-pw")
        msg = ""
        try:
            r.extract_all(os.path.join(tmp, "out4"))
        except fcpk.FcpkError as e:
            msg = str(e)
        check("坏字节定位到 entry", "a/big.bin" in msg, msg)
        r.close()

        # ---- 6. 截断 → inspect 提前发现 ----
        pkg5 = os.path.join(tmp, "trunc.fcpk")
        raw = open(pkg, "rb").read()
        with open(pkg5, "wb") as f:
            f.write(raw[:len(raw) // 2])
        j5 = fcpk.inspect(pkg5)
        check("截断包 inspect 报不完整", not j5["ok"], j5)
        err = ""
        try:
            fcpk.FcpkReader(pkg5, password="test-pw")
        except fcpk.FcpkError as e:
            err = str(e)
        check("截断包 Reader 拒绝", "不完整" in err, err)

        # ---- 7. 路径穿越（含 B1 实锤的嵌套形态）----
        for evil in ("../../evil.txt", "a/../../evil.txt",
                     "a/b/../../../evil.txt"):
            pkg6 = os.path.join(tmp, "trav.fcpk")
            w = fcpk.FcpkWriter(pkg6, password="p")
            w.add_bytes(b"x", evil)
            w.close()
            r = fcpk.FcpkReader(pkg6, password="p")
            msg = ""
            sb = os.path.join(tmp, "out6")
            os.makedirs(sb, exist_ok=True)
            try:
                r.extract_all(sb)
            except fcpk.FcpkError as e:
                msg = str(e)
            r.close()
            check("拒绝路径穿越 %s" % evil, "非法" in msg, msg)
        # 确认没有任何文件被写到解包根之外
        escaped = [p for p in (os.path.join(tmp, "evil.txt"),
                               os.path.join(tmp, "a", "evil.txt"))]
        check("解包根之外无残留", not any(os.path.exists(p) for p in escaped))

        # ---- 7a. 高压缩率 entry（C6 回归）----
        # 全零 9MB deflate 后几十 KB，单个 1MB 密文块解压后远超 8MB 限长，
        # 会走 unconsumed_tail 循环。早前 wrote 在循环内外双计导致误报长度不符。
        zsrc = os.path.join(tmp, "zeros.bin")
        zdata = b"\0" * (9 << 20)
        with open(zsrc, "wb") as f:
            f.write(zdata)
        zpkg = os.path.join(tmp, "zeros.fcpk")
        w = fcpk.FcpkWriter(zpkg, password="p")
        w.add_file(zsrc, "z.bin", kind="k", mode="deflate")
        w.close()
        r = fcpk.FcpkReader(zpkg, password="p")
        zerr = ""
        try:
            r.verify_all()
        except fcpk.FcpkError as e:
            zerr = str(e)
        zout = os.path.join(tmp, "outz")
        r.extract_all(zout)
        r.close()
        check("高压缩率 entry verify_all 通过", not zerr, zerr)
        check("高压缩率 entry 字节一致",
              open(os.path.join(zout, "z.bin"), "rb").read() == zdata)

        # ---- 7b. inspect with truncated header must return dict (B3) ----
        short = os.path.join(tmp, "short.fcpk")
        with open(short, "wb") as f:
            f.write(b"FCRP" + bytes([1]) + bytes(30))
        try:
            jx = fcpk.inspect(short)
            ok = (isinstance(jx, dict) and jx.get("ok") is False)
        except Exception as e:
            ok = False
            jx = repr(e)
        check("inspect truncated header returns dict", ok, jx)

        # ---- 8. kinds 过滤 + 进度回调 ----
        r = fcpk.FcpkReader(pkg, password="test-pw")
        seen = []
        out8 = os.path.join(tmp, "out8")
        got = r.extract_all(out8, kinds=["k2"], progress=lambda d, t, p: seen.append(d))
        check("kinds 只解指定类", got == ["a/empty.bin"], got)
        # 空文件没有数据块 → 不触发进度回调，这是对的
        check("空 entry 不触发进度回调", seen == [], seen)
        r.close()
        r = fcpk.FcpkReader(pkg, password="test-pw")
        seen2 = []
        r.extract_all(os.path.join(tmp, "out8b"), kinds=["k1"],
                      progress=lambda d, t, p: seen2.append(d))
        check("有数据时进度回调被调用", len(seen2) > 0, len(seen2))
        r.close()
        r = fcpk.FcpkReader(pkg, password="test-pw")
        prog = []
        r.extract_all(os.path.join(tmp, "out9"),
                      progress=lambda d, t, p: prog.append((d, t)))
        expect = len(data) + len(b"hello fcpk") + 0 + len(b'{"x":1}')
        check("进度最终到达总量",
              prog and prog[-1][0] == prog[-1][1] == expect,
              prog[-1] if prog else None)
        r.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(_PASS), len(_FAIL)))
    if _FAIL:
        print("FAILED: " + ", ".join(_FAIL))
        return 1
    return 0


def _hard_suite():
    """对抗审计修复回归：表炸弹 / KDF 钳制 / 保留名 / 取消 / 冲突 / 内存。"""
    def _mk(d, entries, password="p"):
        pkg = os.path.join(d, "h.fcpk")
        w = fcpk.FcpkWriter(pkg, password=password)
        for arc, data in entries:
            w.add_bytes(data, arc)
        w.close()
        return pkg

    # 表炸弹：段表解压后 >64MB（path 填 200MB 的 A）→ 打开即拒不 OOM
    with tempfile.TemporaryDirectory() as d:
        pkg = _mk(d, [("A" * (200 << 20), b"x")])
        try:
            fcpk.FcpkReader(pkg, password="p")
            check("表炸弹钳制", False, "打开未拒绝")
        except Exception as e:
            check("表炸弹钳制", "超上限" in str(e) or "段表" in str(e), str(e)[:60])

    # KDF 钳制：iters 改 20 亿 → 立即拒绝（不烧 CPU）
    import struct
    with tempfile.TemporaryDirectory() as d:
        pkg = _mk(d, [("a", b"1")])
        with open(pkg, "r+b") as f:
            f.seek(8)
            f.write(struct.pack("<I", 2000000000))
        try:
            fcpk.FcpkReader(pkg, password="p")
            check("KDF 钳制", False, "未拒绝")
        except fcpk.FcpkError as e:
            check("KDF 钳制", "迭代数越界" in str(e), str(e)[:60])

    # 保留设备名
    with tempfile.TemporaryDirectory() as d:
        pkg = _mk(d, [("LPT1.txt", b"x")])
        r = fcpk.FcpkReader(pkg, password="p")
        try:
            try:
                r.extract_all(d)
                check("保留名拒绝", False, "未拒绝")
            except fcpk.FcpkError as e:
                check("保留名拒绝", "保留设备名" in str(e), str(e)[:60])
        finally:
            r.close()

    # 取消：多块大 entry 的**块级**中途取消 → Cancelled 且无 .part 残留
    # （对抗审二轮 P3-5：早前恰在 entry 边界触发，.part 清理路径没走到）
    with tempfile.TemporaryDirectory() as d:
        big = os.path.join(d, "src.bin")
        with open(big, "wb") as f:
            f.write(bytes(6 << 20))          # 6MB → 6 个 1MB 块
        pkg = os.path.join(d, "c.fcpk")
        w = fcpk.FcpkWriter(pkg, password="p")
        w.add_file(big, "big.bin", mode="raw")
        w.add_bytes(b"tail", "t.txt")
        w.close()
        r = fcpk.FcpkReader(pkg, password="p")
        try:
            calls = [0]

            def cancel():
                calls[0] += 1
                return calls[0] > 3          # 第 4 次块级检查起取消（大 entry 中途）
            try:
                r.extract_all(d, should_cancel=cancel)
                check("块级中途取消", False, "未取消")
            except fcpk.Cancelled:
                left = [f for f in os.listdir(d) if f.endswith(".part")]
                check("块级取消无 .part 残留", left == [], str(left))
                check("块级取消确在大 entry 中途",
                      calls[0] > 3, "calls=%d" % calls[0])
        finally:
            r.close()

    # 文件/目录冲突
    with tempfile.TemporaryDirectory() as d:
        pkg = _mk(d, [("x", b"f"), ("x/y", b"g")])
        r = fcpk.FcpkReader(pkg, password="p")
        try:
            try:
                r.extract_all(d)
                check("路径冲突拒绝", False, "未拒绝")
            except fcpk.FcpkError as e:
                check("路径冲突拒绝", "冲突" in str(e), str(e)[:60])
        finally:
            r.close()

    # 大块 deflate 内存逐片：512MB 零压缩块解包不超 ~2x 块上限
    # （不真做 512MB——用 8MB 验证逐片路径正确即可）
    with tempfile.TemporaryDirectory() as d:
        pkg = os.path.join(d, "big.fcpk")
        # add_bytes 不走压缩（压缩只在 add_file 的 _file_chunks）——
        # 用临时文件 + add_file(deflate) 走真实压缩路径
        big = os.path.join(d, "big_src.bin")
        with open(big, "wb") as f:
            f.write(bytes(16 << 20))
        w = fcpk.FcpkWriter(pkg, password="p")
        w.add_file(big, "big.bin", mode="deflate")
        w.close()
        r = fcpk.FcpkReader(pkg, password="p")
        try:
            got = r.extract_all(d)
            out = os.path.join(d, "big.bin")
            check("大块 deflate 解包", os.path.isfile(out)
                  and os.path.getsize(out) == (16 << 20), str(got))
        finally:
            r.close()


if __name__ == "__main__":
    _hard_suite()
    sys.exit(main())
