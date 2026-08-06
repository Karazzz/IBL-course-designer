# 部署指南

本文档面向已在腾讯云 ADP 上部署 Claw 模式应用并接入微信客服的技术人员。如果你只是想使用这个 Skill，请参考 [README](../README.md#快速开始)。

---

## 环境要求

- Python 3.10+；无第三方 Python 依赖；
- 本地可在 Windows、macOS 或 Linux 校验、打包和调用 ADP API；
- Nginx 部署脚本面向 Linux，要求 Nginx 1.18+、`python3`、`curl`；
- 线上需要腾讯云/ADP、企业微信、微信客服、已备案域名和 HTTPS 证书。

## 1. 本地校验与测试

```powershell
python scripts/validate_skill.py --source .
python -m unittest discover -s tests -v
```

校验内容包括：

- 包根目录存在且只有一个 `SKILL.md`；
- Frontmatter 是可解析的受限 YAML，且 `name`、`description` 和 SemVer 合规；
- 文件总数不超过 300、大小不超过 10 MB；
- 所有打包文件是 UTF-8 文本；
- 无二进制、嵌套压缩包、重复路径或路径穿越。

## 2. 打包 Skill

```powershell
python scripts/package_skill.py
python scripts/validate_skill.py --zip dist/IBL-course-designer.zip
```

输出固定为 `dist/IBL-course-designer.zip`。打包按路径排序并使用固定时间戳；输入不变时 SHA-256 不变。

只上传 `dist/IBL-course-designer.zip`。根目录原有的 `IBL-course-designer.zip` 是 1.0.0 旧包，Frontmatter 不符合当前 ADP 规范，保留它仅为避免擅自覆盖原始文件，不得上传。

查看 ZIP 内容：

```powershell
python -c "import zipfile; print('\n'.join(zipfile.ZipFile('dist/IBL-course-designer.zip').namelist()))"
```

## 3. 准备配置

Windows PowerShell：

```powershell
Copy-Item .env.example .env
```

Linux/macOS：

```sh
cp .env.example .env
chmod 600 .env
```

填写非敏感资源名称、`ADP_MODEL_ID`、`ADP_SKILL_ID` 和域名路径。开发机可用 `--env-file .env` 载入；生产环境应由 CI/CD 或 Secret Manager 直接注入 `TENCENTCLOUD_SECRET_ID`、`TENCENTCLOUD_SECRET_KEY` 和临时令牌，不把真实 Secret 写入任何仓库文件。

先按 `docs/manual-steps.md` 完成实名认证、ADP 开通、Skill 控制台上传、模型选择、企业微信认证、备案和微信客服账号创建。

## 4. 生成 ADP 变更计划

以下命令完全离线，不访问腾讯云：

```powershell
python scripts/adp_client.py --env-file .env plan
```

计划写入 `.state/adp-plan.json`，显示操作、阻塞项和批准哈希。若 `ADP_MODEL_ID` 或 Skill 上传结果缺失，计划会列出阻塞项，`apply` 会拒绝执行。

## 5. 经批准后创建或复用 ADP 资源

先人工审核计划。以下命令会创建或修改线上资源，本项目不会代为运行。将 `<PLAN_HASH>` 替换为刚审核计划中的哈希：

```powershell
python scripts/adp_client.py --env-file .env apply --approve <PLAN_HASH>
```

客户端按顺序执行：

1. 使用 `ADP_SPACE_ID`，或按精确名称查询并创建空间；
2. 精确查询并复用/创建 `AppMode=4` 的 Claw 应用；
3. 验证 `ADP_MODEL_ID` 在 `ModelScene=18` 可用；
4. 使用 `ADP_SKILL_ID`，或查询/创建 Skill；
5. 复用/创建专管主 Agent，对齐指令、模型、唯一 Skill、空工具/插件和推理轮数；
6. 仅当本次新建或配置发生变化时发布；
7. 创建或复用一个 API 测试会话。

主 Agent 是本项目专管资源：客户端会清空已有工具和插件，并把 Skill 列表收敛为当前指定版本的 `ibl-course-designer`，避免遗留能力越权。若 Skill ID、版本、安全分析状态或 Agent 主角色不符合计划，客户端停止而不是猜测。

幂等策略：创建前查询；精确同名超过一个时停止；优先使用 `.state/adp-state.json` 的资源 ID；修改只发送有差异的字段；不因网络超时或可疑 HTTP 5xx 自动重试创建请求；发布哈希未被确认成功时会对账上次 Release；重复运行且已确认发布时不重复发布。状态文件不保存 AppKey、Secret 或 Skill 文件 URL。审批计划同时绑定管理端点、聊天端点、状态文件路径指纹、调用身份指纹、Agent 指令、Skill 文件 URL 指纹和验收文件指纹，配置变化后旧哈希立即失效。计划时应已注入调用身份；使用轮换的临时凭证时设置稳定的 `ADP_ACCOUNT_FINGERPRINT`，避免只因临时 SecretId 变化而重复审批。

只读检查：

```powershell
python scripts/adp_client.py --env-file .env status
```

若 `CreateRelease` 已送达但响应丢失，客户端会保留"不确定发布"标记并拒绝重复创建。先在 ADP 控制台确认对应 Release ID，再用已批准计划对账并轮询；不要猜测 ID：

```powershell
python scripts/adp_client.py --env-file .env reconcile-release --approve <PLAN_HASH> --release-id <REVIEWED_RELEASE_ID>
```

## 6. API 会话和验收测试

发送一条无个人信息的测试消息：

```powershell
python scripts/adp_client.py --env-file .env test --approve <PLAN_HASH> --message "我想做一个种子主题课程"
```

运行 `config/acceptance-cases.json` 的微信多轮验收：

```powershell
python scripts/adp_client.py --env-file .env acceptance --approve <PLAN_HASH>
```

测试会话按稳定 `UserId` 查询并复用，避免重复创建。ADP 当前不支持 Claw 会话重置；重复验收会沿用历史上下文。如果需要完全隔离的验收，先在控制台批准新的测试用户策略，再修改用例 `user_id` 并重新生成计划。

`--verbose` 只打印经过脱敏的请求和 `RequestId`，仍不建议在含真实教师/学生信息的会话中启用。用法是把全局参数放在子命令前：

```powershell
python scripts/adp_client.py --verbose --env-file .env status
```

## 7. 渲染和检查 Nginx

本地只渲染，不部署：

```powershell
python ops/render_nginx.py --env-file .env --output .state/ibl-course-designer.conf
```

模板提供：

- `/cgi-bin/` 原 URI 转发至 `qyapi.weixin.qq.com`；
- `/online/channel/callback/` 原 URI 转发至 `chan.lke.cloud.tencent.com`；
- 80 到 443 跳转、TLS 1.2/1.3、SNI；
- 域名、服务证书、上游 CA 证书和访问日志路径来自环境变量；
- 对两个腾讯上游启用证书链和主机名验证；
- 安全访问日志只记录 `$uri`，不记录查询串或 Referer；由于 Nginx 错误日志可能包含完整请求查询串，该虚拟主机禁用错误日志。

服务器上先做无变更检查：

```sh
ENV_FILE=/secure/path/ibl.env sh ops/check.sh
ENV_FILE=/secure/path/ibl.env sh ops/check.sh --server
```

脚本默认调用 `python3`；若命令名不同，通过 `PYTHON_BIN` 覆盖，例如 `PYTHON_BIN=python`。

`--server` 会执行 `nginx -t`，但不重载。`--remote` 会访问公网两个代理路径，仅确认收到 HTTP 响应，不携带企业凭证：

```sh
ENV_FILE=/secure/path/ibl.env sh ops/check.sh --remote
```

## 8. 部署、备份和回滚

脚本不使用 SSH 或 `sudo`，应在已经进入且有相应权限的服务器会话中运行。所有变更脚本默认只显示计划和批准哈希。

部署计划：

```sh
ENV_FILE=/secure/path/ibl.env sh ops/deploy.sh
```

审核后应用：

```sh
ENV_FILE=/secure/path/ibl.env sh ops/deploy.sh --apply --approve <DEPLOY_HASH>
```

部署会备份现有配置、安装新配置、执行 `nginx -t`，成功后才 `nginx -s reload`；测试失败会恢复旧配置且不重载。

独立备份：

```sh
sh ops/backup.sh
sh ops/backup.sh --apply --approve <BACKUP_HASH>
```

回滚计划和应用：

```sh
sh ops/rollback.sh
sh ops/rollback.sh --apply --approve <ROLLBACK_HASH>
```

也可以显式选择备份：

```sh
sh ops/rollback.sh --backup /var/backups/ibl-course-designer/ibl-course-designer.conf.TIMESTAMP
```

## 9. 微信客服上线

API 客户端不创建微信渠道，因为公开 ADP API 没有渠道 CRUD 接口。按 `docs/manual-steps.md` 在 ADP 和微信客服后台手工配置企业 ID、Secret、URL、Token、EncodingAESKey，完成扫码和管理员授权，再发布微信客服渠道并扫码验收。

## 安全边界

- 不提交 `.env`、`.state/`、证书、私钥、控制台截图或真实 Secret；
- 不把 `ADP_SKILL_FILE_URL`、AppKey、回调密钥或 access token 写入日志；
- 管理 API 和聊天 API 只允许腾讯官方端点，端点变化必须重新生成批准计划；
- 不自动执行 SSH、`sudo`、删除、云端 apply、发布、Nginx reload 或回滚；
- 创建请求发生不确定超时时不直接重试，重新运行 `apply` 先做资源对账；
- Nginx 保留完整 URI 和查询串用于代理，但访问日志主动丢弃查询串；
- 验收数据只使用合成内容，不输入教师、学生或学校个人信息。

## 规范与限制

- ADP Skill ZIP 最大 10 MB、300 个有效文件，且只能包含纯文本；
- `SKILL.md` 必须位于 ZIP 根目录，Frontmatter 的 `name` 只能含小写字母、数字和单连字符；
- `CreateSkill` 需要平台可访问的 `FileUrl`，不能直接传本地 ZIP；
- ADP 创建接口没有公开的客户端幂等键，因此本项目使用查询、精确匹配、本地状态和"歧义停止"实现安全重入；
- 微信客服渠道、主体认证、备案、扫码和管理员授权必须手工完成。
