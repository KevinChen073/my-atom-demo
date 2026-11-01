# `atom-deploy` 部署说明

本分支根据 [ADR-018](decisions/ADR-018-atom-single-process-static-branch.md) 适配只有一个 Python 进程、无 Node 构建进程的 Atoms 环境。代码与离线静态包已备好；平台能力和真实公网闭环仍需按 [部署 TC](../tests/cases/DEPLOYMENT-ATOM.md) 验证。

## 部署包与入口

- 唯一启动命令：`python -m backend.atom_serve`。`HOST` 默认 `0.0.0.0`，`PORT` 默认 `8000`；不再启动 `backend.serve`、`ops.serve` 或 Node。
- 工作台和异常界面分别由 `atom-static/web/`、`atom-static/ops-web/` 直接提供。构建文件已随本分支保存。开发机修改 React 源码后，分别运行 `web` 与 `ops-web` 的 `npm run build:atom`，更新部署包；Atoms 环境不运行这些命令。
- 安装 Python 依赖：`pip install -r requirements.txt`。实际平台是否允许这些 Python 包及其依赖，需要现场验证。

## 环境变量

| 名称 | 要求 |
| --- | --- |
| `APP_ENV` | 必填 `atom`。 |
| `ATOM_ACCESS_TOKEN` | 必填至少 32 字符的随机值，在平台私密配置中设置。所有工作台和异常查询共用此登录。 |
| `MODEL_API_KEY` / `MODEL_NAME` / `MODEL_BASE_URL` | 服务端模型配置；不得放在静态文件或生成应用中。 |
| `WORKBENCH_ORIGIN` | 工作台的外部完整 HTTPS origin，例如 `https://app.example.com`；用于预览嵌入策略。 |
| `MYATOM_DATA_DIR` | SQLite、checkpoint、工作区和产物目录；必须指向经实测可持久保存的目录。 |
| `ATOM_PREVIEW_DOMAIN` | 可选的项目预览通配域后缀，例如 `preview.example.com`。需让 `p-<项目 UUID 去横线>.preview.example.com` 与工作台分属不同 origin，并全部进入同一 Python 入口。未配置时预览关闭。 |
| `ATOM_PREVIEW_SCHEME` | 公开环境用 `https`。 |
| `PORT` / `HOST` | 平台指定的单个监听端口与地址。 |

从浏览器打开工作台 URL，输入访问 Token。`/ops/` 为同进程只读异常界面。`/api/health` 可匿名探测进程存活；其余页面与 API 需要登录。生成应用直接写四个文件，静态检查通过后保存版本；检查等级为 `static_files_only`，不代表真实浏览器可交互。

## 预览与安全边界

启用预览前，须现场证明通配子域 DNS、TLS、外部 Host 头转发以及预览 iframe 可加载。预览静态资源使用短期票据与按版本受限的会话路径；同一项目跨版本共享 origin，不同项目分域。源代码正则检查不是隔离沙箱，未完成这些验证时保持 `ATOM_PREVIEW_DOMAIN` 为空。

若 Atoms 的单域名入口无法提供通配项目域，可交付生成源码与静态文件，但无法满足原 PRD 的跨项目 `localStorage` 隔离和可操作预览。需另选经验证的独立预览托管或明确调整产品验收；不能简单把生成脚本挂在工作台同域。

工作台部署与生成产物都依赖 `MYATOM_DATA_DIR` 的持久性。若平台进程重启后清空该目录，项目、checkpoint 和版本会丢失；部署前必须做重启读回验收。Token 是共享部署入口，不是多用户身份系统；项目所有权仍按访客 Cookie 区分。
