# MYATOM · MVP2 本地开发版

一个本地可运行的 Atoms 类应用生成工作台。用户创建项目、确认需求澄清和 Build Plan 后，单 Agent 在固定的 React + TypeScript + Vite 模板中生成代码，实际执行类型检查与构建，并保存可恢复的项目版本。

产品范围见 [PRD](docs/PRD.md)，架构见 [系统设计](docs/ARCHITECTURE.md)，本轮交互决定见 [ADR-010](docs/decisions/ADR-010-structured-card-single-send.md)，验收见 [单一发送 TC](tests/cases/SINGLE-SEND.md)。工作台视觉以 [V7 设计入口](design/design.md) 为准。首页示例由 [目录](examples/catalog.json) 定义，交互见 [示例 UI](docs/EXAMPLE-UI.md)，验收用例见 [示例 TC](tests/cases/EXAMPLES.md)。修改基线前阅读 [AGENTS.md](AGENTS.md) 和 [ADR-002](docs/decisions/ADR-002-change-control.md)。Atoms 调研与 Spike 过程记录保存在本机 `D:\AI\ATOM笔试\docs`。

生成应用的本地持久化与最多 5 个可用快照遵循 [ADR-004](docs/decisions/ADR-004-generated-deliverable-boundaries.md)。构建失败的自动修复和人工恢复遵循 [ADR-008](docs/decisions/ADR-008-manual-build-recovery.md) 与 [ADR-009](docs/decisions/ADR-009-build-repair-harness.md)。

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

脚本为每次运行创建独立本地项目，检查澄清、计划、构建、预览入口及生成代码的本地存储调用；浏览器内的计时、点击、下单与刷新恢复仍按 [示例 TC](tests/cases/EXAMPLES.md) 逐项验收。

## 当前能力与边界

- 本地默认用 SQLite 保存项目、运行、决策、事件、版本和 LangGraph checkpoint；设置服务端 `MYATOM_DATABASE_URL` 后可在本地开发模式改用 PostgreSQL，先显式运行 `python -m backend.migrate_postgres` 升级到 v2。两种模式共用工作流代码，生成源码和构建产物仍在本地 `data/`；Azure 正式环境的 Blob、隔离 Runner 与预览尚未接通。数据库实施边界见 [Azure 持久化](docs/AZURE-PERSISTENCE.md)。同一访客凭证可刷新/重进恢复项目。
- 已有可用版本时，新需求自动从当前版本继承完整计划与源码快照；计划卡列出沿用、增加、调整或删除的功能，确认后优先修改指定文件。失败不会替换旧版。具体规则见 [ADR-019](docs/decisions/ADR-019-version-inheritance.md)。
- 生成代码限固定 React+TS+Vite 模板：`src/App.tsx`、`src/app.css`、`src/hooks/useAppState.ts` 与根目录 `readme.md` 必需；额外组件在 `src/components/`、额外逻辑在 `src/hooks/`，最多 12 个生成文件。只有编译/类型等源码错误才自动修复，最多 60 轮；同错连续无进展或累计第 5 次出现会提前停止。
- SSE 事件按游标回放。预览用短期票据打开已构建的真实应用，每项目使用稳定的独立 `.localhost` origin；生成应用的业务数据只在该预览域 `localStorage`。候选产物经构建及静态资源检查后才成为可用快照。每项目最多保留 5 版，回滚只持久切换当前版本指针；浏览器业务数据不随代码回滚。
- V7 桌面壳包含新建项目首页、工作台、概览、文档、测试、发布六个 URL 视图。项目内四个状态页可直达并刷新恢复；同项目切页保留对话，跨项目切换先清除旧项目内容。当前视觉规则见 `design/design.md`、`design/token.json` 和 `web/src/v7.css`。
- 桌面工作台的两条竖向分隔线可拖动，也可用方向键微调；布局宽度保存在当前浏览器的 localStorage。双击分隔线或点击侧栏“恢复默认布局”即可重置。
- 本地 Runner 与宿主共享环境，双端口只提供浏览器 origin 隔离，不构成代码执行沙箱。仅供本机可信开发测试，不可把当前配置直接公开部署。公开访问需先完成隔离 Runner、预览网关和部署验收。
- 本仓库的 Git 远端地址为 [KevinChen073/my-atom-demo](https://github.com/KevinChen073/my-atom-demo.git)。当前文件由本地工作区管理，提交、推送和发布需另行授权。
