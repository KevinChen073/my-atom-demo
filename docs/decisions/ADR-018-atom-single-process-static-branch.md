# ADR-018：`atom-deploy` 单进程静态交付分支

- 状态：Accepted for branch（用户 2026-11-01 明确提出 Atoms 能力限制与解决方式）；不替代其他分支的 [ADR-014](ADR-014-atoms-deployment-and-model-credentials.md)。
- 范围：仅 `atom-deploy` 分支，运行模式 `APP_ENV=atom`。

## 背景与冲突

既有 [PRD](../PRD.md) 和 [架构](../ARCHITECTURE.md) 以 React + TypeScript + Vite 生成应用、Node 构建、独立预览网关及独立异常后台为基线，主路线为 GitHub → Azure。用户确认 Atoms 目标后端是类沙箱工具，仅有一个 Python 进程，不能启动其他进程或配置 Node 完整构建。

## 决定

1. Atoms 分支保留 Python + LangGraph 单主 Agent；一个前台 Python/ASGI 进程承载工作台 API、已打包前端、只读异常查询与可选的项目预览 host 分发。线程用于同进程异步工作，不启动子进程。
2. Atoms 分支生成应用改用固定四文件模板：`index.html`、`style.css`、`app.js`、`readme.md`。直接复制前三者为静态产物，仅进行受限源码、入口和资源检查，不运行 Node、编译器或浏览器检查。生成应用不拥有后端进程。
3. 工作台和异常界面的 React 构建产物在开发机制作并随部署包提供；Atoms 运行时只读取 `atom-static/`，不安装或运行 Node。异常界面复用工作台的 Token 会话，异常查询只读同一 SQLite 数据库。
4. `ATOM_ACCESS_TOKEN` 是整个工作台的高熵访问 Token，登录后使用有时限、HttpOnly、SameSite=Strict 的签名 Cookie。访客项目身份 Cookie 仍用于项目数据区分。Token 不进入前端包或生成产物。
5. 生成脚本只在每项目独立 HTTPS origin 上预览。若平台未提供可保持外部 Host 的通配子域、证书和同进程分发，预览 API 返回 503，工作台仅可查看静态源码；不能用同域 iframe 冒充隔离预览。

## 已知代价与验收

无 TypeScript 编译、依赖安装、完整 JS 语法解析或浏览器交互测试；静态检查通过只证明入口和文件可读。平台数据目录持久性、通配域名、模型兼容性与公网访问均须按 [Atoms 部署 TC](../../tests/cases/DEPLOYMENT-ATOM.md) 实测。未通过前不能把该分支称为已上线或满足原 PRD 的完整 MVP2 交付门槛。
