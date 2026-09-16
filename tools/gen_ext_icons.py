# -*- coding: utf-8 -*-
"""按后缀生成桌面文件图标 .ico（临时生成脚本，可重复运行覆盖）。
设计对齐 web/js/file-icons.js：圆角纸形 + 折角 + 后缀专属内容 + 左下角像素
机器人角标（呼应工具 logo）。输出 ico/ext/<design>.ico，注册表按 design 映射。
"""
import os
from PIL import Image, ImageDraw, ImageFont

# 输出到项目根 ico/ext/（本脚本在 tools/ 下，上溯一层才是项目根）
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ico", "ext")
os.makedirs(OUT_DIR, exist_ok=True)
S = 256  # 画布

def _font(size, bold=True):
    for name in (["consolab.ttf", "consola.ttf"] if bold else ["consola.ttf"]) + ["arialbd.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _robot(d, x0=6, y0=142, s=104):
    """左下角角标 = app.ico logo 缩小复刻（海康摄像头拟人机器人，用户反馈
    初版方脸像素机器人"太丑、不还原"后按 logo 逐像素拆解重绘）：
    深蓝灰 squircle 底 + 蓝机身黑粗描边 + 天线黑杆青球 + 中心镜头同心圆
    （黑环→白环→黑环→蓝心+高光点）+ 橙色腮红两点。HIK 红字/斜光带省略
    （小尺寸会糊）。"""
    BASE = (38, 42, 54, 255)      # 深蓝灰底
    OUTL = (20, 22, 31, 255)      # 黑描边
    BODY = (78, 124, 246, 255)    # 亮蓝机身
    CYAN = (41, 197, 246, 255)    # 天线球
    ORNG = (249, 141, 85, 255)    # 腮红
    W = (255, 255, 255, 255)
    # 底 squircle
    d.rounded_rectangle([x0+2, y0+2, x0+s-2, y0+s-2], int(s*0.20), fill=BASE)
    cx = x0 + s/2
    by = y0 + s*0.30                          # 机身顶
    # 天线：黑杆 + 青球（球压在深底上）
    d.rectangle([cx-s*0.022, y0+s*0.10, cx+s*0.022, by], fill=OUTL)
    r = s*0.085
    d.ellipse([cx-r, y0+s*0.075-r, cx+r, y0+s*0.075+r], fill=CYAN)
    # 机身：粗黑描边圆角横矩形（宽>高）
    bw, bh = s*0.96, s*0.62
    bx = cx - bw/2
    d.rounded_rectangle([bx, by, bx+bw, by+bh], int(bh*0.42), fill=OUTL)
    m = s*0.045
    d.rounded_rectangle([bx+m, by+m, bx+bw-m, by+bh-m], int(bh*0.42)-m, fill=BODY)
    # 镜头同心圆（黑粗环→白环→黑环→蓝心）+ 左上白色高光点
    cyc = by + bh/2
    for rr, col in ((bh*0.40, OUTL), (bh*0.288, W), (bh*0.224, OUTL), (bh*0.136, BODY)):
        d.ellipse([cx-rr, cyc-rr, cx+rr, cyc+rr], fill=col)
    hr = bh*0.05
    d.ellipse([cx-bh*0.14-hr, cyc-bh*0.14-hr, cx-bh*0.14+hr, cyc-bh*0.14+hr], fill=W)
    # 腮红：镜头左右下侧橙点
    cr = s*0.05
    for sx in (cx-bw*0.30, cx+bw*0.30):
        d.ellipse([sx-cr, by+bh*0.74-cr, sx+cr, by+bh*0.74+cr], fill=ORNG)

def _paper(d, color):
    """文件主体：圆角纸形 + 右上折角，浅填充+描边。返回内容区（供画字）。"""
    fill = color + (38,)
    line = color + (255,)
    d.polygon([(150, 24), (226, 100), (150, 100)], fill=color + (90,))
    d.rounded_rectangle([30, 24, 196, 232], 18, fill=fill, outline=line, width=8)
    d.polygon([(30, 62), (30, 42+0), (30, 24+18)], fill=fill)  # 无害占位
    # 折角白线
    d.line([(150, 24), (150, 100), (226, 100)], fill=color + (200,), width=8)
    d.rounded_rectangle([30, 24, 196, 232], 18, outline=line, width=8, fill=None)

def _txt(d, c):
    for i, (y, w, op) in enumerate([(84, 116, 200), (118, 116, 150), (152, 82, 110)]):
        d.rounded_rectangle([64, y, 64+w, y+20], 10, fill=c + (op,))

def _log(d, c):
    d.ellipse([62, 72, 116, 126], outline=c + (255,), width=9)
    d.line([(89, 84), (89, 100), (102, 108)], fill=c + (255,), width=8, joint="curve")
    for y, w in ((84, 50), (114, 50)):
        d.rounded_rectangle([128, y, 128+w, y+16], 8, fill=c + (170,))
    d.rounded_rectangle([64, 156, 178, 174], 8, fill=c + (110,))

def _letter(d, c, ch):
    f = _font(108)
    d.text((118, 116), ch, font=f, fill=c + (255,), anchor="mm")

def _cpp(d, c):
    f = _font(100); fp = _font(72)
    d.text((100, 130), "C", font=f, fill=c + (255,), anchor="mm")
    d.text((164, 100), "+", font=fp, fill=c + (255,), anchor="mm")
    d.text((164, 162), "+", font=fp, fill=c + (255,), anchor="mm")

def _json(d, c):
    f = _font(72)
    d.text((113, 118), "{ }", font=f, fill=c + (255,), anchor="mm")

def _md(d, c):
    f = _font(104)
    d.text((113, 116), "M", font=f, fill=c + (255,), anchor="mm")
    d.rounded_rectangle([64, 150, 176, 168], 9, fill=c + (160,))

def _gear(d, c, cx=118, cy=120, r=44):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=c + (255,), width=10)
    d.ellipse([cx-16, cy-16, cx+16, cy+16], fill=c + (255,))
    import math
    for ang in range(0, 360, 45):
        a = math.radians(ang)
        x1, y1 = cx + (r+4) * math.cos(a), cy + (r+4) * math.sin(a)
        x2, y2 = cx + (r+22) * math.cos(a), cy + (r+22) * math.sin(a)
        d.line([(x1, y1), (x2, y2)], fill=c + (255,), width=14)

def _py(d, c):
    yellow = (255, 212, 59)
    d.rounded_rectangle([70, 66, 130, 100], 16, fill=yellow + (230,))
    d.rounded_rectangle([126, 106, 186, 140], 16, fill=c + (230,))
    d.rounded_rectangle([70, 146, 130, 180], 16, fill=yellow + (180,))

def _sh(d, c):
    d.line([(70, 92), (106, 120), (70, 148)], fill=c + (255,), width=12, joint="curve")
    d.rounded_rectangle([118, 140, 172, 156], 8, fill=c + (255,))

def _xml(d, c):
    f = _font(64)
    d.text((113, 124), "< >", font=f, fill=c + (255,), anchor="mm")

def _yaml(d, c):
    # key:value 结构:粗竖树干 + 层级缩进色块 + 冒号圆点
    d.rounded_rectangle([66, 70, 80, 150], 7, fill=c + (200,))
    d.rounded_rectangle([94, 78, 174, 94], 8, fill=c + (230,))
    d.rounded_rectangle([96, 108, 168, 124], 8, fill=c + (150,))
    d.ellipse([150, 84, 158, 92], fill=c + (255,))   # 冒号点

def _csv(d, c):
    # 田字表格:表头行 + 2x3 数据格(区别于 txt 的横线)
    d.rounded_rectangle([64, 72, 178, 176], 8, outline=c + (255,), width=8)
    d.line([(64, 110), (178, 110)], fill=c + (200,), width=7)
    d.line([(64, 146), (178, 146)], fill=c + (140,), width=6)
    d.line([(121, 72), (121, 176)], fill=c + (160,), width=6)
    d.rounded_rectangle([72, 84, 108, 98], 4, fill=c + (220,))   # 表头高亮块

# design → (绘制函数, 颜色)
DESIGNS = {
    "txt":  (_txt,  (122, 162, 200)),
    "log":  (_log,  (79, 209, 161)),
    "c":    (_letter, (92, 179, 255), "C"),
    "h":    (_letter, (92, 179, 255), "H"),
    "cpp":  (_cpp,  (92, 179, 255)),
    "json": (_json, (232, 162, 91)),
    "csv":  (_csv,  (86, 184, 217)),
    "md":   (_md,   (176, 140, 217)),
    "ini":  (_gear, (210, 168, 255)),
    "py":   (_py,   (92, 179, 255)),
    "sh":   (_sh,   (143, 212, 148)),
    "xml":  (_xml,  (232, 148, 91)),
    "yaml": (_yaml, (86, 184, 217)),
}

for name, spec in DESIGNS.items():
    if name in ("c", "h"):
        fn, color, arg = spec
    elif name == "txt":
        fn, color = _txt, (122, 162, 200)
    else:
        fn, color = spec[0], spec[1]
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    _paper(d, color)
    if name in ("c", "h"):
        fn(d, color, arg)
    elif callable(getattr(fn, "__call__", None)):
        fn(d, color)
    _robot(d)
    # 存多尺寸 ico
    im.save(os.path.join(OUT_DIR, f"{name}.ico"),
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.save(os.path.join(OUT_DIR, f"{name}.png"))
    print("gen", name)

# 后缀 → design 映射（与 file_assoc.py 共用，写成 json）
import json
EXT_MAP = {
    ".txt": "txt", ".log": "log", ".md": "md",
    ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".json": "json", ".csv": "csv",
    ".yaml": "yaml", ".yml": "yaml",
    ".c": "c", ".h": "h", ".cpp": "cpp", ".hpp": "cpp",
    ".py": "py",
    ".sh": "sh", ".bat": "sh", ".cmd": "sh", ".ps1": "sh",
    ".xml": "xml",
}
with open(os.path.join(OUT_DIR, "ext_map.json"), "w", encoding="utf-8") as f:
    json.dump(EXT_MAP, f, ensure_ascii=False, indent=1)
print("map written,", len(EXT_MAP), "exts")
