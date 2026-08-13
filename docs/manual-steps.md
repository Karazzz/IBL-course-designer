# 必须手动完成的控制台步骤

本项目不会代替用户登录控制台、扫码、认证、备案、授权、上传 Skill、创建微信客服账号或发布线上渠道。以下步骤涉及主体身份、付费、密钥或线上资源，必须由企业管理员完成。

## 1. 腾讯云实名认证和 ADP 开通

1. 使用企业主体腾讯云账号完成实名认证。
2. 开通腾讯云智能体开发平台 ADP，确认账号有空间、应用、Agent、Skill 和发布权限。
3. 在 CAM 中创建最小权限的调用身份，不使用主账号长期密钥。测试阶段可先使用受限子账号。
4. 获取 `SecretId`、`SecretKey`；临时凭证还需 `SessionToken`。只通过环境变量或部署平台的 Secret 管理注入：

```text
TENCENTCLOUD_SECRET_ID
TENCENTCLOUD_SECRET_KEY
TENCENTCLOUD_SESSION_TOKEN
```

5. 不把密钥粘贴到聊天、截图、工单、README、命令参数、Git 或 Nginx 配置。完成测试后按企业制度轮换密钥。
6. 使用频繁轮换的临时凭证时，通过非敏感的 `ADP_ACCOUNT_FINGERPRINT` 指定稳定账号/角色标签；计划只保存其 SHA-256，不保存标签原文或凭证。

## 2. 企业微信认证

1. 登录企业微信管理后台，确认企业主体与微信客服主体一致。
2. 完成企业微信认证。腾讯云文档明确指出，回调域名校验失败时需要先完成企业认证。
3. 由企业管理员确认操作人拥有微信客服、API 接收、企业 Secret 和授权管理权限。

## 3. 域名备案、DNS 和 HTTPS

1. 准备企业主体拥有的域名并完成 ICP 备案；认证企业应使用认证主体名下已备案域名。
2. 将 `PUBLIC_DOMAIN` 的 DNS 记录解析到 Nginx 代理服务器公网 IP。
3. 为完整域名申请有效 HTTPS 证书，服务器保存证书链和私钥；不要把私钥放入本项目。
4. 将证书路径通过 `TLS_CERT_PATH`、`TLS_KEY_PATH` 注入服务器环境。
5. 通过 `PROXY_CA_CERT_PATH` 配置服务器 CA 证书包，确认 Nginx 会验证两个腾讯上游的证书和主机名。
6. 开放公网 443，确认 Nginx 能访问 `qyapi.weixin.qq.com:443` 和 `chan.lke.cloud.tencent.com:443`。
7. Nginx 配置并不是回调业务处理器，只按原 URI 和查询串转发；不要自行改写腾讯云生成的回调后缀。

## 4. 微信客服账号创建

1. 访问 [微信客服后台](https://kf.weixin.qq.com/)。
2. 在“企业信息”确认企业 ID。
3. 在“客服账号”创建教师可见的客服账号，设置名称、头像和接待方式。
4. 记录要绑定的客服账号名称或标识，但不要把企业 Secret 写入仓库。

## 5. ADP Skill 上传和模型选择

1. 本地运行校验和打包：

```powershell
python scripts/validate_skill.py --source .
python scripts/package_skill.py
python scripts/validate_skill.py --zip dist/IBL-course-designer.zip
```

2. 在 ADP Skills 广场创建自定义 Skill，上传 `dist/IBL-course-designer.zip`。
3. 等待平台解析和安全检查可用，记录 Skill ID，注入 `ADP_SKILL_ID`。
4. 在 Claw 模式应用可用模型列表中选择模型，记录 Model ID，注入 `ADP_MODEL_ID`。
5. 公共 API 的 `CreateSkill.FileUrl` 不接受本地 ZIP，公开文档也没有本地文件上传 API。因此上传步骤默认必须在控制台完成。只有从已认证控制台流程获得有效文件地址时，才使用 `ADP_SKILL_FILE_URL`。

## 6. 创建并审核 Claw 应用

可以用本项目客户端创建或复用空间、Claw 应用和 Agent，但必须先输出并人工审核计划：

```powershell
python scripts/adp_client.py --env-file .env plan
```

确认计划中的空间、应用名、模型、Skill、Agent 和操作列表。只有明确批准后，才把输出的哈希传给 `apply`。创建完成后在 ADP 控制台人工核对：

- 应用模式为 Claw；
- 主 Agent 使用正确模型；
- `ibl-course-designer` Skill 已加载；
- Agent 指令和微信多轮规则正确；
- 没有意外插件、工具或共享范围；
- 测试会话不含真实教师或学生数据。

## 7. 微信客服渠道配置

1. 确认 ADP 应用已成功发布。
2. 在 ADP“应用发布”中新建“微信客服”渠道。
3. 输入微信客服后台取得的企业 ID。
4. 在 ADP 渠道回调设置中填写已备案的 HTTPS 域名。只填域名时按控制台提示操作，不自行拼接回调后缀。
5. ADP 创建渠道后会显示服务器地址 `URL`、`Token` 和 43 位 `EncodingAESKey`。把三项复制到微信客服后台的回调配置并完成验证。
6. 首次完成微信客服回调配置后，在微信客服后台“企业信息”获取企业 `Secret`。
7. 回到 ADP 渠道配置，填写企业 `Secret` 并选择已创建的微信客服账号。
8. `企业 ID`、`Secret`、`URL`、`Token`、`EncodingAESKey` 只在相应控制台和 Secret 管理系统之间传递，不写入 `.env.example`、文档、日志或 Git。Nginx 不需要知道这些值。

## 8. 扫码和管理员授权

1. 由企业微信超级管理员或有权限管理员登录、扫码并确认腾讯云 ADP/微信客服所需授权。
2. 检查授权企业、客服账号和应用名称，避免授权到测试企业或错误账号。
3. 在 ADP 发布时勾选微信客服渠道，确认发布和渠道服务状态均成功。
4. 从“服务状态 > 运行渠道 > 分享二维码”获取客服二维码。
5. 管理员先扫码验收，再由至少一名普通微信用户测试。不要直接把未验收二维码发给教师。

## 9. 人工验收清单

- 首句在尺度不明确时询问“整套还是单节”，并建议整体优先；
- 每轮最多两个问题；
- 信息足够后先给待确认框架，不越过确认直接生成；
- 确认后单节课包含教案、PPT、逐环节学生物料和教师工具包；
- 文件可下载、打开、打印，课件简洁且要点逐步呈现；
- 连续多轮会话保持上下文；
- 微信文本超长时分段合理；
- 不要求教师提供真实学生姓名、照片或敏感信息；
- Nginx 日志不记录查询串；
- Nginx 上游证书验证已开启，服务器 CA 路径有效；
- Claw 模式以文本和文件为主要交付。腾讯云文档目前只保证标准模式应用理解微信客服图片消息，不应承诺 Claw 图片问答。

## 官方参考

- [Skills 文件规范](https://cloud.tencent.com/document/product/1759/134602)
- [从零搭建 Claw 模式应用](https://cloud.tencent.com/document/product/1759/133869)
- [将应用发布到微信客服](https://cloud.tencent.com/document/product/1759/122567)
- [企业微信回调协议](https://developer.work.weixin.qq.com/document/path/90930)
