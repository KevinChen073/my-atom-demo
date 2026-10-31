# MYATOM · MVP2 本地开发版

一个本地可运行的 Atoms 类应用生成工作台。用户创建项目、确认需求澄清和 Build Plan 后，单 Agent 在固定的 React + TypeScript + Vite 模板中生成代码，实际执行类型检查与构建，并保存可恢复的项目版本。

产品范围见 [PRD](docs/PRD.md)，架构见 [系统设计](docs/ARCHITECTURE.md)，本轮实现见 [MVP2 落地映射](docs/MVP2-IMPLEMENTATION.md)。工作台视觉以 [V3 设计](design/v3/README.md) 为准，浏览器验收见 [V3 TC](tests/cases/DESIGN-V3.md)。首页示例由 [目录](examples/catalog.json) 定义，交互见 [示例 UI](docs/EXAMPLE-UI.md)，验收用例见 [示例 TC](tests/cases/EXAMPLES.md)。修改基线前阅读 [AGENTS.md](AGENTS.md) 和 [ADR-002](docs/decisions/ADR-002-change-control.md)。Atoms 调研与 Spike 过程记录保存在本机 `D:\AI\ATOM笔试\docs`。

用户新确认的[生成交付物边界与 5 版回滚目标](docs/decisions/ADR-004-generated-deliverable-boundaries.md)目前仅写入文档，尚未迁移代码。下文“当前能力”仍如实描述旧版服务端业务数据方案；不能据此宣称新目标已完成。

跨项目异常收集与独立管理员后台见 [异常设计](docs/EXCEPTION-OBSERVABILITY.md)、[ADR-003](docs/decisions/ADR-003-exception-console.md) 和 [验收用例](tests/cases/EXCEPTIONS.md)。

## 本地运行（Windows PowerShell）

需要 Python 3.11+、Node.js 22+、npm，以及一个可用的模型 API Key。项目根目录 `.env` 设置 `MODEL_API_KEY`；参考 `.env.example`，不要提交 `.env`。

```powershell
cd D:\projects\my-atom-demo
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd web
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe -m backend.serve
```

打开 `http://127.0.0.1:8000`。命令同时启动 `127.0.0.1:8001` 上的独立 origin 本地预览服务。`web/dist` 存在时，FastAPI 提供主前端和 API。前端开发可在 `web` 下另开终端运行 `npm run dev`，Vite 会把 `/api` 转发到本地 API。

## 独立异常后台（本地）

异常后台是另一套服务和前端，不挂载在主应用上。主应用负责向统一数据库写入脱敏异常记录；后台只读同一数据库。先在 `ops/.env` 设置 `OPS_ADMIN_KEY`（随机高熵值）与 `OPS_DB_PATH`（指向主应用 `data/myatom.sqlite3` 的绝对路径），参考 `ops/.env.example`。该密钥只由独立运维服务读取，不放入根目录 `.env` 或浏览器存储。

另开终端执行：

```powershell
cd D:\projects\my-atom-demo
py -3.11 -m venv ops\.venv
.\ops\.venv\Scripts\python.exe -m pip install -r ops\requirements.txt
cd D:\projects\my-atom-demo\ops-web
npm ci
npm run build
cd ..
.\ops\.venv\Scripts\python.exe -m ops.serve
```

打开 `http://127.0.0.1:8002`，输入管理员密钥后查看所有项目的异常。主应用停机时后台仍可查询已有记录，但不会产生新记录。本地两个进程共享同一 SQLite 文件；跨机器上线前须验证统一数据库服务或可靠共享卷、只读权限与正式管理员身份方案。后台默认只绑定本机，不能将当前密钥页面直接作为公网管理员系统。

第一次生成时，Runner 从固定模板执行 `npm ci` 和 `npm run build`，会下载模板依赖。模型调用从服务端读取 `.env` 中的 `MODEL_API_KEY`；默认使用 DeepSeek 兼容接口 `https://api.deepseek.com`、模型 `deepseek-flash`。澄清/计划使用 high 思考，代码输出使用 `.env` 中的 `MODEL_CODE_REASONING_EFFORT=none`，避免生成源码前耗尽输出额度。密钥不会下发给浏览器或生成应用。

## 验证

```powershell
cd D:\projects\my-atom-demo
.\.venv\Scripts\python.exe -m pytest -q
cd web
npm run build
```

需要主动消耗真实模型额度时，在仓库根目录运行 `.\.venv\Scripts\python.exe -m tests.live_smoke`。该脚本走完澄清、计划确认、生成、构建及源码读取，产物放在被 Git 忽略的 `data/live-smoke/`。

三个首页示例分别覆盖番茄钟待办、带皮肤的点击游戏、移动点单。选择示例只填入可编辑需求，点击“创建并开始”才会创建项目并调用模型。移动点单当前生成小程序风格的 Web/H5，支持手机宽度，不是原生微信小程序，也不接真实支付。针对单个示例进行主动付费的生成链路检查：

```powershell
.\.venv\Scripts\python.exe -m tests.live_examples_smoke --id pomodoro_todo
.\.venv\Scripts\python.exe -m tests.live_examples_smoke --id elder_clicker
.\.venv\Scripts\python.exe -m tests.live_examples_smoke --id mobile_ordering
```

脚本为每次运行创建独立本地项目，检查澄清、计划、构建、预览入口和受控数据接口；浏览器内的计时、点击和下单仍按 [示例 TC](tests/cases/EXAMPLES.md) 逐项验收。

## 当前能力与边界

- 项目、运行、决策、事件、模型用量、版本和 LangGraph checkpoint 保存在本地 SQLite；生成源码和构建产物在 `data/`。同一访客凭证可刷新/重进恢复项目。
- 生成代码只可写 `src/App.tsx` 与 `src/App.css`，且在批准计划后才能写入。构建命令的成功状态来自实际退出码。失败最多自动修复两轮。
- SSE 事件按游标回放。预览用短期票据打开已构建的真实应用，生成应用通过模板 SDK 对计划中的实体做受控 CRUD；业务数据在独立 SQLite 文件中，刷新后可读回。
- V3 桌面壳包含项目中心、工作台、概览、文档、测试、发布六页。项目内四个状态页有可直达和刷新恢复的独立 URL；同项目切页保留对话，跨项目切换会先清除旧项目内容。颜色、排版、间距等变量见 `web/src/design-tokens.css`，源值为 `design/v3/tokens.json`。
- 桌面工作台的两条竖向分隔线可拖动，也可用方向键微调；布局宽度保存在当前浏览器的 localStorage。双击分隔线或点击侧栏“恢复默认布局”即可重置。
- 本地 Runner 与宿主共享环境，双端口只提供浏览器 origin 隔离，不构成代码执行沙箱。仅供本机可信开发测试，不可把当前配置直接公开部署。公开访问需先完成隔离 Runner、预览网关和部署验收。
- 本仓库的 Git 远端地址为 [KevinChen073/my-atom-demo](https://github.com/KevinChen073/my-atom-demo.git)。当前文件由本地工作区管理，提交、推送和发布需另行授权。
