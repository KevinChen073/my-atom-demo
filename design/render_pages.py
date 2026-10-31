"""Render reviewable MYATOM multi-project desktop page mockups.

All visible project names and results are illustrative, never product evidence.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).parent
OUT = ROOT / "pages"
OUT.mkdir(exist_ok=True)
FONT = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

W, H = 1600, 1000
C = {
    "canvas": "#F6F5F1", "paper": "#FFFEFB", "soft": "#F0F1EC",
    "nav": "#F3F4EF", "ink": "#172522", "muted": "#53635C",
    "subtle": "#78857D", "line": "#D5DCD4", "green": "#285E52",
    "green_soft": "#E8F0EB", "orange": "#A64B2B",
    "orange_soft": "#F8ECE5", "warning": "#8A4C1E",
    "warning_soft": "#F9EBD8", "danger": "#A43D34",
    "danger_soft": "#F8E8E5", "white": "#FFFFFF",
}


def f(size=16, bold=False):
    return ImageFont.truetype(BOLD if bold else FONT, size)


class Art:
    def __init__(self):
        self.im = Image.new("RGB", (W, H), C["canvas"])
        self.d = ImageDraw.Draw(self.im)

    def box(self, x1, y1, x2, y2, fill="paper", outline=None, r=10, width=1):
        self.d.rounded_rectangle((x1, y1, x2, y2), radius=r,
                                 fill=C.get(fill, fill),
                                 outline=C.get(outline, outline) if outline else None,
                                 width=width)

    def line(self, x1, y1, x2, y2, color="line", width=1):
        self.d.line((x1, y1, x2, y2), fill=C.get(color, color), width=width)

    def text(self, x, y, value, size=16, color="ink", bold=False):
        self.d.text((x, y), value, font=f(size, bold), fill=C.get(color, color))

    def circle(self, x, y, radius=5, fill="green"):
        color = C.get(fill, fill)
        self.d.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)

    def pill(self, x, y, value, fill="green_soft", color="green", size=13, px=12, h=30):
        width = int(self.d.textlength(value, font=f(size))) + px * 2
        self.box(x, y, x+width, y+h, fill, r=h//2)
        self.text(x+px, y+(h-size)//2-2, value, size, color)
        return width

    def save(self, name):
        path = OUT / name
        self.im.save(path, optimize=True)
        return path


def brand(a):
    a.box(26, 20, 65, 57, "green", r=9)
    a.text(37, 19, "M", 24, "white", True)
    a.text(79, 26, "MYATOM", 20, "ink", True)


def chevron(a, x, y, color="muted"):
    a.line(x-6, y-3, x, y+3, color, 2)
    a.line(x, y+3, x+6, y-3, color, 2)


def checkmark(a, x, y, color="green"):
    a.line(x-6, y, x-1, y+5, color, 2)
    a.line(x-1, y+5, x+8, y-6, color, 2)


def topbar(a, project=None, status="代码已保存"):
    a.box(0, 0, W, 72, "paper", r=0)
    a.line(0, 71, W, 71)
    brand(a)
    a.line(216, 0, 216, 72)
    if project:
        a.text(243, 23, "所有项目", 15, "muted")
        a.text(318, 23, "›", 17, "subtle")
        a.text(342, 19, project, 20, "ink", True)
        a.circle(568, 35, 4, "green")
        a.text(580, 24, status, 14, "muted")
    else:
        a.text(243, 19, "所有项目", 20, "ink", True)
    a.text(1461, 25, "设计示例", 13, "subtle")


def nav_item(a, y, value, active=False, dot=None):
    if active:
        a.box(14, y, 202, y+43, "green_soft", r=9)
        a.box(14, y, 18, y+43, "green", r=2)
    a.circle(40, y+22, 5, "green" if active else "#9BA9A0")
    a.text(58, y+10, value, 16, "ink" if active else "muted", active)
    if dot:
        a.circle(182, y+22, 4, dot)


def project_nav(a, active="工作台"):
    a.box(0, 72, 216, H, "nav", r=0)
    a.line(215, 72, 215, H)
    a.text(23, 102, "当前项目", 13, "subtle", True)
    a.box(14, 132, 202, 205, "paper", "line", r=10)
    a.text(28, 146, "每周支出记录", 16, "ink", True)
    a.text(28, 175, "切换项目", 13, "green")
    chevron(a, 184, 163)
    a.text(23, 230, "项目空间", 13, "subtle", True)
    for idx, label in enumerate(["工作台", "项目概览", "项目文档", "测试", "发布"]):
        nav_item(a, 259 + idx*52, label, label == active,
                 "warning" if label == "测试" else "#ACB8AF" if label == "发布" else None)
    a.line(19, 545, 197, 545)
    a.text(30, 566, "←  所有项目", 15, "green")
    a.text(25, 948, "项目内容按身份隔离", 12, "subtle")


def chat(a):
    a.box(216, 72, 660, H, "paper", r=0)
    a.line(659, 72, 659, H)
    a.text(241, 105, "对话", 21, "ink", True)
    a.pill(540, 102, "当前项目", size=12, h=27)
    a.line(235, 151, 640, 151)
    a.box(302, 180, 638, 263, "soft", r=11)
    a.text(321, 192, "帮我做一个每周支出记录工具，", 15)
    a.text(321, 220, "可以添加金额、分类和备注。", 15)
    a.text(302, 271, "你 · 10:14", 12, "subtle")
    a.circle(263, 334, 16, "green")
    a.text(253, 317, "M", 19, "white", True)
    a.text(289, 315, "已明确需求，生成版本 v3。", 15)
    a.box(290, 357, 639, 503, "#F8F9F5", "line", r=10)
    a.text(309, 369, "已明确内容", 16, "ink", True)
    a.line(308, 405, 622, 405)
    a.text(309, 422, "目标：记录与查看每周支出", 14, "muted")
    a.text(309, 449, "功能：添加、分类、统计", 14, "muted")
    a.text(309, 476, "数据：刷新后仍可读取", 14, "muted")
    a.circle(263, 561, 16, "green")
    a.text(253, 544, "M", 19, "white", True)
    a.text(289, 543, "代码已保存，可以继续迭代。", 15)
    a.text(289, 573, "右侧可查看当前版本和项目状态。", 13, "muted")
    a.box(236, 856, 640, 970, "paper", "line", r=13)
    a.text(254, 873, "继续描述要修改的内容…", 15, "subtle")
    a.line(254, 923, 622, 923)
    a.text(254, 935, "发送后创建新的迭代", 12, "subtle")
    a.box(594, 932, 624, 962, "green", r=8)
    a.text(602, 933, "↑", 19, "white", True)


def shell(active="工作台", status="代码已保存"):
    a = Art()
    topbar(a, "每周支出记录", status)
    project_nav(a, active)
    chat(a)
    a.box(660, 72, W, H, "paper", r=0)
    a.line(660, 72, 660, H)
    return a


def right_title(a, title, subtitle, chip=None):
    a.text(700, 110, title, 31, "ink", True)
    a.text(702, 160, subtitle, 15, "muted")
    if chip:
        a.pill(1393, 117, chip[0], chip[1], chip[2], size=14, h=34)
    a.line(700, 199, 1555, 199)


def hub():
    a = Art()
    topbar(a)
    a.box(0, 72, 216, H, "nav", r=0)
    a.line(215, 72, 215, H)
    a.text(23, 104, "导航", 13, "subtle", True)
    nav_item(a, 136, "所有项目", True)
    nav_item(a, 190, "新建项目")
    a.line(19, 258, 197, 258)
    a.text(23, 279, "最近访问", 13, "subtle", True)
    for y, value in [(318, "每周支出记录"), (362, "面试练习助手"), (406, "阅读清单")]:
        a.text(28, y, value, 14, "muted")
    a.text(25, 948, "所有项目只显示可访问内容", 12, "subtle")
    a.text(271, 113, "从一个想法，开始新的项目。", 37, "ink", True)
    a.text(273, 170, "描述你希望做成什么网页应用，或继续已有项目。", 17, "muted")
    a.box(269, 222, 1543, 410, "paper", "line", r=14)
    a.text(294, 244, "新建项目", 19, "ink", True)
    a.text(295, 281, "例如：做一个可以记录每周支出、按分类统计的网页应用…", 17, "subtle")
    a.line(291, 341, 1520, 341)
    a.text(295, 361, "项目名称（可选）", 13, "muted")
    a.box(424, 353, 879, 394, "paper", "line", r=7)
    a.text(441, 362, "每周支出记录", 14, "muted")
    a.text(1020, 363, "试试示例需求", 14, "green")
    a.box(1342, 353, 1520, 395, "orange", r=7)
    a.text(1375, 361, "创建并开始  →", 15, "white", True)
    a.text(272, 455, "最近项目", 23, "ink", True)
    a.text(272, 489, "按最近活动排序，状态来自真实项目记录。", 14, "muted")
    a.box(1260, 453, 1541, 498, "paper", "line", r=8)
    a.text(1276, 464, "搜索项目名称", 14, "subtle")
    a.line(271, 522, 1540, 522)
    a.text(289, 535, "项目", 13, "subtle", True)
    a.text(764, 535, "当前状态 / 下一步", 13, "subtle", True)
    a.text(1132, 535, "最近版本", 13, "subtle", True)
    a.text(1325, 535, "最近活动", 13, "subtle", True)
    rows = [
        ("每周支出记录", "代码已保存 · 可继续迭代", "v3", "今天 10:17", "green"),
        ("面试练习助手", "等待计划确认 · 需要你处理", "—", "昨天 19:24", "warning"),
        ("阅读清单", "正在生成 · 可稍后返回", "v1", "10 月 29 日", "green"),
        ("活动报名页", "需要处理 · 构建失败", "v2", "10 月 26 日", "danger"),
    ]
    for i, (name, state, version, time, color) in enumerate(rows):
        y = 570 + 96*i
        a.line(271, y-4, 1540, y-4)
        a.circle(301, y+38, 20, "green_soft" if color == "green" else "warning_soft" if color == "warning" else "danger_soft")
        a.text(293, y+22, str(i+1), 16, color, True)
        a.text(337, y+15, name, 17, "ink", True)
        a.text(337, y+45, "Web 应用项目", 13, "muted")
        a.circle(770, y+37, 5, color)
        a.text(785, y+25, state, 15, "ink")
        a.text(1132, y+25, version, 15, "muted")
        a.text(1325, y+25, time, 14, "muted")
        a.text(1517, y+23, "›", 22, "green")
    return a.save("01-projects.png")


def workbench():
    a = shell("工作台")
    a.text(700, 108, "预览", 18, "green", True)
    a.text(781, 108, "代码", 18, "muted")
    a.line(697, 147, 758, 147, "green", 3)
    a.pill(1464, 106, "v3", "soft", "ink", 14, h=32)
    chevron(a, 1510, 122)
    a.line(690, 160, 1572, 160)
    a.box(690, 178, 1570, 970, "white", "line", r=12)
    a.text(722, 197, "每周支出记录", 20, "ink", True)
    for x, value in [(1363, "首页"), (1431, "统计"), (1499, "设置")]:
        a.text(x, 201, value, 14, "green" if value == "首页" else "muted", value == "首页")
    a.line(711, 240, 1550, 240)
    a.box(714, 260, 1547, 420, "green", r=11)
    a.text(747, 288, "本周支出", 18, "#DDEAE2")
    a.text(747, 327, "¥ 528.00", 43, "white", True)
    a.text(747, 386, "6 月 10 日 — 6 月 16 日", 14, "#DDEAE2")
    for i, h in enumerate((43, 70, 51, 91, 62, 77, 37)):
        a.box(1193+i*44, 393-h, 1215+i*44, 393, "#C5DBD0", r=3)
    a.text(721, 455, "支出记录", 21, "ink", True)
    a.text(1272, 455, "添加支出", 21, "ink", True)
    a.line(1245, 455, 1245, 932)
    for i, (name, desc, amount) in enumerate([
        ("午餐", "餐饮 · 6 月 12 日", "− ¥ 28.00"),
        ("地铁", "交通 · 6 月 12 日", "− ¥ 6.00"),
        ("超市购物", "生活 · 6 月 11 日", "− ¥ 86.00"),
        ("电影票", "娱乐 · 6 月 10 日", "− ¥ 45.00"),
        ("咖啡", "餐饮 · 6 月 10 日", "− ¥ 32.00"),
    ]):
        y = 513+i*83
        a.circle(744, y+15, 18, "green_soft")
        a.text(735, y+1, str(i+1), 16, "green", True)
        a.text(780, y-5, name, 16, "ink", True)
        a.text(780, y+25, desc, 13, "muted")
        a.text(1099, y+3, amount, 14, "ink", True)
        a.line(719, y+65, 1220, y+65)
    for y, label, value in [(530, "金额", "¥  0.00"), (640, "分类", "请选择分类"), (750, "备注", "输入备注…")]:
        a.text(1273, y-30, label, 15, "ink", True)
        a.box(1271, y, 1526, y+55, "paper", "line", r=7)
        a.text(1286, y+15, value, 14, "muted")
    chevron(a, 1502, 667)
    a.box(1271, 877, 1526, 931, "orange", r=7)
    a.text(1355, 889, "添加支出", 15, "white", True)
    return a.save("02-workbench.png")


def overview():
    a = shell("项目概览")
    right_title(a, "项目概览", "用一屏确认项目现在在哪里，以及接下来做什么。", ("代码已保存", "green_soft", "green"))
    a.box(700, 224, 1556, 355, "green_soft", r=11)
    a.text(725, 243, "当前阶段", 15, "muted")
    a.text(725, 279, "版本 v3 已保存", 26, "ink", True)
    a.text(725, 319, "可以继续提出修改；公开发布尚未完成。", 15, "muted")
    a.box(1327, 274, 1531, 322, "green", r=8)
    a.text(1351, 285, "回到工作台  →", 15, "white", True)
    a.text(702, 393, "项目目标", 21, "ink", True)
    a.text(703, 437, "做一个每周支出记录工具，支持添加金额、分类与备注，", 17)
    a.text(703, 469, "按周查看统计；刷新后仍能读取已保存记录。", 17)
    a.line(700, 520, 1556, 520)
    a.text(702, 553, "最新结果", 21, "ink", True)
    for i, (label, value, note) in enumerate([
        ("最近成功版本", "v3", "本次代码已保存"),
        ("测试概况", "3 项通过", "浏览器检查未执行"),
        ("发布状态", "未发布", "暂无公开链接"),
    ]):
        y = 610+i*75
        a.text(706, y, label, 15, "muted")
        a.text(908, y-4, value, 17, "ink", True)
        a.text(1127, y, note, 14, "muted")
        a.line(702, y+52, 1554, y+52)
    a.text(702, 872, "最近活动", 21, "ink", True)
    a.text(703, 914, "10:17  版本 v3 已保存       ·       10:15  计划已确认", 15, "muted")
    return a.save("03-overview.png")


def docs():
    a = shell("项目文档")
    right_title(a, "项目文档", "需求、计划与决定随项目版本保留；这里展示已确认的内容。")
    for x, label, active in [(702, "需求", True), (806, "计划", False), (910, "决定", False), (1014, "文件", False)]:
        a.text(x, 224, label, 16, "green" if active else "muted", active)
        if active:
            a.line(x-2, 260, x+61, 260, "green", 3)
    a.line(700, 261, 1556, 261)
    a.text(702, 295, "每周支出记录 · 已确认需求", 24, "ink", True)
    a.text(703, 341, "确认于 10 月 31 日 10:15   ·   对应规格版本 3", 13, "muted")
    a.line(702, 383, 1550, 383)
    a.text(702, 412, "目标", 19, "ink", True)
    a.text(703, 453, "让用户快速记录每天的支出，并看懂一周内的分类分布。", 16)
    a.text(702, 515, "核心功能", 19, "ink", True)
    for i, item in enumerate(["添加支出：金额、分类、日期、可选备注。", "浏览和筛选：按周查看记录，按分类筛选。", "统计：显示本周总额与每日趋势。"]):
        a.circle(710, 560+i*43, 4, "green")
        a.text(726, 547+i*43, item, 16)
    a.text(702, 715, "数据与边界", 19, "ink", True)
    a.text(703, 757, "记录需要保存；刷新页面后，已添加的内容仍能读取。", 16)
    a.text(703, 794, "本项目只生成 Web 应用；移动端体验由该应用的需求另定。", 15, "muted")
    a.box(702, 859, 1208, 931, "soft", r=9)
    a.text(719, 871, "需要改变需求？", 15, "ink", True)
    a.text(719, 898, "到工作台提出新要求，将形成新的运行与规格版本。", 14, "muted")
    a.line(1262, 292, 1262, 826)
    a.text(1290, 303, "本文目录", 14, "muted", True)
    a.text(1290, 352, "目标", 15, "green")
    a.text(1290, 397, "核心功能", 15, "muted")
    a.text(1290, 442, "数据与边界", 15, "muted")
    return a.save("04-docs.png")


def tests():
    a = shell("测试")
    right_title(a, "测试", "只显示实际执行的检查；每项结果可追到对应版本和证据。")
    a.pill(700, 221, "版本 v3", "soft", "ink", 14, h=36)
    a.text(875, 225, "3 项通过", 16, "green", True)
    a.text(1000, 225, "1 项未执行", 16, "warning", True)
    a.line(700, 278, 1556, 278)
    a.text(706, 302, "检查项", 14, "subtle", True)
    a.text(1134, 302, "结果", 14, "subtle", True)
    a.text(1310, 302, "证据", 14, "subtle", True)
    checks = [
        ("模板构建", "React + Vite 项目可构建", "通过", "查看日志", "green"),
        ("类型检查", "类型错误为 0", "通过", "查看日志", "green"),
        ("自动化测试", "项目用例已执行", "通过", "查看用例", "green"),
        ("浏览器检查", "尚无本版本的浏览器执行记录", "未执行", "暂无证据", "warning"),
    ]
    for i, (name, detail, status, evidence, color) in enumerate(checks):
        y = 353+i*117
        a.line(701, y-7, 1555, y-7)
        a.circle(722, y+41, 14, "green_soft" if color == "green" else "warning_soft")
        if color == "green":
            checkmark(a, 722, y+41)
        else:
            a.text(717, y+27, "!", 17, color, True)
        a.text(755, y+9, name, 18, "ink", True)
        a.text(755, y+46, detail, 14, "muted")
        a.pill(1110, y+20, status, "green_soft" if color == "green" else "warning_soft", color, 14, h=34)
        a.text(1309, y+27, evidence, 15, "green" if color == "green" else "muted")
    a.box(701, 835, 1553, 941, "soft", r=10)
    a.text(723, 850, "结果如何理解", 17, "ink", True)
    a.text(723, 882, "“代码已保存”和“构建通过”不等于浏览器流程已验证，也不等于公开发布。", 15, "muted")
    a.text(723, 910, "未执行项需要真实运行后才可更新状态。", 14, "muted")
    return a.save("05-tests.png")


def publish():
    a = shell("发布")
    right_title(a, "发布", "查看发布准备情况与真实公开链接；当前不会自动发布。", ("未发布", "warning_soft", "warning"))
    a.box(700, 223, 1555, 347, "warning_soft", r=11)
    a.text(724, 245, "尚未发布", 27, "ink", True)
    a.text(725, 294, "当前项目还没有公开访问地址。预览仅供项目内检查。", 16, "muted")
    a.text(702, 385, "发布前检查", 22, "ink", True)
    items = [
        ("代码版本", "v3 已保存", "已具备", "green"),
        ("构建与类型检查", "本版本检查通过", "已具备", "green"),
        ("浏览器验证", "尚未执行本版本的真实浏览器流程", "待完成", "warning"),
        ("公开环境", "发布服务尚未接入", "不可用", "warning"),
    ]
    for i, (name, detail, state, color) in enumerate(items):
        y = 442+i*91
        a.line(703, y-10, 1550, y-10)
        a.circle(721, y+24, 13, "green_soft" if color == "green" else "warning_soft")
        if color == "green":
            checkmark(a, 721, y+24)
        else:
            a.text(716, y+9, "!", 16, color, True)
        a.text(750, y+1, name, 17, "ink", True)
        a.text(750, y+34, detail, 14, "muted")
        a.pill(1430, y+10, state, "green_soft" if color == "green" else "warning_soft", color, 14, h=33)
    a.box(701, 838, 1554, 941, "soft", r=10)
    a.text(724, 851, "下一步", 17, "ink", True)
    a.text(724, 882, "完成真实浏览器验证，并接入发布环境后，这里才会提供发布操作与公开链接。", 15, "muted")
    a.text(724, 910, "查看测试  →", 14, "green", True)
    return a.save("06-publish.png")


def switcher():
    base = Image.open(OUT / "02-workbench.png").convert("RGBA")
    shade = Image.new("RGBA", (W, H), (18, 31, 27, 72))
    base = Image.alpha_composite(base, shade).convert("RGB")
    a = Art()
    a.im = base
    a.d = ImageDraw.Draw(a.im)
    a.box(19, 210, 447, 718, "paper", "line", r=13, width=2)
    a.text(42, 231, "切换项目", 21, "ink", True)
    a.text(409, 236, "×", 20, "muted")
    a.box(41, 282, 423, 331, "paper", "line", r=8)
    a.text(57, 294, "搜索项目名称…", 15, "subtle")
    a.text(42, 355, "最近项目", 13, "subtle", True)
    items = [
        ("每周支出记录", "当前项目 · 代码已保存", True),
        ("面试练习助手", "等待计划确认", False),
        ("阅读清单", "正在生成", False),
        ("活动报名页", "需要处理", False),
    ]
    for i, (name, detail, selected) in enumerate(items):
        y = 383+i*68
        if selected:
            a.box(38, y-1, 426, y+62, "green_soft", r=8)
        a.circle(61, y+29, 15, "green" if selected else "soft")
        a.text(53, y+14, str(i+1), 14, "white" if selected else "green", True)
        a.text(86, y+6, name, 16, "ink", selected)
        a.text(86, y+33, detail, 13, "muted")
        if selected:
            checkmark(a, 398, y+30)
    a.line(42, 659, 424, 659)
    a.text(46, 675, "所有项目", 15, "green", True)
    a.text(328, 675, "＋ 新建项目", 15, "green")
    return a.save("07-project-switcher.png")


def contact_sheet():
    names = [
        ("01  项目中心", "01-projects.png"),
        ("02  工作台", "02-workbench.png"),
        ("03  项目概览", "03-overview.png"),
        ("04  项目文档", "04-docs.png"),
        ("05  测试", "05-tests.png"),
        ("06  发布", "06-publish.png"),
    ]
    im = Image.new("RGB", (1650, 1730), C["canvas"])
    d = ImageDraw.Draw(im)
    d.text((44, 28), "MYATOM  ·  六个主页面", font=f(32, True), fill=C["ink"])
    d.text((44, 76), "项目中心跨项目；工作台与四个状态页共享当前项目和对话。", font=f(17), fill=C["muted"])
    for i, (label, filename) in enumerate(names):
        col, row = i % 2, i // 2
        x, y = 44 + col*810, 126 + row*522
        d.text((x, y), label, font=f(18, True), fill=C["green"])
        source = Image.open(OUT / filename)
        thumb = source.resize((755, 472), Image.Resampling.LANCZOS)
        im.paste(thumb, (x, y+38))
        d.rectangle((x, y+38, x+755, y+510), outline=C["line"], width=2)
    path = OUT / "00-contact-sheet.png"
    im.save(path, optimize=True)
    return path


if __name__ == "__main__":
    paths = [hub(), workbench(), overview(), docs(), tests(), publish(), switcher(), contact_sheet()]
    for path in paths:
        print(path)
