# MYATOM：以 GitHub 为代码源的部署与 Atoms 迁移方案

状态：**GitHub → Azure 主路径已于 2026-11-01 确认，实施未完成**。决定见 [ADR-014](decisions/ADR-014-atoms-deployment-and-model-credentials.md)；本方案的迁移与验证步骤仍需实测。这里的“发布”指 MYATOM 主应用供评审访问；生成应用的项目版本与预览是 MYATOM 自己管理的另一层，不等于 Atoms 的 Publish。

## 1. 目标、依据与当前结论

目标是让评审从**公开 URL** 真实完成：创建项目 → 澄清与确认计划 → 模型生成代码 → 构建/检查 → 隔离预览中操作 → 刷新恢复项目和生成应用数据。MYATOM 的 React + TypeScript + Vite 前端、Python + LangGraph 单 Agent、服务端项目/检查点持久化、独立异常后台和不可信生成代码隔离，仍按现行基线执行；不能为了取得一个发布 URL 将这些验收点改成截图或模拟状态。

“使用 GitHub 部署”有两种含义：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)只能托管静态网页，[官方说明](https://docs.github.com/en/pages/getting-started-with-github-pages/creating-a-github-pages-site)明确不运行 Python 服务，因而只能放前端，无法单独部署本项目；另一种是 **GitHub 仓库作为代码源，由支持 Python 的外部平台运行应用**，可用 [GitHub Actions](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms)自动构建/部署。后者无需按 Atoms 的项目结构重建，是当前更省改动的方向。GitHub 自身不是 Python 主服务、数据库或隔离 Runner。

用户提供的当前 Atoms 平台答复表明：不能直接克隆已有 GitHub 仓库并按原技术栈部署；可在 Atoms 内按 React + shadcn/ui + Vite、内置 FastAPI 路由、PostgreSQL、对象存储等能力重建后 Publish。将它作为**迁移约束**，不推断本仓库能原样运行。官方 [GitHub 连接说明](https://help.atoms.dev/en/articles/12129569-connect-github)进一步明确：连接器创建个人账户下的**新私人仓库**，Push/Pull 不是自动同步，冲突文件会被一方覆盖；它不是“连接已有仓库并部署”。[文件与上传说明](https://help.atoms.dev/en/articles/12129559-code-and-files)、[上传限制](https://help.atoms.dev/en/articles/12129597-file-types-and-limits)也不保证上传文件夹后能按原项目构建运行。

现有 Atoms Spike 记录（本机 `D:\AI\ATOM笔试\docs\ATOMS-SPIKES.md`，仅过程证据）显示：S0 通过；S1–S8 尚未全部通过。S2–S5 在开发环境有部分 Python/数据库/AI/SSE 证据，但 GitHub/文件导入、可信 Runner 隔离和公开发布仍是阻断点。**平台回答与一次开发环境实验的证据层级不同**：实验不能证明可原样部署或生产可用；平台答复也不抹去已观察到的有限 Python 路由能力。目标账户、权限、套餐和生产环境需重新验收。

### 部署路径决策

| 路径 | 内容 | 当前判断 |
| --- | --- | --- |
| A：Atoms 全部重建 | 把主前端、API、LangGraph、平台数据库、产物存储及 Runner/预览均迁入 Atoms | **暂不能承诺**。只有 Python 路由的部分证据，没有可信生成代码隔离和公开端到端证据；即使页面能 Publish，也不能按现行 PRD 交付。 |
| B：Atoms 前台 + 外部执行服务 | Atoms 负责主 Web、可验证的内置 API/数据库；生成代码的构建、隔离预览在外部受控 Runner；独立异常后台在单独服务 | **条件候选**。要验证跨域、身份、回调、长任务、稳定预览 origin、数据库访问与平台 Publish。涉及多处适配，不能当作“轻松复制仓库”。 |
| C：GitHub 源 → Azure 全栈托管 | 现有 GitHub 仓库为代码源；Azure 承载主服务、持久数据库、隔离 Runner/预览及独立运维服务 | **已选定的交付主路径**。保留现行代码结构，仍需完成下文的生产适配；不能把当前本地版本直接公开。 |
| D：GitHub Pages + 外部 API | Pages 只托管 `web/dist`，Python API、数据库、Runner/预览和运维后台仍在外部 | 可行但比 C 多跨域、前后端地址和身份配置；本项目没有明显简化收益。 |

**C 已由用户选定**，Atoms 的 A/B 路线只保留为有条件迁移研究，不阻断公开交付。C 仍需通过本方案 §6 的安全和真实交互验收；当前本地版本不能直接公开。若将来改为“只用 Atoms”且平台无法提供可信 Runner，须按 ADR-002 重新确认范围。

### C 路径的托管候选：Azure 与 Vercel

| 候选 | 对本项目的便利之处 | 对本项目的额外工作 | 判断 |
| --- | --- | --- | --- |
| Vercel | GitHub 接入与 React/Vite 静态前端发布直接；[Python Runtime](https://vercel.com/docs/functions/runtimes/python)也能运行 FastAPI，[2026 年更新](https://vercel.com/changelog/vercel-functions-can-now-run-up-to-30-minutes)允许部分套餐的 Python Function 配置更长运行时间 | [Function 文件系统](https://vercel.com/docs/functions/runtimes)为只读部署包与有限 `/tmp` 临时空间；现有 SQLite、产物目录、后台工作与隔离 Runner/稳定预览域均需外置并重新编排。较长请求时限不等于持久 Agent/Runner 服务 | 适合只交付静态前端；完整 MYATOM 会引入更多拆分 |
| Azure App Service | [官方 Python 部署说明](https://learn.microsoft.com/en-us/azure/app-service/containers/how-to-configure-python)支持从 GitHub 源运行 Python Web 服务，适合先把主 FastAPI API 上线 | 本机 SQLite、产物、生成代码隔离和独立异常后台仍需生产化；单个 App Service 不能自动解决可信 Runner | 可作为主 API 的简化起步，但不是全部系统 |
| Azure Container Apps | [容器应用](https://learn.microsoft.com/en-us/azure/container-apps/overview)可承载 HTTP 服务与后台处理，[Jobs](https://learn.microsoft.com/en-us/azure/container-apps/jobs)适合有限时任务；主 API、独立异常后台和执行单元可分开部署 | 需容器化、持久数据库/对象存储、HTTPS 预览域与可信 Runner 安全设计；Job 容器本身不自动证明生成代码隔离 | **当前推荐的完整部署候选**，在保留 Python/LangGraph 主结构上比 Vercel 少做架构拆分 |

推荐的候选拓扑是 `GitHub → 构建/部署 → Azure Container Apps 主 API + 独立异常后台 + 受控执行单元`，配持久数据库和对象存储；生成代码的 Runner 需单独验证权限、网络与资源隔离。这里是技术选型建议，不代表已经创建 Azure 资源、取得公开域名或通过生产验收。若只需要静态设计展示，Vercel 更快，但达不到现行 PRD 的真实生成闭环。

从 Azure 账户、官方样例到 MYATOM GitHub 自动部署的操作步骤见 [Azure Container Apps 快速操作指南](AZURE-CONTAINER-APPS-QUICKSTART.md)。

### ChatGPT Sites 能承担哪一部分

2026-11-01 核对本机已安装的 Sites 插件说明（`sites/1.1.2/skills/sites/SKILL.md` 及 `references/storage.md`、`references/identity-and-secrets.md`）：Sites 可发布静态网页或带服务端逻辑的网站；托管服务端代码在 Cloudflare Workers 中运行，每个 isolate 128 MB，仅支持 HTTP 型外部连接、没有原始 TCP；可绑定 D1 结构化数据、R2 文件存储、ChatGPT 登录和运行时密钥。现有仓库也没有 Sites 的 `.openai/hosting.json`，不能把当前 Python 项目视为已就绪的 Sites 项目。

| MYATOM 要求 | Sites 单独承载 | 判断 |
| --- | --- | --- |
| React 工作台、公开访问链接、轻量 API、项目数据/文件 | 可重建或迁移为 Sites 支持的前端/Worker + D1/R2；需实测真实交互与数据恢复 | **可作为界面与轻量数据层**，并非现有仓库原样部署 |
| 现有 Python + LangGraph、长期执行与 checkpoint | Sites 的托管运行时是 Worker，不运行现有 Python 服务；若改写为 Worker 工作流会改变已接受的技术基线 | **单独不满足**；保留 Python 时须接外部服务 |
| `npm ci`/构建用户生成代码、可信隔离 Runner、每项目稳定独立预览 origin | 插件未提供运行任意子进程或安全执行用户生成代码的托管能力；D1/R2 不能替代 Runner | **单独不满足**；需外部隔离执行和预览服务 |
| DeepSeek/OpenAI 兼容 API Key | Sites 支持运行时密钥和 Worker 到外部 HTTP API；界面录入 Key 仍须后端处理，不能写浏览器持久存储 | **模型请求层有条件可行**，但不解决完整 Agent 执行 |

因此，**Sites 单独不能完成现行 PRD 的真实生成闭环**。可选的组合是 `Sites 前台 → Azure Python/LangGraph API + 数据库 + 隔离 Runner/预览`；这会增加前后端身份、跨域和两套部署流程。若目标是最大限度复用现有 GitHub 仓库，仍优先评估同一外部平台托管主前端和主 API，Sites 只在需要独立展示页或明确接受混合架构时使用。此处仅为能力评估，没有创建或发布 Site。

## 2. GitHub 源 → 外部全栈托管：最小改动范围

推荐将现有仓库作为唯一代码源，连接一个能运行 Python Web 服务的外部托管平台；主 Python API 可以继续提供构建后的 `web/dist`，减少单独部署前端和跨域配置。GitHub Actions 可作为构建/测试/部署触发器，但它的临时 runner 不是长期运行的 Agent 服务或预览沙箱。

| 当前本地实现 | 生产需要的改动 | 原因 |
| --- | --- | --- |
| `backend/serve.py` 与 `backend/preview.py` 只允许 `APP_ENV=local`，预览绑定 `127.0.0.1` 和 `.localhost` 子域；本地跨站 iframe 用票据兑换会话路径 | 单独实现生产 `PreviewGateway`、HTTPS 下的稳定项目子域、受控会话机制与隔离 Runner；保留本地入口 | 当前本地预览不能靠改端口或环境变量就公开，本地路径令牌不可直接视为公网安全方案 |
| `backend/store.py`、`backend/workflow.py`、`backend/preview_access.py` 与 `ops/store.py` 使用本机 SQLite 文件 | 接入持久数据库或经证明可靠的共享存储；迁移 schema、checkpoint、事件和运维只读权限 | 托管实例重启/扩容时不能丢状态，独立异常后台必须读同一权威库 |
| `backend/runner.py` 在本机目录运行构建；产物在 `data/` | 隔离生成代码的执行环境；产物迁至持久对象存储/卷，保留 hash、版本指针与清理规则 | 生成代码不可信，托管服务的临时文件系统不能作为交付物持久存储 |
| `.env` 与本地监听地址 | 在托管平台配置服务端密钥、数据库、模型及域名；公开前验证 HTTPS、限流、预算与项目权限 | 不能把本地 `.env` 推到 GitHub 或把浏览器输入的 Key 写入源码 |

最小发布顺序：①锁定待部署提交并核对未提交工作；②准备独立测试环境与脱敏数据；③接入持久数据库和产物存储；④完成隔离 Runner/预览域；⑤构建 `web`、启动主服务及独立异常服务；⑥在测试域跑现行端到端与安全用例；⑦取得公开域名后再跑一次。实际主机、数据库和域名选择待部署评估，不在本文假定“GitHub 一键上线”。

## 3. GitHub → Atoms 的可重复迁移步骤

1. **确定源头**：记录现有仓库 URL、分支、提交号、依赖锁文件和本地未提交改动；本地仓库保持权威源。迁移在单独分支或副本上整理，不覆盖当前工作树。现有工作树有未提交工作，不能把 `git push` 当备份。
2. **做可共享迁移包**：列出前端、Python 主服务、LangGraph/checkpoint、Runner/Preview、独立运维服务、模板及资源的文件清单与差异表；排除 `.env`、`data/`、数据库、日志、密钥、测试产生的个人数据和 `.git`。只分享 `.env.example` 的字段名与说明。对迁移包记录 hash/版本，避免“上传成功”被误认作源码一致。
3. **在 Atoms 建隔离项目**：用最小合成数据项目先验证。若走 `+Add`，分批上传可共享文件并逐项核对 Atoms Editor 的源码、锁文件和构建结果；遇编辑/上传套餐门槛，停止该路线并记为阻断。GitHub Connector 若使用，只让 Atoms 创建新私人仓库；不要在未知冲突状态对原仓库 Push/Pull。
4. **先迁架构适配，后迁业务**：React 页面按 V7 视觉原型对照现有真实状态；把 Python API 路由、LangGraph 恢复、平台记录、产物存储、模型网关、Runner/Preview 分别映射。每个模块必须有“保留原样 / 改写 / 外部服务 / 暂不可用”的记录。不能把 Atoms 自带 AI、DB、App Storage 自动等同于 MYATOM 的模型网关、checkpointer 或安全沙箱。
5. **在预览环境验收**：检查主流程、重启后的 checkpoint 恢复、SSE/轮询回放、项目权限、生成代码与主密钥/其他项目隔离、生成应用业务数据同项目稳定 origin 刷新读回。保留环境、版本、输入、实际结果与截图/脱敏日志。
6. **形成发布候选**：检查密钥的 Test/Production 配置、数据库迁移选项、独立异常后台可用性、费用/调用上限和公开访问控制。只有安全、功能和真实数据路径都通过，才能将 Atoms 的 Publish 作为最终动作。发布需单独明确授权；发布后在公开 URL 复跑端到端，并记录版本、访问地址和结果。[Atoms Publish 说明](https://help.atoms.dev/en/articles/12129577-publish-your-project)明确 App Viewer 与公开站点是不同状态。

## 4. 配置与模型接入：前端选择，后端执行

### 用户可见的设置界面

在主工作台的“模型设置”提供一个聚焦表单：供应商/协议、模型、服务地址、API Key、连接测试、保存方式与当前状态。默认显示 **DeepSeek（推荐）**；另有 **OpenAI 兼容 API**，包括符合该调用格式的第三方服务。两项共用 OpenAI 风格协议适配层；无需 Anthropic Messages 专用适配器。首次配置成功后只展示供应商、模型和密钥状态（如“已配置，尾号不可显示”），绝不回显 Key。改变供应商时提示当前运行不受影响、下一次运行才使用新配置；运行中锁定所用配置的非敏感快照，避免中途切换影响重试/恢复。

| 字段 | 默认/录入 | 存放与权限 |
| --- | --- | --- |
| `provider` / `protocol` | DeepSeek 与 OpenAI 兼容两类；均走 OpenAI 风格协议 | 可在 UI 选择；服务端对每个 run 固定并校验 |
| `model_id` | DeepSeek 默认 `deepseek-flash`；其他由用户填写受支持的模型 ID | 可在 UI 选择/填写；变更影响计费和输出，显示预算并受服务端额度限制。模型名随官方目录变化，发布前再确认 |
| `base_url` | DeepSeek 默认 `https://api.deepseek.com`；其他使用供应商官方地址或管理员核准的 HTTPS 地址 | 不允许匿名访客任填任意 URL 后让服务端请求；限制协议、域名、重定向和私网地址，避免 SSRF。自定义兼容网关只对管理员开放 |
| `reasoning_effort`、超时、模型调用/token/时间上限 | 按模型能力显示；可保留现有默认值 | 普通访客只可在服务端上限内选；管理员设硬上限。某些兼容服务不接受 `thinking`、`reasoning_effort` 或 JSON mode，按适配器能力发参 |
| `MODEL_API_KEY` 或用户自带 Key | 密码输入框，支持粘贴/替换/清除 | **秘密**。只经 HTTPS 发给后端；不写进前端 bundle、URL、聊天、生成代码、localStorage/sessionStorage、日志、SSE、checkpoint、项目快照或异常库 |
| `APP_ENV`、`MYATOM_DATA_DIR`、`PREVIEW_PORT`、`WORKBENCH_ORIGIN`、数据库连接、对象存储绑定 | 由部署环境确定 | 服务端/平台运行配置；不是访客可编辑的模型设置。生产域名、隔离 origin 与持久数据库必须部署时校验 |
| `OPS_DB_PATH` / `OPS_ADMIN_KEY` | 独立异常后台配置 | 独立运维服务配置；管理员密钥是秘密，不能并入主应用设置或让访客填写 |

**Key 录入不是“安全地放到前端”。**输入框中的值会短暂存在浏览器内存，并可能被该页面的恶意脚本读取；需要 CSP、依赖审查、HTTPS、`Cache-Control: no-store` 和严禁第三方埋点采集。浏览器不直接调用模型厂商。后端只接受有权用户提交的 Key，创建或查找凭证引用，再由 `ModelGateway` 发出模型请求；服务端返回配置状态，不返回 Key。公开访客使用平台自有 Key 时还必须有身份/速率/费用上限，避免任意访客消耗额度。用户自带 Key 模式则要清楚标示由该 Key 所属账户承担费用。

**首版 Key 行为**：按本次用户要求提供“输入自己的 API Key”入口；默认只在当前页面内存和当前服务端执行上下文临时使用，不跨刷新保存。服务重启、等待确认或恢复时需要重新录入并继续；界面必须先说明这一点。项目所有者也可在 [Atoms Keys](https://help.atoms.dev/en/articles/12129564-keys-and-secrets) 配置平台运营 Key，分开 Test/Production，作为不要求访客自备 Key 的受限演示模式。若以后要让用户自带 Key 跨刷新/中断自动恢复，后端必须在身份隔离后用服务端主密钥加密存储，数据库只存密文和凭证 ID，主密钥在 Atoms Keys/托管密钥中，支持替换、撤销、过期和审计。**尚未验证 Atoms 内置 API 能否安全完成此流程**；通过前不承诺 Key 持久化或无人值守恢复。不得把明文写入 PostgreSQL、对象存储或浏览器存储。

### 两类模型接入的实现边界

- **DeepSeek（默认）**：使用其官方 OpenAI 兼容 endpoint 和当前模型 ID；默认值与参数在部署时再次核对 [DeepSeek API 文档](https://api-docs.deepseek.com/quick_start/agent_integrations/)。
- **OpenAI 兼容**：由后端 OpenAI 风格适配器处理鉴权、结构化输出、错误、用量与超时；“兼容”不代表全部支持 `response_format`、`reasoning_effort`、工具或流式协议，连接测试与一次结构化 JSON 测试均需通过。类 Claude 服务只有在**自身确实提供 OpenAI 兼容接口**时才可作为此类接入；不支持 Anthropic 原生 Messages API。

当前代码的 `backend/settings.py` 只读取 `MODEL_API_KEY`、`MODEL_NAME`、`MODEL_BASE_URL` 等，`.env.example` 虽有 `MODEL_PROVIDER` 但代码未读取；`backend/model.py` 已使用 OpenAI SDK，却固定发送 DeepSeek 风格 `thinking`。因此两类切换和 UI Key 录入仍是**拟开发功能**，不是已有能力。最小修改是让 `ModelGateway` 按所选 provider 选择 base URL、模型、Key 和参数；DeepSeek 保留其专属 `thinking`，OpenAI 兼容服务只发送能力探测通过的通用参数，必要时降级为提示词约束 JSON 并严格校验输出。统一错误码、token/费用估算与取消语义；用无真实 Key 的假服务测试，真实厂商连通测试再用用户授权的测试 Key 执行。

## 5. Atoms 对应关系与不能偷换的边界

| MYATOM 部分 | Atoms 候选映射 | 上线前必须拿到的证据 |
| --- | --- | --- |
| 主 React 工作台 | Atoms React + Vite 项目，迁移 V7 的视觉规则与真实状态 | 源码/锁文件一致、构建、桌面真实用户旅程 |
| Python API + LangGraph | 平台内置 FastAPI 路由；若不能持久运行，移至外部服务 | 依赖、路由、`interrupt/resume`、重启恢复、长任务、鉴权与生产流量 |
| 项目/事件/checkpoint | 平台 PostgreSQL 或外部受管数据库 | 事务、迁移、读写权限、独立异常后台只读访问、开发/生产隔离 |
| 源码/构建产物 | 对象存储或外部产物存储 | 原子版本指针、最多 5 版、下载/回滚、权限和清理 |
| Runner + Preview | 独立可信隔离执行服务与每项目稳定独立 origin | 不可信生成代码不能读主密钥或其他项目数据；资源/网络限制、清理、浏览器内真实交互；Atoms App Viewer 本身不构成此证明 |
| 模型配置/凭证 | 后端 OpenAI 风格适配器 + Keys/加密凭证仓 | DeepSeek 与 OpenAI 兼容请求、脱敏、额度、重启恢复和生产 Key 验证 |
| 独立异常后台 | 单独服务与只读统一数据库访问 | 与主应用分离、管理员身份、跨项目只读查询；不能把主应用 `/ops` 页面当作替代 |

## 6. 决策闸门、验收与待确认事项

| 闸门 | Pass 条件 | 未通过时 |
| --- | --- | --- |
| G1 导入 | 现有仓库的可共享迁移包在 Atoms 中源码/锁文件核对一致，并真实构建 | 保持本地 Git 为权威源；走外部部署或修正迁移方式 |
| G2 后端 | 平台 API 中 Python/LangGraph 的请求、确认中断、重启恢复、数据库事务和模型协议调用在生产候选成立 | 主服务外置；若跨域/身份不通则整站外置 |
| G3 隔离 | 生成源码构建和预览在独立 Runner/origin 中可验证隔离、清理和限制，`TC-SEC-01` 通过 | 不公开运行任意生成代码；现行 PRD 不算完成 |
| G4 公开发布 | 公开 URL 中跑通 `TC-E2E-01`、项目恢复、模型权限/费用控制、独立异常后台读回，记录版本和证据 | Atoms 预览或候选域名不能作为交付链接；改走外部部署 |

部署前还要复查：开发/生产 Key 分离、密钥从未进入源码/构建产物；各项目不可互读；请求限流和每 run 硬预算；生成应用稳定 origin；数据库备份和迁移；发布后实际访问与更新回归。将结果按 **Pass / Fail / Blocked / 未执行** 记录到过程文档，不能靠按钮、截图或一次 HTTP 200 宣称整个闸门通过。

### 已确认路线与后续设计边界

1. **平台边界**：若决定 Atoms 全部重建且无法提供可信 Runner，将与 [PRD §1、§6](PRD.md) 和 [架构 §7、§10](ARCHITECTURE.md) 的真实生成/隔离/在线验收冲突。推荐保留现行验收，必要时使用外部 Runner 或整站外部部署。
2. **凭证模式**：现行 [架构 §2](ARCHITECTURE.md) 以服务端 `SecretProvider` 读密钥，不提供访客在 UI 添加 Key。本次用户已提出该入口，因此方案纳入用户自带 Key；首版按 §4 采用临时 Key、需要时重新录入，跨请求/重启的安全传递必须通过 Spike。若要自动恢复，另补身份、加密存储、撤销及费用归属设计。正式实施时同步 PRD/架构/TC，不把前端持久化作为捷径。
3. **UI 与后端适配**：现行模型实现是 DeepSeek 风格 OpenAI SDK。本次用户将范围收束为 DeepSeek 与 OpenAI 兼容 API，故无需 Anthropic Messages 适配器；但仍需 provider 参数分流、兼容性测试及错误语义，不能仅修改 `.env` 或前端选项。

**已确认的决定**：保持现行 PRD 的真实闭环，以 GitHub 为代码源走 Azure 全栈托管，Atoms 为可选迁移。模型范围与 Key 录入按 [ADR-014](decisions/ADR-014-atoms-deployment-and-model-credentials.md) 设计；凭证跨请求、重启恢复和隔离方式仍需实现与验证。实际发布以 [Azure 部署验收 TC](../tests/cases/DEPLOYMENT-AZURE.md) 为闸门。
