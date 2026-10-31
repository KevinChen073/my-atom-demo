"""Render MYATOM v3 VI board and desktop design review images."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).parent
PAGES = ROOT / "pages"
PAGES.mkdir(exist_ok=True)
FONT = r"C:\Windows\Fonts\msyh.ttc"
BOLD = r"C:\Windows\Fonts\msyhbd.ttc"
SERIF = r"C:\Windows\Fonts\simsun.ttc"

K = {
    "bg": "#F5F4EF", "paper": "#FFFEFA", "nav": "#F0F1EB",
    "soft": "#F4F5F0", "ink": "#172522", "muted": "#52645B",
    "quiet": "#69776E", "line": "#D7DED6", "strong": "#BDC9BE",
    "green": "#245C50", "green2": "#1D4B41", "green_soft": "#E7F0EA",
    "orange": "#A64B2B", "orange_soft": "#F8EBE3",
    "warning": "#89501F", "warning_soft": "#F8EBD9",
    "danger": "#A43D34", "danger_soft": "#FAE9E5",
    "blue": "#233A4F", "blue_mid": "#4A7194", "blue_soft": "#E8EEF1",
    "preview_bg": "#E8EBE9", "white": "#FFFFFF",
}


def font(size, weight="regular"):
    return ImageFont.truetype(SERIF if weight == "serif" else BOLD if weight == "bold" else FONT, size)


class Art:
    def __init__(self, size=(1600, 1000), bg="bg"):
        self.im = Image.new("RGB", size, K[bg])
        self.d = ImageDraw.Draw(self.im)
        self.w, self.h = size

    def rr(self, box, fill="paper", outline=None, r=10, width=1):
        self.d.rounded_rectangle(box, radius=r, fill=K.get(fill, fill),
                                 outline=K.get(outline, outline) if outline else None,
                                 width=width)

    def rect(self, box, fill, outline=None, width=1):
        self.d.rectangle(box, fill=K.get(fill, fill),
                         outline=K.get(outline, outline) if outline else None, width=width)

    def line(self, points, color="line", width=1):
        self.d.line(points, fill=K.get(color, color), width=width, joint="curve")

    def circle(self, x, y, r, fill, outline=None, width=1):
        self.d.ellipse((x-r, y-r, x+r, y+r), fill=K.get(fill, fill),
                       outline=K.get(outline, outline) if outline else None, width=width)

    def text(self, x, y, value, size=16, color="ink", weight="regular"):
        self.d.text((x, y), value, font=font(size, weight), fill=K.get(color, color))

    def pill(self, x, y, label, fill="green_soft", color="green", size=13, px=12, h=30):
        width = int(self.d.textlength(label, font=font(size))) + px * 2
        self.rr((x, y, x+width, y+h), fill, r=h//2)
        self.text(x+px, y+(h-size)//2-2, label, size, color)
        return width

    def save(self, path):
        self.im.save(path, optimize=True)
        return path


def mark(a, x, y, s=31, dark=False):
    stroke = "white" if dark else "green"
    t = max(3, int(s*0.11))
    a.line([(x+s*.39, y+s*.16), (x+s*.19, y+s*.16), (x+s*.19, y+s*.84), (x+s*.39, y+s*.84)], stroke, t)
    a.line([(x+s*.61, y+s*.16), (x+s*.81, y+s*.16), (x+s*.81, y+s*.84), (x+s*.61, y+s*.84)], stroke, t)
    a.circle(x+s/2, y+s/2, s*.105, "orange")


def icon(a, name, x, y, color="muted", s=20):
    q = s/20
    def line(*xy):
        a.line([(x+xy[i]*q, y+xy[i+1]*q) for i in range(0,len(xy),2)], color, max(1,int(1.8*q)))
    if name == "workbench":
        a.rr((x+2*q,y+3*q,x+18*q,y+17*q), outline=color, fill="nav", r=2, width=2)
        line(8,3,8,17); line(2,8,8,8); line(11,8,15,8); line(11,11,14,11)
    elif name == "overview":
        for yy in (4,10,16): line(4,yy,16,yy)
        for xx,yy in ((5.5,4),(10,10),(14.5,16)): a.circle(x+xx*q,y+yy*q,1.5*q,color)
    elif name == "docs":
        line(5,2.5,12,2.5,16,6.5,16,17,4,17,4,4,5,2.5)
        line(12,2.5,12,6.5,16,6.5); line(7,10,13,10); line(7,13,13,13)
    elif name == "tests":
        a.circle(x+10*q,y+10*q,7.4*q,"nav",color,2)
        line(6.5,10,9,12.5,13.6,7.5)
    elif name == "publish":
        line(10,3,16,3,16,9); line(16,3,8,11)
        line(10,4.5,5,4.5,3.5,6,3.5,16,5,17.5,15,17.5,16.5,16,16.5,11)
    elif name == "search":
        a.circle(x+8*q,y+8*q,5*q,"paper",color,2); line(12,12,17,17)
    elif name == "plus":
        line(10,3,10,17); line(3,10,17,10)
    elif name == "chevron":
        line(5,8,10,13,15,8)
    elif name == "arrow":
        line(3,10,16,10); line(11,5,16,10,11,15)


def brand(a):
    mark(a, 25, 18, 34)
    a.text(72, 21, "MYATOM", 22, "ink", "bold")


def topbar(a, project=None):
    a.rect((0,0,1599,70), "paper")
    a.line([(0,70),(1600,70)], "line")
    brand(a)
    a.line([(214,0),(214,70)], "line")
    if project:
        a.text(240, 24, "所有项目", 14, "muted")
        a.text(320, 22, "／", 17, "quiet")
        a.text(350, 20, project, 19, "ink", "bold")
        a.pill(567, 20, "版本 v3 已保存", "green_soft", "green", 13, 11, 31)
    else:
        a.text(240, 20, "所有项目", 20, "ink", "bold")
    a.text(1484, 25, "帮助", 14, "muted")


def project_badge(a, x, y, label, fill="green_soft", color="green", size=34):
    a.rr((x,y,x+size,y+size),fill,r=9)
    a.text(x+(size-26)//2, y+(size-18)//2-3,label,18,color,"bold")


def nav_item(a,y,label,name,active=False):
    if active:
        a.rr((13,y,200,y+45),"green_soft",r=8)
        a.rr((13,y,17,y+45),"green",r=2)
    icon(a,name,32,y+12,"green" if active else "muted",20)
    a.text(65,y+11,label,15,"ink" if active else "muted","bold" if active else "regular")


def side(a, active):
    a.rect((0,71,214,999),"nav")
    a.line([(214,71),(214,1000)],"line")
    a.text(26,102,"当前项目",12,"quiet","bold")
    a.rr((15,129,200,204),"paper","line",10)
    project_badge(a,27,148,"支","blue_soft","blue",35)
    a.text(74,144,"每周支出记录",14,"ink","bold")
    a.text(74,173,"切换项目",12,"green")
    icon(a,"chevron",174,156,"muted",16)
    a.text(27,237,"项目空间",12,"quiet","bold")
    for i,(label,name) in enumerate((
        ("工作台","workbench"),("项目概览","overview"),("项目文档","docs"),
        ("测试","tests"),("发布","publish"))):
        nav_item(a,266+i*53,label,name,label==active)
    a.line([(21,557),(194,557)],"line")
    icon(a,"arrow",27,578,"green",17)
    a.text(54,576,"所有项目",14,"green")
    a.text(25,941,"访客空间",12,"quiet")
    a.text(25,961,"项目内容按身份隔离",11,"quiet")


def chat(a):
    a.rect((215,71,640,999),"paper")
    a.line([(640,71),(640,1000)],"line")
    a.text(242,103,"对话",21,"ink","bold")
    a.pill(529,101,"本次运行", "soft","muted",12,10,29)
    a.line([(238,149),(619,149)],"line")
    a.text(244,175,"你",13,"muted","bold")
    a.text(577,175,"10:14",12,"quiet")
    a.rr((244,204,617,283),"soft",r=10)
    a.text(260,216,"做一个每周支出记录工具，",15)
    a.text(260,242,"支持分类、统计和保存。",15)
    mark(a,243,319,25)
    a.text(279,315,"已确认需求",15,"ink","bold")
    a.text(544,319,"10:15",12,"quiet")
    a.rr((279,352,617,514),"paper","line",10)
    a.rr((279,352,283,514),"orange",r=2)
    a.text(298,366,"本次将完成",15,"ink","bold")
    a.text(298,400,"01",13,"orange","bold"); a.text(328,398,"记录金额、分类和备注",14,"ink")
    a.text(298,432,"02",13,"orange","bold"); a.text(328,430,"按周查看统计",14,"ink")
    a.text(298,464,"03",13,"orange","bold"); a.text(328,462,"刷新后读取已存记录",14,"ink")
    a.line([(296,495),(600,495)],"line")
    a.text(298,497,"已确认 · 规格 3",12,"muted")
    mark(a,243,554,25)
    a.text(279,551,"版本已保存",15,"ink","bold")
    a.rr((279,589,617,685),"green_soft",r=10)
    a.text(298,602,"版本 v3",17,"green","bold")
    a.text(298,633,"构建完成 · 预览已就绪",14,"muted")
    a.text(298,662,"可以在右侧体验，或继续提出修改。",13,"muted")
    a.text(242,809,"继续迭代",13,"quiet","bold")
    a.rr((237,834,620,969),"paper","line",12)
    a.text(255,851,"描述你想修改的地方…",15,"quiet")
    a.line([(254,918),(603,918)],"line")
    a.text(255,934,"新要求将形成下一版本",12,"quiet")
    a.rr((570,927,605,959),"green",r=8)
    a.text(582,930,"↑",18,"white","bold")


def shell(active="工作台"):
    a=Art()
    topbar(a,"每周支出记录")
    side(a,active)
    chat(a)
    a.rect((641,71,1599,999),"paper")
    a.line([(640,71),(640,1000)],"line")
    return a


def right_head(a,eyebrow,title,subtitle,badge=None):
    a.text(682,103,eyebrow,12,"green","bold")
    a.text(681,132,title,30,"ink","bold")
    a.text(682,181,subtitle,14,"muted")
    if badge:
        a.pill(1430,129,badge[0],badge[1],badge[2],13,13,33)
    a.line([(680,218),(1560,218)],"line")


def hub():
    a=Art()
    topbar(a)
    a.rect((0,71,214,999),"nav")
    a.line([(214,71),(214,1000)],"line")
    a.text(26,108,"导航",12,"quiet","bold")
    a.rr((13,139,200,184),"green_soft",r=8);a.rr((13,139,17,184),"green",r=2)
    icon(a,"overview",31,152,"green");a.text(65,151,"所有项目",15,"ink","bold")
    icon(a,"plus",31,208,"muted");a.text(65,205,"新建项目",15,"muted")
    a.line([(22,272),(194,272)],"line")
    a.text(26,292,"最近访问",12,"quiet","bold")
    for i,(name,abbr,fill,color) in enumerate((
        ("每周支出记录","支","blue_soft","blue"),
        ("面试练习助手","面","orange_soft","orange"),
        ("阅读清单","阅","green_soft","green"))):
        y=327+i*54
        project_badge(a,28,y,abbr,fill,color,28)
        a.text(66,y+4,name,13,"muted")
    a.text(25,950,"MYATOM · DESKTOP",11,"quiet")

    a.text(263,119,"从想法，到可以验证的作品。",43,"ink","serif")
    a.text(266,180,"写下目标，确认计划，和 AI 一起把应用做出来。",16,"muted")
    a.line([(265,230),(1535,230)],"line")
    a.text(266,252,"01  开始一个新项目",16,"green","bold")
    a.rr((265,294,1539,461),"paper","line",13)
    a.text(292,319,"你想做什么应用？",19,"ink","bold")
    a.text(292,357,"例如：做一个每周支出记录工具，支持分类统计和数据保存…",16,"quiet")
    a.line([(289,401),(1514,401)],"line")
    a.text(292,417,"项目名称（可选）",13,"muted")
    a.rr((419,411,812,450),"paper","line",7)
    a.text(432,419,"每周支出记录",14,"quiet")
    a.text(1067,420,"使用示例需求",14,"green")
    a.rr((1329,408,1512,450),"orange",r=7)
    a.text(1358,416,"创建并开始",15,"white","bold")
    icon(a,"arrow",1480,419,"white",16)

    a.text(267,506,"02  继续已有项目",16,"green","bold")
    a.text(267,537,"最近活动",24,"ink","bold")
    a.text(267,575,"找回正在进行的工作；状态只展示已核实的结果。",14,"muted")
    a.rr((1267,537,1539,581),"paper","line",8)
    icon(a,"search",1280,550,"muted",18)
    a.text(1305,547,"搜索项目",14,"quiet")
    a.line([(266,611),(1539,611)],"line")
    a.text(277,625,"项目",13,"quiet","bold")
    a.text(821,625,"当前状态",13,"quiet","bold")
    a.text(1217,625,"最近版本",13,"quiet","bold")
    for i,(name,abbr,fill,color,state,version,when) in enumerate((
        ("每周支出记录","支","blue_soft","blue","代码已保存 · 继续迭代","v3","今天 10:17"),
        ("面试练习助手","面","orange_soft","orange","等待计划确认","—","昨天 19:24"),
        ("阅读清单","阅","green_soft","green","正在生成","v1","10 月 29 日"),
    )):
        y=665+i*102
        a.line([(267,y-11),(1538,y-11)],"line")
        project_badge(a,276,y+9,abbr,fill,color,43)
        a.text(335,y+4,name,17,"ink","bold")
        a.text(335,y+37,"Web 应用项目",13,"muted")
        a.text(820,y+21,state,15,"ink")
        a.text(1218,y+21,version,15,"muted")
        a.text(1361,y+21,when,14,"muted")
        icon(a,"arrow",1504,y+18,"green",15)
    return a.save(PAGES/"01-projects.png")


def workbench():
    a=shell("工作台")
    a.text(681,101,"APP VIEWER",12,"green","bold")
    a.text(681,129,"应用预览",26,"ink","bold")
    a.pill(825,133,"可交互 · v3","green_soft","green",13,11,28)
    a.text(1369,128,"预览",16,"green","bold")
    a.text(1452,128,"代码",16,"muted")
    a.line([(1368,162),(1421,162)],"green",3)
    a.line([(680,172),(1560,172)],"line")
    a.rr((679,187,1561,968),"preview_bg",r=14)
    a.rr((704,208,1537,941),"#D8DDDA",r=13)
    a.rr((701,204,1534,938),"white","strong",13)
    a.rr((701,204,1534,242),"#F6F8F9",r=13)
    a.line([(702,242),(1533,242)],"#DAE2E6")
    for i,c in enumerate(("#C8D3D9","#C8D3D9","#C8D3D9")):a.circle(721+i*14,223,4,c)
    a.text(1242,212,"预览环境 · 当前版本 v3",12,"#607481")
    a.rect((702,243,1533,937),"#FAFBFC")
    a.text(735,264,"WEEKLY",13,"blue_mid","bold")
    a.text(735,285,"每周支出记录",21,"blue","bold")
    for x,label in ((1340,"记录"),(1404,"统计"),(1468,"设置")):
        a.text(x,282,label,14,"blue" if label=="记录" else "#708392","bold" if label=="记录" else "regular")
    a.line([(733,324),(1503,324)],"#D8E0E5")
    a.rr((733,344,1502,496),"blue",r=12)
    a.text(762,367,"本周支出",16,"#BED0DC")
    a.text(762,399,"¥ 528.00",41,"white","bold")
    a.text(762,458,"6 月 10 日 — 6 月 16 日",13,"#C7D7E2")
    for i,h in enumerate((26,50,40,74,45,63,32)):
        a.rr((1211+i*39,468-h,1227+i*39,468),"#9FC3D8",r=3)
    a.text(737,526,"最近记录",20,"blue","bold")
    a.text(1255,526,"添加支出",20,"blue","bold")
    a.line([(1233,531),(1233,905)],"#D7E0E6")
    for i,(name,category,amount) in enumerate((
        ("午餐","餐饮 · 6 月 12 日","− ¥ 28.00"),
        ("地铁","交通 · 6 月 12 日","− ¥ 6.00"),
        ("超市购物","生活 · 6 月 11 日","− ¥ 86.00"),
        ("电影票","娱乐 · 6 月 10 日","− ¥ 45.00"))):
        y=581+i*78
        a.circle(756,y+10,18,"#E7EEF2")
        a.text(748,y-4,str(i+1),14,"blue_mid","bold")
        a.text(786,y-9,name,15,"blue","bold")
        a.text(786,y+18,category,12,"#748895")
        a.text(1087,y+1,amount,14,"blue","bold")
        a.line([(737,y+58),(1209,y+58)],"#DEE6E9")
    for y,label,value in ((593,"金额","¥  0.00"),(691,"分类","请选择分类"),(789,"备注","输入备注…")):
        a.text(1256,y-27,label,14,"blue","bold")
        a.rr((1254,y,1487,y+50),"white","#CCD8DF",7)
        a.text(1267,y+11,value,14,"#718492")
    a.rr((1254,869,1487,912),"blue_mid",r=7)
    a.text(1329,877,"添加支出",14,"white","bold")
    return a.save(PAGES/"02-workbench.png")


def overview():
    a=shell("项目概览")
    right_head(a,"PROJECT / 01","项目概览","看清当前进度，再决定下一步。",("代码已保存","green_soft","green"))
    a.text(683,250,"从需求到版本，正在继续。",27,"ink","serif")
    a.text(684,302,"当前可以继续修改应用；公开发布尚未完成。",15,"muted")
    a.rr((1328,254,1555,300),"green",r=7)
    a.text(1356,264,"返回工作台",14,"white","bold")
    icon(a,"arrow",1504,268,"white",17)
    a.line([(684,349),(1558,349)],"line")
    a.text(686,381,"项目阶段",19,"ink","bold")
    a.line([(712,441),(712,717)],"strong",2)
    stages=(
        ("01","需求已确认","10:15 · 规格 3"),
        ("02","计划已确认","10:16 · 开始生成"),
        ("03","版本已保存","10:17 · 版本 v3"),
        ("04","浏览器验证","尚未执行"),
    )
    for i,(num,label,detail) in enumerate(stages):
        y=444+i*87
        a.circle(712,y,12,"green" if i<3 else "paper","green" if i>=3 else None,2)
        if i<3:
            a.line([(706,y),(710,y+4),(718,y-5)],"white",2)
        else:
            a.text(708,y-10,"4",13,"green","bold")
        a.text(746,y-16,label,17,"ink","bold" if i==2 else "regular")
        a.text(746,y+14,detail,13,"muted")
    a.line([(1071,381),(1071,815)],"line")
    a.text(1103,381,"项目目标",19,"ink","bold")
    a.text(1103,425,"记录每周支出，",16)
    a.text(1103,453,"按分类与日期查看统计。",16)
    a.text(1103,511,"最新版本",19,"ink","bold")
    a.text(1103,554,"v3 已保存",20,"green","bold")
    a.text(1103,588,"构建通过 · 预览可用",14,"muted")
    a.text(1103,649,"下一步",19,"ink","bold")
    a.text(1103,691,"继续迭代或完成浏览器验证。",15,"muted")
    a.rr((682,840,1558,935),"soft",r=10)
    a.text(702,855,"最近活动",15,"ink","bold")
    a.text(702,889,"10:17  保存版本 v3     /     10:16  确认计划     /     10:15  确认需求",14,"muted")
    return a.save(PAGES/"03-overview.png")


def docs():
    a=shell("项目文档")
    right_head(a,"DOCUMENTS / 02","项目文档","需求、计划与决定按规格版本保留。")
    for x,label,active in ((684,"需求",True),(792,"计划",False),(899,"决定",False),(1006,"文件",False)):
        a.text(x,239,label,16,"green" if active else "muted","bold" if active else "regular")
        if active:a.line([(x,275),(x+55,275)],"green",3)
    a.line([(682,276),(1558,276)],"line")
    a.text(684,317,"需求说明",30,"ink","serif")
    a.text(685,365,"每周支出记录   /   已确认于 10 月 31 日 10:15   /   规格 3",13,"muted")
    a.line([(684,402),(1236,402)],"line")
    a.text(684,427,"01",13,"orange","bold")
    a.text(728,423,"目标",20,"ink","bold")
    a.text(728,469,"让用户快速记录每天的支出，并看懂一周内",16)
    a.text(728,498,"的分类与日期分布。",16)
    a.text(684,568,"02",13,"orange","bold")
    a.text(728,563,"核心功能",20,"ink","bold")
    for i,text in enumerate(("添加金额、分类、日期与可选备注。","按周浏览记录，并按分类筛选。","显示本周总额和每日变化。")):
        y=608+i*38
        a.circle(738,y+12,3,"green")
        a.text(754,y,text,15)
    a.text(684,765,"03",13,"orange","bold")
    a.text(728,760,"数据与边界",20,"ink","bold")
    a.text(728,805,"刷新后，已保存的记录仍可读取。",15)
    a.rr((683,866,1237,935),"soft",r=9)
    a.text(702,880,"要修改已确认内容？",15,"ink","bold")
    a.text(702,907,"在工作台提出新要求，形成新的运行与规格版本。",13,"muted")
    a.line([(1264,316),(1264,830)],"line")
    a.text(1294,325,"目录",14,"quiet","bold")
    for i,label in enumerate(("01  目标","02  核心功能","03  数据与边界")):
        a.text(1295,371+i*49,label,14,"green" if i==0 else "muted")
    return a.save(PAGES/"04-docs.png")


def tests():
    a=shell("测试")
    right_head(a,"TEST REPORT / 03","测试","结论与证据对应同一个版本；未执行项单独列出。")
    a.text(684,250,"3 / 4",45,"ink","bold")
    a.text(827,263,"检查已执行",18,"ink","bold")
    a.text(827,294,"版本 v3 · 1 项浏览器检查尚未运行",14,"muted")
    for i,col in enumerate(("green","green","green","#E6D9C9")):
        a.rr((684+i*218,348,892+i*218,356),col,r=4)
    a.text(684,385,"检查项",13,"quiet","bold")
    a.text(1122,385,"结果",13,"quiet","bold")
    a.text(1361,385,"证据",13,"quiet","bold")
    rows=(
        ("模板构建","React + Vite 项目可构建","通过","查看日志",True),
        ("类型检查","类型错误为 0","通过","查看日志",True),
        ("自动化测试","项目用例已执行","通过","查看用例",True),
        ("浏览器检查","暂无本版本执行记录","未执行","暂无证据",False),
    )
    for i,(name,desc,state,link,ok) in enumerate(rows):
        y=422+i*104
        a.line([(682,y),(1558,y)],"line")
        a.circle(706,y+47,14,"green_soft" if ok else "warning_soft")
        if ok:a.line([(700,y+47),(705,y+52),(714,y+41)],"green",2)
        else:a.text(702,y+31,"!",16,"warning","bold")
        a.text(739,y+19,name,17,"ink","bold")
        a.text(739,y+51,desc,13,"muted")
        a.pill(1112,y+28,state,"green_soft" if ok else "warning_soft","green" if ok else "warning",13,12,31)
        a.text(1360,y+33,link,14,"green" if ok else "muted")
    a.rr((683,855,1557,935),"soft",r=9)
    a.text(702,868,"结果解释",15,"ink","bold")
    a.text(702,900,"构建通过代表代码检查通过；浏览器流程需要实际运行后才能标记完成。",14,"muted")
    return a.save(PAGES/"05-tests.png")


def publish():
    a=shell("发布")
    right_head(a,"RELEASE / 04","发布","检查发布条件，并只在真实上线后展示公开链接。",("未发布","warning_soft","warning"))
    a.text(684,251,"尚未发布",36,"ink","serif")
    a.text(685,310,"当前项目还没有公开访问地址。预览可供项目内检查。",15,"muted")
    a.line([(684,361),(1558,361)],"line")
    a.text(684,396,"发布前检查",20,"ink","bold")
    conditions=(
        ("代码版本","v3 已保存","已具备",True),
        ("构建与类型检查","本版本检查通过","已具备",True),
        ("浏览器验证","尚未执行真实业务流程","待完成",False),
        ("公开环境","发布服务尚未接入","不可用",False),
    )
    for i,(name,desc,state,ok) in enumerate(conditions):
        y=453+i*82
        a.line([(684,y-4),(1223,y-4)],"line")
        a.circle(704,y+27,12,"green_soft" if ok else "warning_soft")
        if ok:a.line([(699,y+27),(703,y+31),(710,y+23)],"green",2)
        else:a.text(700,y+13,"!",14,"warning","bold")
        a.text(734,y+5,name,16,"ink","bold")
        a.text(734,y+36,desc,13,"muted")
        a.text(1120,y+20,state,13,"green" if ok else "warning","bold")
    a.line([(1260,400),(1260,801)],"line")
    a.text(1290,401,"公开链接",19,"ink","bold")
    a.rr((1287,445,1556,613),"soft",r=10)
    icon(a,"publish",1310,469,"muted",24)
    a.text(1310,518,"尚无公开地址",16,"ink","bold")
    a.text(1310,552,"发布成功后显示真实 URL",13,"muted")
    a.text(1310,579,"及对应版本。",13,"muted")
    a.rr((683,850,1558,936),"warning_soft",r=9)
    a.text(703,865,"下一步",15,"ink","bold")
    a.text(703,896,"完成真实浏览器验证，并接入发布环境后，再启用发布操作。",14,"muted")
    a.text(1447,895,"查看测试  →",13,"green","bold")
    return a.save(PAGES/"06-publish.png")


def switcher():
    base=Image.open(PAGES/"02-workbench.png").convert("RGBA")
    shade=Image.new("RGBA",base.size,(18,31,27,73))
    a=Art()
    a.im=Image.alpha_composite(base,shade).convert("RGB")
    a.d=ImageDraw.Draw(a.im)
    a.rr((16,210,449,726),"paper","strong",13,2)
    a.text(39,235,"切换项目",21,"ink","bold")
    a.text(409,239,"×",20,"muted")
    a.rr((37,283,426,331),"paper","line",8)
    icon(a,"search",53,296,"muted",18)
    a.text(80,293,"搜索项目名称",14,"quiet")
    a.text(41,353,"最近项目",13,"quiet","bold")
    items=(
        ("每周支出记录","支","blue_soft","blue","当前项目 · 版本 v3"),
        ("面试练习助手","面","orange_soft","orange","等待计划确认"),
        ("阅读清单","阅","green_soft","green","正在生成"),
        ("活动报名页","报","warning_soft","warning","需要处理"),
    )
    for i,(name,abbr,fill,color,status) in enumerate(items):
        y=383+i*67
        if i==0:a.rr((35,y-3,430,y+60),"green_soft",r=8)
        project_badge(a,51,y+8,abbr,fill,color,36)
        a.text(100,y+3,name,15,"ink","bold" if i==0 else "regular")
        a.text(100,y+31,status,12,"muted")
        if i==0:a.line([(389,y+27),(394,y+32),(404,y+20)],"green",2)
    a.line([(38,660),(426,660)],"line")
    a.text(42,678,"所有项目",14,"green","bold")
    a.text(312,678,"＋ 新建项目",14,"green")
    return a.save(PAGES/"07-project-switcher.png")


def vi_board():
    a=Art((1600,1110))
    a.text(56,45,"MYATOM",14,"green","bold")
    a.text(56,78,"视觉识别与界面语言",39,"ink","serif")
    a.text(58,139,"清晰的制作台 · 从想法到可验证版本",17,"muted")
    a.line([(58,181),(1542,181)],"line")
    a.text(59,209,"01  品牌标记",16,"green","bold")
    a.rr((59,254,634,505),"paper","line",12)
    mark(a,95,291,92)
    a.text(213,302,"MYATOM",44,"ink","bold")
    a.text(214,369,"开口框  /  中央节点",15,"muted")
    a.text(95,450,"构图取意：输入、处理、形成可查看的结果。",14,"muted")
    a.text(693,209,"02  色彩与比例",16,"green","bold")
    colors=(("纸白","paper","#FFFEFA"),("墨绿","green","#245C50"),("陶土","orange","#A64B2B"),("结构灰","nav","#F0F1EB"))
    for i,(label,key,hexval) in enumerate(colors):
        x=693+i*212
        a.rr((x,254,x+186,413),key,"line" if key in ("paper","nav") else None,9)
        a.text(x,427,label,15,"ink","bold")
        a.text(x,454,hexval,13,"muted")
    a.text(694,491,"暖中性色为底；橙色只用于关键决定和品牌节点。",14,"muted")
    a.line([(58,544),(1542,544)],"line")
    a.text(59,566,"03  字体层级",16,"green","bold")
    a.text(59,605,"把想法做成能使用的应用。",34,"ink","serif")
    a.text(60,672,"页面标题  /  系统无衬线  30px",22,"ink","bold")
    a.text(60,714,"正文 16px · 保持可读行长、明确的动作和真实状态。",16,"muted")
    a.text(831,566,"04  线性图标",16,"green","bold")
    for i,(label,name) in enumerate((
        ("工作台","workbench"),("概览","overview"),("文档","docs"),("测试","tests"),("发布","publish"))):
        x=841+i*134
        a.rr((x,606,x+74,680),"green_soft",r=11)
        icon(a,name,x+23,629,"green",28)
        a.text(x,700,label,14,"muted")
    a.line([(58,763),(1542,763)],"line")
    a.text(59,788,"05  交互反馈",16,"green","bold")
    a.text(59,827,"同项目换页：对话不动，右侧内容轻淡入。",16,"ink")
    a.text(59,861,"项目切换：先隐去旧项目，再加载目标项目。",16,"muted")
    for i,(label,body) in enumerate((
        ("01 工作台","对话  │  预览"),("02 切换中","对话  │  页面过渡"),("03 测试页","对话  │  测试结果"))):
        x=59+i*506
        a.rr((x,914,x+460,1039),"paper","line",10)
        a.text(x+16,929,label,14,"green","bold")
        a.rr((x+16,965,x+150,1017),"soft",r=5)
        a.rr((x+162,965,x+443,1017),"green_soft" if i!=1 else "#EEF0EB",r=5)
        a.text(x+25,981,body.split("│")[0],13,"muted")
        a.text(x+172,981,body.split("│")[1].strip(),13,"green" if i!=1 else "muted")
    a.text(59,1064,"常规 120–180ms · 确认反馈约 220ms · 减少动态效果时即时切换",13,"quiet")
    return a.save(ROOT/"vi-board.png")


def contact_sheet():
    im=Image.new("RGB",(1650,1740),K["bg"])
    d=ImageDraw.Draw(im)
    d.text((43,24),"MYATOM  ·  V3 页面精修",font=font(34,"bold"),fill=K["ink"])
    d.text((43,75),"六个主页面维持原交互，视觉识别、图标和层级统一升级。",font=font(17),fill=K["muted"])
    names=(("01  项目中心","01-projects.png"),("02  AI 工作台","02-workbench.png"),
           ("03  项目概览","03-overview.png"),("04  项目文档","04-docs.png"),
           ("05  测试","05-tests.png"),("06  发布","06-publish.png"))
    for i,(label,file) in enumerate(names):
        x=43+(i%2)*810;y=124+(i//2)*524
        d.text((x,y),label,font=font(18,"bold"),fill=K["green"])
        thumb=Image.open(PAGES/file).resize((754,471),Image.Resampling.LANCZOS)
        im.paste(thumb,(x,y+37))
        d.rectangle((x,y+37,x+754,y+508),outline=K["line"],width=2)
    path=PAGES/"00-contact-sheet.png"
    im.save(path,optimize=True)
    return path


if __name__=="__main__":
    files=[hub(),workbench(),overview(),docs(),tests(),publish(),switcher(),vi_board(),contact_sheet()]
    for file in files:print(file)
