# 模型设置与单数据库版本存储

关联：[PRD](../../docs/PRD.md)、[架构](../../docs/ARCHITECTURE.md)、[ADR-024](../../docs/decisions/ADR-024-sqlite-local-artifacts.md)、[ADR-028](../../docs/decisions/ADR-028-browser-model-key-both-environments.md)。

| 用例 | 步骤 | 预期 | 本轮证据 |
| --- | --- | --- | --- |
| TC-MODEL-01 默认值无 Key | 本机设置 `MODEL_API_KEY`，从本机及非本机请求默认值接口，并打开模型设置；Azure 同样核对 | 两端接口的 Key 均为空；无用户自存 Key 时输入框为空；有用户自存 Key 时仍恢复该用户配置 | 本地接口与无凭证 run 定向自动测试；Azure 待实测 |
| TC-MODEL-02 用户 Key | 输入 Key、测试连接、保存、刷新，发起任务；检查平台 SQLite/SQL、checkpoint、异常记录与页面源码 | 本地与 Azure 均仅在点击保存后写入 `myatom.model-config.v1`；刷新恢复，清除后刷新不恢复；运行使用用户 Key；服务端只保留非密钥配置标记；数据库及日志无 Key | 两种 hostname 的存储单测通过；本地 `localhost:8000` 及 Azure 新修订 `0000010` 均以虚构 Key 完成保存、刷新读回、清除、再刷新确认缺失；后端 SQLite 非落库测试通过。真实模型连接/调用与 Azure SQL、checkpoint、异常记录、日志的在线密钥审计未执行。 |
| TC-MODEL-03 重启恢复 | 任务处理中重启 API，保留浏览器存储后刷新；再清除 Key 重试 | 有 Key 时重新注册并继续；无 Key 时明确提示重新填写，不自动改用运营者 Key | 待执行 |
| TC-MODEL-04 入口合并 | 打开首页和项目页的模型设置；切换“自己的 API Key”与“测试邀请码”；未验证时输入邀请码，用按钮与 Enter 分别提交；已验证后切回自己的 Key，最后退出身份 | 顶部只有一个模型入口；邀请码在同一弹窗验证；个人 Key 与测试模型选择互不覆盖；无独立身份/额度按钮；邀请码不写入浏览器存储 | 本地项目页已核对单一入口、两种方式切换、短码启用按钮；真实邀请码提交、退出及线上尚未执行 |
| TC-STORAGE-01 本地快照 | 提交成功版本，删除工作区与旧 `data/artifacts/`，重启并预览、读源码、回滚、迭代 | SQLite 独立保存完整版本，指针和文件一致 | 自动化源码/预览重启测试通过；回滚/迭代 UI 待冒烟 |
| TC-STORAGE-02 原子性 | 制造缺文件、错误 hash、数据库写入失败，再读当前版本 | 新版不入库，旧版与指针保持可用 | 缺文件测试通过；数据库故障注入待执行 |
| TC-STORAGE-03 Azure SQL | 对专用库按 v1/v2 迁移；创建版本后换容器副本、清空容器数据目录并预览、回滚 | Azure SQL 单一权威源，schema=2，版本可恢复 | 未实测；见 [Azure 部署 TC](DEPLOYMENT-AZURE.md) |

v1 SQL 的 `CHECKPOINT` 列须写成 `[checkpoint]`；若旧脚本执行中途失败，在专用库核对版本标记后重跑修正版 v1，不要直接清空或继续 v2。
