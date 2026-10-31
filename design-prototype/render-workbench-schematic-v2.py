"""Render the desktop-only MYATOM workbench schematic."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


OUT = Path(__file__).with_name("workbench-schematic-v2.png")
FONT = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

BG = "#F5F4EF"
PAPER = "#FFFEFA"
SOFT = "#F0F1EC"
INK = "#172522"
MUTED = "#617069"
LINE = "#DCE2DA"
GREEN = "#285E52"
GREEN_SOFT = "#E9F1EC"
ORANGE = "#AD5636"
ORANGE_SOFT = "#F8EEE8"

im = Image.new("RGB", (1600, 1210), BG)
d = ImageDraw.Draw(im)


def font(size, bold=False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size)


def txt(x, y, s, size=18, color=INK, bold=False):
    d.text((x, y), s, font=font(size, bold), fill=color)


def rr(box, fill=PAPER, outline=None, width=1, radius=12):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def ln(x1, y1, x2, y2, color=LINE, width=1):
    d.line((x1, y1, x2, y2), fill=color, width=width)


def pill(x, y, label, fill=GREEN_SOFT, color=GREEN, size=15, pad=14):
    f = font(size)
    w = int(d.textlength(label, font=f)) + pad * 2
    rr((x, y, x + w, y + 32), fill=fill, radius=16)
    txt(x + pad, y + 5, label, size, color)
    return w


def dot(x, y, color, r=5):
    d.ellipse((x-r, y-r, x+r, y+r), fill=color)


def arrow(x1, y1, x2, y2, color=GREEN, width=2):
    ln(x1, y1, x2, y2, color, width)
    d.polygon([(x2, y2), (x2-10, y2-5), (x2-10, y2+5)], fill=color)


# Page title and proportion labels.
txt(64, 44, "MYATOM  ·  主工作台示意", 38, INK, True)
txt(66, 100, "保留熟悉的 AI 对话 + 应用预览；在左侧加入可核对的项目状态入口。", 20, MUTED)
pill(1270, 54, "桌面工作区 · 结构示意", fill="#E8EBE4", color=MUTED, size=16)

txt(78, 151, "01  项目导航", 17, GREEN, True)
txt(300, 151, "02  AI 对话（始终保留）", 17, GREEN, True)
txt(735, 151, "03  预览 / 项目状态（按选择切换）", 17, GREEN, True)

# Main application frame: 200 / 424 / 848 logical widths.
sx, sy, ex, ey = 64, 190, 1536, 953
rr((sx, sy, ex, ey), fill=PAPER, outline="#CED7CE", width=2, radius=16)
ln(sx, 259, ex, 259)
ln(264, sy, 264, ey)
ln(688, 259, 688, ey)

# Project header.
rr((88, 210, 126, 240), fill=GREEN, radius=8)
txt(97, 207, "M", 22, PAPER, True)
txt(290, 207, "每周支出记录", 23, INK, True)
dot(474, 225, GREEN, 5)
txt(489, 210, "已保存 · 版本 v3", 15, MUTED)
txt(1370, 211, "项目设置", 16, MUTED)

# Left navigation.
def nav(y, label, active=False, status=None, status_color=MUTED):
    if active:
        rr((77, y-3, 251, y+38), fill="#E8ECE6", radius=9)
        rr((77, y-3, 81, y+38), fill=GREEN, radius=2)
    dot(101, y+18, GREEN if active else "#9AA8A0", 5)
    txt(118, y+5, label, 17, INK if active else MUTED, active)
    if status:
        dot(236, y+18, status_color, 4)

nav(286, "工作台", True)
ln(83, 346, 248, 346)
txt(89, 361, "项目状态", 13, "#88958D", True)
nav(398, "项目概览")
nav(448, "项目文档")
nav(498, "测试", status="待看", status_color=ORANGE)
nav(548, "发布", status="未发布", status_color="#B5BDB6")
ln(83, 616, 248, 616)
txt(89, 635, "最近项目", 13, "#88958D", True)
txt(89, 670, "每周支出记录", 14, MUTED)
txt(89, 707, "＋  新建项目", 14, GREEN)

# Conversation panel.
txt(289, 280, "对话", 20, INK, True)
pill(599, 278, "当前项目", fill=GREEN_SOFT, color=GREEN, size=13, pad=10)
ln(282, 324, 670, 324)
rr((327, 348, 662, 432), fill=SOFT, radius=11)
txt(348, 362, "帮我做一个每周支出记录工具，", 16)
txt(348, 389, "可添加金额、分类和备注。", 16)
txt(328, 439, "你 · 10:14", 12, "#88958D")

dot(307, 491, GREEN, 14)
txt(298, 474, "M", 17, PAPER, True)
txt(331, 472, "需求已明确，开始生成。", 16, INK)
rr((332, 511, 662, 655), fill="#F7F8F4", outline=LINE, radius=10)
txt(350, 526, "已明确内容", 16, INK, True)
ln(349, 560, 646, 560)
txt(350, 575, "应用：每周支出记录", 14, MUTED)
txt(350, 602, "功能：添加、分类、统计", 14, MUTED)
txt(350, 629, "数据：刷新后仍可读取", 14, MUTED)

dot(307, 700, GREEN, 14)
txt(298, 683, "M", 17, PAPER, True)
txt(331, 681, "版本 v3 已保存，预览已就绪。", 16, INK)
txt(331, 711, "可以在右侧体验，也可以继续提出修改。", 14, MUTED)

rr((282, 839, 670, 925), fill=PAPER, outline=LINE, radius=12)
txt(301, 855, "继续描述你想修改的内容…", 15, "#8A9790")
ln(298, 890, 652, 890)
txt(301, 898, "发送后形成新的迭代", 12, "#8A9790")
rr((616, 894, 652, 920), fill=GREEN, radius=7)
txt(624, 894, "↑", 18, PAPER, True)

# Right: preview toolbar.
txt(719, 278, "预览", 18, GREEN, True)
txt(795, 278, "代码", 18, MUTED)
ln(714, 315, 771, 315, GREEN, 3)
pill(1405, 272, "v3", fill=SOFT, color=INK, size=14, pad=13)
ln(706, 324, 1516, 324)

# App preview browser.
rr((710, 341, 1515, 929), fill="#FFFFFF", outline=LINE, radius=11)
txt(736, 359, "每周支出记录", 20, INK, True)
txt(1284, 361, "首页", 15, GREEN, True)
txt(1347, 361, "统计", 15, MUTED)
txt(1410, 361, "设置", 15, MUTED)
ln(730, 399, 1495, 399)

rr((732, 419, 1492, 553), fill=GREEN, radius=12)
txt(759, 442, "本周支出", 17, "#E9F1EC")
txt(759, 475, "¥ 528.00", 35, PAPER, True)
txt(759, 525, "6 月 10 日 — 6 月 16 日", 14, "#D5E6DC")
for i, h in enumerate([34, 61, 47, 77, 42, 66, 29]):
    x = 1138 + i * 43
    rr((x, 524-h, x+18, 524), fill="#C9E0D2", radius=3)

txt(736, 578, "支出记录", 19, INK, True)
txt(1245, 578, "添加支出", 19, INK, True)
ln(1227, 574, 1227, 899)
for j, (name, cat, amount) in enumerate([
    ("午餐", "餐饮 · 6 月 12 日", "− ¥ 28.00"),
    ("地铁", "交通 · 6 月 12 日", "− ¥ 6.00"),
    ("超市购物", "生活 · 6 月 11 日", "− ¥ 86.00"),
    ("电影票", "娱乐 · 6 月 10 日", "− ¥ 45.00"),
]):
    y = 624 + j * 69
    dot(756, y+15, "#E7EFE9", 17)
    txt(746, y+2, str(j+1), 15, GREEN, True)
    txt(787, y-1, name, 16, INK, True)
    txt(787, y+27, cat, 13, MUTED)
    txt(1079, y+8, amount, 14, INK, True)
    ln(736, y+58, 1209, y+58)

for label, value, y in [("金额", "¥  0.00", 628), ("分类", "请选择分类  ▾", 714), ("备注", "输入备注…", 800)]:
    txt(1245, y-27, label, 14, INK, True)
    rr((1244, y, 1476, y+48), fill=PAPER, outline=LINE, radius=6)
    txt(1258, y+12, value, 14, MUTED)
rr((1244, 867, 1476, 912), fill=ORANGE, radius=7)
txt(1324, 875, "添加支出", 15, PAPER, True)

# State-switch rule: compact 2-step visual, no second dashboard.
txt(66, 982, "左侧导航的切换规则", 23, INK, True)
txt(66, 1021, "只更换右侧项目内容；对话与输入保持在原位。", 17, MUTED)

rr((64, 1061, 714, 1173), fill=PAPER, outline=LINE, radius=11)
pill(84, 1079, "工作台", fill=GREEN_SOFT, color=GREEN, size=15)
txt(193, 1083, "对话常驻", 17, INK, True)
arrow(299, 1096, 380, 1096)
txt(401, 1083, "右侧：应用预览 / 代码", 17, GREEN, True)
txt(86, 1124, "继续描述需求、处理确认卡、查看 Agent 进展", 15, MUTED)

rr((741, 1061, 1536, 1173), fill=PAPER, outline=LINE, radius=11)
pill(762, 1079, "项目概览 / 文档 / 测试 / 发布", fill=ORANGE_SOFT, color=ORANGE, size=15)
txt(1094, 1083, "对话常驻", 17, INK, True)
arrow(1199, 1096, 1267, 1096)
txt(1287, 1083, "右侧：对应状态页", 17, GREEN, True)
txt(763, 1124, "当前阶段、规格文档、测试证据与发布状态按需查看", 15, MUTED)

im.save(OUT, optimize=True)
print(OUT)
