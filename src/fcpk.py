# -*- coding: utf-8 -*-
"""`.fcpk` 离线资源包格式核心（v4.1，用户拍板：统一自定义加密容器）。

为什么不用标准 zip + 密码（用户否决 pyzipper）：
- 标准 AES zip 要引第三方库，且 7-Zip/WinRAR 输密码就能打开、资源管理器
  双击直接展开——「防止用户错误打开」的目的达不到。
- 自定义容器：magic 不是 zip，资源管理器/7z/tar 一律拒绝；段表也加密，
  hexdump 连文件名和目录结构都看不到；后缀 `.fcpk` 未注册关联，双击只会
  弹「选择打开方式」。只有本工具能解。

文件布局（全程流式，内存恒等 chunk_size，不随包体增长）：

    +0x000  HEADER 64B（明文）
    +0x040  SEGMENT 0..N-1（每帧 = 密文 clen + 16B tag，顺序排布）
    +T      TABLE_BLOB（AES-GCM 密文 + 16B tag）   ← 段表在**末尾**
    EOF-32  FOOTER 32B

段表放末尾而不是开头：开头放表会导致「写体时还不知道各段长度，写完再
插到前面」= 整个 620MB 包要搬运一遍。放末尾则零搬运，close() 只需追加
表 + footer 再 seek(0) 回填 64 字节头。

HEADER 布局（小端）：
    0  4B  magic  b"FCRP"        28 16B header_mac
    4  1B  ver    1              44 4B  table_len
    5  1B  flags                  48 4B  chunk_size
    6  2B  salt_len               52 8B  total_plain_len
    8  4B  kdf_iter               60 4B  entry_count
    12 16B salt

AAD 策略：每段的 AAD = b"FCPK-SEG" || path || seg_no(4B) || chunk_idx(4B)。
**不含头部字节**——头部完整性由 header_mac 单独保证（改一个字节 MAC 即
失败），这样就不需要「占位头与真头逐字节一致」这种脆弱约束。

架构取舍：
- 明文字头 → 不解密就能判「是不是 fcpk / 是否截断」。
- 每段独立 GCM（nonce 含段号+块号、AAD 绑 path）→ 段级完整性、坏字节
  能定位到具体文件、且不能跨 entry 剪贴重组。
- mode=link：同内容大文件只存一份（claude.exe 两份各 258MB），解包时
  硬链接补齐；跨盘/失败自动退化复制。
"""
import hashlib
import hmac
import json
import os
import shutil
import struct
import zlib

from Crypto.Cipher import AES

MAGIC = b"FCRP"
TABLE_MAGIC = b"FCT1"
FOOTER_MAGIC = b"FCFN"
VERSION = 1
HEADER_LEN = 64
FOOTER_LEN = 32
CHUNK_SIZE = 1 << 20          # 1MB
TAG_LEN = 16
DEFAULT_ITER = 300000
# 解压膨胀上限（C6 包炸弹防护）：单块最多 8MB、单 entry 最多 4GB
_MAX_OUT_PER_CHUNK = 8 << 20
_MAX_OUT_PER_ENTRY = 4 << 30
_MAX_TABLE = 64 << 20          # 段表解压后上限（正常 <100KB，恶意包防 OOM）
_MAX_TOTAL_OUT = 32 << 30      # 单次解包总量上限（跨 entry 配额）
_KDF_ITERS_MIN, _KDF_ITERS_MAX = 10000, 2000000   # 预认证 DoS 钳制
_AAD_TAG = b"FCPK-SEG"

# 口令来源（对抗审修正）：**仓库与源码不再包含任何口令**——旧版把一个
# 固定口令异或混淆后写在源里（且与 secure_boot 的口令同源），等于公开：
# 任何人可解包、可伪造完全合法的包，全部 MAC/GCM 对主动攻击失效。
# 现取值优先级：环境变量 FCPK_PW > 构建期生成的 src/_fcpk_key.py
# （gitignored，build.py --offline 首次自动生成随机密钥并复用，保证旧包
# 可读）。拿到发行 exe 的人仍可提取（PYC 可反编译）——本容器的定位是
# 「防误开/防随手解包」的混淆层，不承诺对抗逆向的保密性。
_KEY_MODULE = "_fcpk_key"


def _password():
    pw = os.environ.get("FCPK_PW")
    if pw:
        return pw
    try:
        mod = __import__(__package__ + "." + _KEY_MODULE,
                         fromlist=[_KEY_MODULE]) if __package__             else __import__(_KEY_MODULE)
        return mod.BUILD_KEY
    except Exception:
        raise FcpkError(
            "缺少资源包密钥（src/_fcpk_key.py）——先跑 "
            "python src/build.py --offline 生成，或设 FCPK_PW 环境变量")


def _over(data, wrote, path):
    """单 entry 解压输出是否超上限。用减法比较避免大数相加溢出，
    并留出余量：宁可早报错，也不让超量字节先落盘。"""
    return len(data) > _MAX_OUT_PER_ENTRY - wrote


class FcpkError(Exception):
    """格式/口令/完整性错误——调用方直接给人话展示。"""


class Cancelled(Exception):
    """解包被取消（对抗审 P1：保留名挂死/长解包不可取消的接线位）。"""


# --------------------------------------------------------------------- 密钥

def _derive(pwd, salt, iters):
    """口令 → 主密钥 → 三把用途隔离的子密钥（表/头/段各一把）。"""
    km = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iters, 64)
    h = lambda tag: hmac.new(km, tag, hashlib.sha256).digest()[:32]
    return (h(b"fcpk/table/v1"), h(b"fcpk/header/v1"), h(b"fcpk/segment/v1"))


def _seg_nonce(k_seg, seg_no, chunk_idx):
    """段 nonce：包级前缀(4B) || 段号(4B) || 块号(4B) || 0(4B)。
    GCM 复用 nonce 等于密钥灭顶——段号/块号进 nonce 保证同密钥下唯一。"""
    pre = hmac.new(k_seg, b"nonce", hashlib.sha256).digest()[:4]
    return pre + struct.pack("<III", seg_no & 0xFFFFFFFF,
                             chunk_idx & 0xFFFFFFFF, 0)


def _seg_aad(path, seg_no, chunk_idx):
    return (_AAD_TAG + path.encode("utf-8")
            + struct.pack("<II", seg_no & 0xFFFFFFFF,
                          chunk_idx & 0xFFFFFFFF))


# --------------------------------------------------------------------- 头

def _pack_header(salt, iters, table_len, total, entry_count):
    buf = bytearray(HEADER_LEN)
    buf[0:4] = MAGIC
    buf[4] = VERSION
    buf[5] = 1                        # flags: footer_present
    struct.pack_into("<H", buf, 6, len(salt))
    struct.pack_into("<I", buf, 8, iters)
    buf[12:12 + len(salt)] = salt
    struct.pack_into("<I", buf, 44, table_len)
    struct.pack_into("<I", buf, 48, CHUNK_SIZE)
    struct.pack_into("<Q", buf, 52, total)
    struct.pack_into("<I", buf, 60, entry_count)
    return bytes(buf)


def _mac_input(buf):
    """MAC 覆盖面：header[0:28] + header[44:64]。

    全审 B2 实锤（严重）：早前只对 buf[:28] 做 MAC，而 table_len(44)/
    chunk(48)/total(52)/entry_count(60) 全在覆盖之外——文件头注释宣称
    「改一个字节 MAC 即失败」不成立（实测把 entry_count 改成 999，Reader
    照常打开、verify_all 也过）。这里把这三项也纳入（中间 16B 是 MAC
    自身，不能自我覆盖）。"""
    return bytes(buf[:28]) + bytes(buf[44:64])


def _sign(buf, k_hdr):
    """把 header[28:44] 填成对 _mac_input 的 HMAC，返回完整 64B 头。"""
    mac = hmac.new(k_hdr, _mac_input(buf), hashlib.sha256).digest()[:16]
    return bytes(buf[:28]) + mac + bytes(buf[44:])


def _parse_header(head):
    if len(head) < HEADER_LEN:
        raise FcpkError("资源包不完整（头部被截断）")
    if head[0:4] != MAGIC:
        raise FcpkError("不是资源包（文件头不匹配）——请选择 .fcpk 资源包")
    if head[4] != VERSION:
        raise FcpkError("资源包版本不支持（v%d）——请升级工具" % head[4])
    salt_len = struct.unpack_from("<H", head, 6)[0]
    return {
        "salt": head[12:12 + salt_len],
        "iters": struct.unpack_from("<I", head, 8)[0],
        "mac": head[28:44],
        "table_len": struct.unpack_from("<I", head, 44)[0],
        "chunk": struct.unpack_from("<I", head, 48)[0],
        "total": struct.unpack_from("<Q", head, 52)[0],
        "entries": struct.unpack_from("<I", head, 60)[0],
    }


def is_fcpk(path):
    """只看前 4 字节——用户选错文件时给友好提示，不用走完整解析。"""
    try:
        with open(path, "rb") as f:
            return f.read(4) == MAGIC
    except OSError:
        return False


def pkg_class(name):
    """资源包分类：'full' | 'subset' | None。

    a336R（第7轮 P1-1，实锤回归）：本函数原先放在 update_server.py，而该模块
    被 tools/cythonize_build.py 的 _EXCLUDE 排除出发布包——frozen 机上
    `from src.update_server import pkg_class` 必然 ImportError，autofind 落到
    fallback 分支把 `-资源包-拓展` / `-资源包-v2` 全丢掉，同事机明明有包却
    报「没有选择资源包」。挪到 fcpk.py（两侧本就依赖、零副作用、发布包内存在）。

    判定只看 basename（目录名不参与——第5轮 P2-1 的教训），且归一化空白：
    浏览器重名下载会产出 `资源包 (1).fcpk` / `资源包 - 副本.fcpk`。

      full   : `…资源包.fcpk`（含重名空白变体）
               或 `资源包-v<数字>[.数字]*.fcpk`（用户给新版全量包带版本后缀）
      subset : 其余含 `资源包-` 的（`-资源包-拓展`、`-资源包-claude` …）
    """
    import re as _re
    b = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if not b.endswith(".fcpk"):
        return None
    # 归一化空白 / 括号，吃下浏览器重名下载的形态（`资源包 (1).fcpk`）
    t = _re.sub(r"[\s()（）]+", "", b)
    if "资源包" not in t:
        return None
    # a336R（第7轮 P2-3）：归一化后 `资源包 (1).fcpk` 变成 `资源包1.fcpk`，
    # 原先只认 `资源包.fcpk` 会漏 → 允许结尾带数字的重名序号
    if _re.search(r"资源包\d*\.fcpk$", t):
        return "full"
    if _re.search(r"资源包-v\d+(?:\.\d+)*\.fcpk$", t):
        return "full"
    if "资源包-" in t:
        # `资源包-副本` / `资源包-拓展` 之类：Windows 副本名归一化后也是这个形态，
        # 故在这里再区分一次——副本/重名类没有子集语义关键字时按全量算
        if _re.search(r"资源包-(副本|copy|\d+)[^/]*\.fcpk$", t) and \
                not _re.search(r"资源包-(拓展|claude|基础|onlyoffice|bili)", t):
            return "full"
        return "subset"
    return None


def inspect(path):
    """只读探测（不派生密钥、不解密）：大小/条数/是否截断。
    表在末尾，所以「是否完整」只需看 footer——比读完整个包快。

    全审 B3 实锤（严重）：本函数契约是**返回 dict**，但早前头部被截断时
    走 `_parse_header` 抛 FcpkError，三个调用点（res_boot/res_install/
    res_api）全都没接——最坏链路是用户在引导框选了半截包 → 抛异常 →
    preflight_gate 兜底吞掉放行 → 走到「窗口建不出来」的莫名状态。
    这里统一兜成 {"ok": False}。"""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(HEADER_LEN)
            if len(head) < HEADER_LEN:
                return {"ok": False, "size": size,
                        "err": "资源包不完整（头部被截断——下载没下完？）"}
            if head[0:4] != MAGIC:
                return {"ok": False, "size": size,
                        "err": "不是资源包（文件头不匹配）"}
            h = _parse_header(head)
            if size >= FOOTER_LEN:
                f.seek(size - FOOTER_LEN)
                foot = f.read(FOOTER_LEN)
            else:
                foot = b""
        if len(foot) < FOOTER_LEN or foot[0:4] != FOOTER_MAGIC:
            return {"ok": False, "err": "资源包不完整（下载被截断或传输损坏）",
                    "size": size}
        if foot[4:12] != struct.pack("<Q", h["total"]):
            return {"ok": False, "err": "资源包不完整（长度校验不一致）",
                    "size": size}
        return {"ok": True, "size": size, "entries": h["entries"],
                "plain_len": h["total"], "chunk": h["chunk"],
                "table_len": h["table_len"]}
    except FcpkError as e:
        return {"ok": False, "err": str(e)}
    except OSError as e:
        return {"ok": False, "err": "读取失败：%s" % e}


# --------------------------------------------------------------------- 写

def _sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


class FcpkWriter:
    """流式写出。

        w = FcpkWriter("/tmp/x.fcpk")
        w.add_file("C:/a/Git.exe", "install/Git.exe", kind="git", mode="raw")
        w.add_file(".../claude.exe", "claude-code/bin/claude.exe",
                   kind="claude", mode="deflate")
        w.add_file(".../claude.exe",     # 同内容第二处 → 硬链接，不占空间
                   "claude-code/node_modules/.../claude.exe",
                   kind="claude", link_from="claude-code/bin/claude.exe")
        w.add_bytes(b"...", "manifest.json")
        w.close()

    段表在内存累积（几百条元数据量级），体边算边写，内存不随包体增长。
    """

    def __init__(self, path, password=None, chunk_size=CHUNK_SIZE,
                 salt=None, iters=DEFAULT_ITER, resources=None):
        self.path = path
        self._pwd = password or _password()
        self.chunk = chunk_size
        self.iters = iters
        self._salt = salt or os.urandom(16)
        self._k_tab, self._k_hdr, self._k_seg = _derive(
            self._pwd, self._salt, iters)
        self._resources = list(resources or [])
        self._tmp = path + ".building"
        self._f = open(self._tmp, "wb")
        self._f.write(b"\0" * HEADER_LEN)      # 头占位，close 时回填
        self._entries = []
        self._total = 0
        self._sig = {}                         # arcname -> (size, sha256)

    # -- 体写入 --

    def _write_seg(self, arc, seg_no, idx, data, segs):
        c = AES.new(self._k_seg, AES.MODE_GCM,
                    nonce=_seg_nonce(self._k_seg, seg_no, idx))
        c.update(_seg_aad(arc, seg_no, idx))
        ct, tag = c.encrypt_and_digest(bytes(data))
        self._f.write(ct)
        self._f.write(tag)
        segs.append([idx, len(ct)])
        return idx + 1

    def _seal(self, chunks, arc, kind, size, sha, mode, link):
        # 段号 = 该 entry 在 entries 里的索引。读写必须同一口径——早前写侧
        # 用独立递增计数器、读侧用列表索引，link entry 只占索引不占计数器，
        # 一旦出现 link 之后所有段号全错位（实测 pydeps 段 MAC 失败）。
        seg_no = len(self._entries)
        if link:
            self._entries.append({"path": arc, "kind": kind, "mode": "link",
                                  "size": size, "sha256": sha, "segs": [],
                                  "link": link})
            return
        segs, idx, buf = [], 0, bytearray()
        for chunk in chunks:
            pos = 0
            while pos < len(chunk):
                take = min(self.chunk - len(buf), len(chunk) - pos)
                buf += chunk[pos:pos + take]
                pos += take
                if len(buf) == self.chunk:
                    idx = self._write_seg(arc, seg_no, idx, buf, segs)
                    buf = bytearray()
        if buf:
            idx = self._write_seg(arc, seg_no, idx, buf, segs)
        self._entries.append({"path": arc, "kind": kind, "mode": mode,
                              "size": size, "sha256": sha, "segs": segs,
                              "link": None})
        self._total += size

    def add_bytes(self, data, arc, kind="misc", mode="raw"):
        self._seal([data], arc, kind, len(data),
                   hashlib.sha256(data).hexdigest(), mode, None)
        return self

    def add_file(self, src, arc, kind="misc", mode="raw", link_from=None,
                 chunk=1 << 20):
        """加入一个文件。

        - link_from：arcname 指向包内另一个 entry。仅当 size+sha256 完全
          一致才复用以省空间（如 claude.exe 两份各 258MB）；否则照常存。
        - mode="raw"：原字节直存（.msi/.zip/.whl 已压缩，再压反而变大）；
          "deflate"：entry 级 zlib（.exe/.dll 这类值得压，实测压到 0.57）。
        """
        size = os.path.getsize(src)
        sha = _sha256_file(src)
        if link_from:
            prev = self._sig.get(link_from)
            if prev and prev[0] == size and prev[1] == sha:
                self._seal([], arc, kind, size, sha, "raw", link_from)
                return self
        self._sig[arc] = (size, sha)
        self._seal(_file_chunks(src, chunk, compress=(mode == "deflate")),
                   arc, kind, size, sha, mode, None)
        return self

    def close(self):
        """追加段表 + footer，回填头。无数据搬运。"""
        table = {"format": "fcpk", "ver": VERSION,
                 "created": _now(), "resources": self._resources,
                 "entries": self._entries}
        raw = json.dumps(table, ensure_ascii=False,
                         separators=(",", ":"), sort_keys=True).encode("utf-8")
        comp = zlib.compress(raw, 6)
        nonce = hmac.new(self._k_tab, b"table", hashlib.sha256).digest()[:12]
        c = AES.new(self._k_tab, AES.MODE_GCM, nonce=nonce)
        c.update(struct.pack("<I", len(comp)))
        ct, tag = c.encrypt_and_digest(comp)
        blob = TABLE_MAGIC + struct.pack("<I", len(comp)) + ct + tag
        self._f.write(blob)
        self._f.write(FOOTER_MAGIC + struct.pack("<Q", self._total)
                      + hashlib.sha256(blob).digest()[:16] + b"\0\0\0\0")
        self._f.flush()
        os.fsync(self._f.fileno())
        self._f.seek(0)
        self._f.write(_sign(_pack_header(self._salt, self.iters, len(blob),
                                         self._total, len(self._entries)),
                            self._k_hdr))
        self._f.close()
        os.replace(self._tmp, self.path)
        return self.path


def _file_chunks(path, chunk, compress=False):
    """顺序读文件。compress=True 走 entry 级 zlib（块级会因块边界丢压缩率）。"""
    if compress:
        co = zlib.compressobj(6)
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(chunk), b""):
                out = co.compress(b)
                if out:
                    yield out
        tail = co.flush()
        if tail:
            yield tail
    else:
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(chunk), b""):
                yield b


def _now():
    import datetime
    return datetime.datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------- 读

class FcpkReader:
    """打开、校验、按 entry 流式解包。

        r = FcpkReader("x.fcpk")          # 派生密钥 + 解出段表（几 KB）
        for e in r.entries: print(e["path"])
        r.extract_to("claude-code", "/tmp/out")     # 只解某个前缀
        r.close()

    也可以在后台线程里用 progress 回调（cb(done_bytes, total_bytes, path)）。
    """

    def __init__(self, path, password=None):
        self.path = path
        self._f = open(path, "rb")
        try:
            self._open(path, password)
        except Exception:
            try:
                self._f.close()
            except OSError:
                pass
            raise

    def _open(self, path, password):
        size = os.path.getsize(path)
        head = self._f.read(HEADER_LEN)
        self.header = _parse_header(head)
        if size < HEADER_LEN + FOOTER_LEN:
            raise FcpkError("资源包不完整（文件过小）")
        self._f.seek(size - FOOTER_LEN)
        foot = self._f.read(FOOTER_LEN)
        if foot[0:4] != FOOTER_MAGIC:
            raise FcpkError("资源包不完整（下载被截断或传输损坏）")
        # 全审 B2：footer 的 total 与头里的 total 必须一致——头被改过时
        # MAC 已经会失败，但这里再校验一次，防止头部 manifest 级篡改漏网。
        if foot[4:12] != struct.pack("<Q", self.header["total"]):
            raise FcpkError("资源包不完整（长度校验不一致）")
        self._body_start = HEADER_LEN
        table_len = self.header["table_len"]
        self._body_end = size - FOOTER_LEN - table_len
        if self._body_end < self._body_start:
            raise FcpkError("资源包结构异常（段表位置越界）")
        # 预认证 DoS 钳制（对抗审 P1）：kdf_iter 是明文字段且 KDF 必须先于
        # MAC（口令派生键才能验 MAC——顺序无法颠倒），不钳制时改 4 字节
        # 即可让每次打开烧数十分钟 CPU。合法包恒为 DEFAULT_ITER。
        _it = self.header["iters"]
        if not (_KDF_ITERS_MIN <= _it <= _KDF_ITERS_MAX):
            raise FcpkError("资源包结构异常（kdf 迭代数越界：%d）" % _it)
        self._pwd = password or _password()
        self._k_tab, self._k_hdr, self._k_seg = _derive(
            self._pwd, self.header["salt"], _it)
        if not hmac.compare_digest(
                _sign(head, self._k_hdr)[28:44], self.header["mac"]):
            raise FcpkError("资源包头部校验失败（文件被篡改或口令不匹配）")
        self._f.seek(self._body_end)
        blob = self._f.read(table_len)
        if blob[0:4] != TABLE_MAGIC:
            raise FcpkError("资源包结构异常（段表标记不匹配）")
        # footer 的段表哈希校验（对抗审 P3：写了从不验——现与头/表三方一致）
        if foot[12:28] != hashlib.sha256(blob).digest()[:16]:
            raise FcpkError("资源包不完整（段表哈希不一致）")
        n = struct.unpack_from("<I", blob, 4)[0]
        if n > table_len - 8 - TAG_LEN:
            raise FcpkError("资源包结构异常（段表长度越界）")
        nonce = hmac.new(self._k_tab, b"table", hashlib.sha256).digest()[:12]
        c = AES.new(self._k_tab, AES.MODE_GCM, nonce=nonce)
        c.update(struct.pack("<I", n))
        try:
            comp = c.decrypt_and_verify(blob[8:8 + n], blob[8 + n:])
        except ValueError:
            raise FcpkError("资源包段表解密失败（口令错误或文件损坏）")
        # 表炸弹上限（对抗审 P0 + 二轮 P0-1）：zlib 的 max_length=0 语义是
        # **无限制**——首轮恰返回 64MB 后传 0 会让后续调用一口吃完全部膨胀
        # （实测 2MB 包→4GB RSS 后才报错）。修：每轮**先查余量再解**，
        # 余量≤0 立即拒，绝不以 0 为 max_length 调用
        d = zlib.decompressobj()
        raw = d.decompress(comp, _MAX_TABLE)
        while d.unconsumed_tail:
            if len(raw) >= _MAX_TABLE:
                raise FcpkError("资源包异常：段表超上限（疑似损坏或包炸弹）")
            more = d.decompress(d.unconsumed_tail, _MAX_TABLE - len(raw))
            if not more:
                break
            raw += more
        if len(raw) > _MAX_TABLE or d.unconsumed_tail or not d.eof:
            raise FcpkError("资源包异常：段表超上限（疑似损坏或包炸弹）")
        self.table = json.loads(raw.decode("utf-8"))
        self.entries = self.table.get("entries") or []
        if len(self.entries) != self.header["entries"]:
            raise FcpkError("资源包结构异常（条目数与头部不一致）")
        # 顺序累计每个 entry 的体起点（段按 entry 顺序物理排布）
        off = self._body_start
        for e in self.entries:
            e["_off"] = off
            off += sum(clen + TAG_LEN for _i, clen in (e.get("segs") or []))

    # -- 解包 --

    def _read_entry(self, e, out_f, progress=None, done_ref=None,
                    should_cancel=None):
        """把一个 entry 的段逐块解密写出。mode=deflate 时边解压边写。

        内存上限（对抗审 P1）：续解产物**逐片过 _over 并立即写出**——早前
        `data += more` 把单块全部膨胀结果累计进内存（实测单块峰值 1GB），
        "每块 8MB" 只保了磁盘没保内存。"""
        dec = zlib.decompressobj() if e.get("mode") == "deflate" else None
        seg_no = self._entry_seg_no(e)
        self._f.seek(e["_off"])
        wrote = 0

        def _emit(piece):
            # C6 二审：上限判定在写入点无条件执行（段切分绕过已封）
            nonlocal wrote
            if _over(piece, wrote, e["path"]):
                raise FcpkError(
                    "资源包异常：%s 解压后超过上限（疑似损坏或包炸弹）"
                    % e["path"])
            if piece:
                out_f.write(piece)
                wrote += len(piece)
                if progress and done_ref is not None:
                    done_ref[0] += len(piece)
                    progress(done_ref[0], self.header["total"], e["path"])

        for idx, clen in e.get("segs") or []:
            if should_cancel and should_cancel():
                raise Cancelled("已取消")
            ct = self._f.read(clen)
            tag = self._f.read(TAG_LEN)
            if len(ct) != clen or len(tag) != TAG_LEN:
                raise FcpkError("资源包不完整（%s 第 %d 段读取失败）"
                                % (e["path"], idx))
            c = AES.new(self._k_seg, AES.MODE_GCM,
                        nonce=_seg_nonce(self._k_seg, seg_no, idx))
            c.update(_seg_aad(e["path"], seg_no, idx))
            try:
                pt = c.decrypt_and_verify(ct, tag)
            except ValueError:
                raise FcpkError("资源包校验失败：%s 第 %d 段损坏"
                                % (e["path"], idx))
            if dec:
                # C6（全审）：分块限长解压——1MB 密文可膨胀 GB 级
                piece = dec.decompress(pt, _MAX_OUT_PER_CHUNK)
                while True:
                    if piece:
                        _emit(piece)
                    if not dec.unconsumed_tail:
                        break
                    piece = dec.decompress(dec.unconsumed_tail,
                                           _MAX_OUT_PER_CHUNK)
                    if not piece:
                        # 还有残留却压不出字节 = 流内部状态异常，别静默丢数据
                        raise FcpkError("资源包校验失败：%s 解压异常"
                                        % e["path"])
            else:
                _emit(pt)
        if dec:
            tail = dec.flush()
            if tail:
                _emit(tail)
        if wrote != e.get("size", wrote):
            raise FcpkError("资源包校验失败：%s 长度不符（%d ≠ %d）"
                            % (e["path"], wrote, e.get("size")))
        return wrote

    def _entry_seg_no(self, e):
        """段号 = 该 entry 在所有 entry 里的序号（link 也占号，写入时同口径）。"""
        for i, x in enumerate(self.entries):
            if x is e:
                return i
        raise FcpkError("内部错误：entry 定位失败")

    def extract_entry(self, e, dst_path, progress=None, done_ref=None,
                      should_cancel=None):
        """解一个 entry 到 dst_path。parent 自动创建；先写 .part 再改名，
        失败/取消时清理 .part（对抗审 P2：残留半装骗过启动闸门）。link entry
        由调用方处理（见 extract_all）。"""
        os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
        tmp = dst_path + ".part"
        try:
            with open(tmp, "wb") as f:
                self._read_entry(e, f, progress, done_ref,
                                 should_cancel=should_cancel)
            os.replace(tmp, dst_path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
        return dst_path

    def verify_all(self, progress=None):
        """逐段验签 + 逐 entry 长度校验（不落盘）。打包后自检与
        「用户装完前确认包没坏」两处用。"""
        done = [0]
        for e in self.entries:
            if e.get("mode") == "link":
                continue
            with open(os.devnull, "wb") as devnull:
                self._read_entry(e, devnull, progress, done)
        return True

    # NTFS 保留设备名（对抗审 P1）：LPT1/PRN 等作文件名时 open 落在设备上
    # 无限挂死（取消也救不了）。基名（首个点前）命中即拒——含扩展名形态
    # （"LPT1.txt" 同样挂）。另拒尾部点/空格组件与超长组件。
    _RESERVED = frozenset(
        ["CON", "PRN", "AUX", "NUL"]
        + ["COM%d" % i for i in range(1, 10)]
        + ["LPT%d" % i for i in range(1, 10)])

    @classmethod
    def _check_rel(cls, rel):
        if not rel or rel in (".", ".."):
            raise FcpkError("资源包路径非法（空路径）")
        for part in rel.split("/"):
            if not part or part in (".", ".."):
                raise FcpkError("资源包路径非法（空/相对组件）：%s" % rel)
            if len(part) > 255 or len(rel) > 1000:
                raise FcpkError("资源包路径非法（超长）：%s" % rel[:80])
            if part.rstrip(" .") != part:
                raise FcpkError("资源包路径非法（尾部点/空格）：%s" % rel)
            stem = part.split(".")[0].upper()
            if stem in cls._RESERVED:
                raise FcpkError("资源包路径非法（保留设备名）：%s" % rel)

    def extract_all(self, dest_root, kinds=None, progress=None,
                    should_cancel=None):
        """按需解包到 dest_root，返回已解出的相对路径列表。

        kinds=None 表示全解；list 表示只解这些 kind。
        mode=link 的 entry 不占包体，用硬链接指向前一个 entry 的落地文件；
        跨卷/不支持时退化 shutil.copy2（**绝不因链接失败阻断安装**）。
        失败/取消时清理 .part 半截文件（对抗审 P2：残留半装会骗过启动闸门）。
        """
        done = [0]
        made = {}
        out = []
        try:
            for e in self.entries:
                if should_cancel and should_cancel():
                    raise Cancelled("已取消")
                if kinds is not None and e.get("kind") not in kinds:
                    continue
                rel = e["path"].replace("\\", "/").lstrip("/")
                self._check_rel(rel)
                # 全审 B1 实锤（严重）：早前只判 rel.startswith("..")，`a/../../evil.txt`
                # 首段是 a 不触发 → 真能写到解包根之外。改用 realpath 包含判定。
                dst = os.path.realpath(os.path.join(dest_root, *rel.split("/")))
                root_real = os.path.realpath(dest_root)
                if dst != root_real and not dst.startswith(root_real + os.sep):
                    raise FcpkError("资源包路径非法（越出解包目录）：%s" % e["path"])
                # 文件/目录名冲突（对抗审 P2）：先文件后同名目录（或反）曾裸抛
                _dir = os.path.dirname(dst)
                if _dir and os.path.isfile(_dir):
                    raise FcpkError("资源包路径冲突：%s 的父级已是文件" % e["path"])
                if os.path.isdir(dst):
                    raise FcpkError("资源包路径冲突：%s 已是目录" % e["path"])
                if e.get("mode") == "link":
                    src = made.get(e.get("link") or "")
                    if not src or not os.path.isfile(src):
                        # 目标没解出（kinds 过滤掉了）或链接源缺失 → 无法补
                        continue
                    os.makedirs(_dir or ".", exist_ok=True)
                    try:
                        if os.path.exists(dst):
                            os.remove(dst)
                        os.link(src, dst)
                    except OSError:
                        shutil.copy2(src, dst)
                else:
                    # 跨 entry 总量配额（对抗审 P1：按 entry 限不按包限可填盘）
                    if done[0] > _MAX_TOTAL_OUT:
                        raise FcpkError("资源包异常：解包总量超过上限（疑似包炸弹）")
                    self.extract_entry(e, dst, progress, done,
                                       should_cancel=should_cancel)
                    made[rel] = dst
                out.append(rel)
        except BaseException:
            raise
        return out

    def close(self):
        try:
            self._f.close()
        except OSError:
            pass
