# HumanGrant 登录链接精简记录

本次更新将 HumanGrant 收敛为一个流程：**AI 生成登录链接 → 人类使用已有账号认证并明确确认 → 原 AI 单次领取独立会话**。实现已推送至 `main`，对应提交为 [54c784c46968a0693adef868ea14ff23f45574ff](https://github.com/LIghtJUNction/humangrant/commit/54c784c46968a0693adef868ea14ff23f45574ff)，[该提交的 CI](https://github.com/LIghtJUNction/humangrant/actions/runs/44053222051) 已通过。本次没有部署生产环境。

## 界面与入口

正常首页只保留简洁说明，没有登录按钮或表单。AI 通过 HTML 头部元数据、HTTP `Link` 响应头、`/.well-known/humangrant.json` 和 `/agent.md` 发现登录流程。人类打开生成的专用链接后，查看服务、请求、账号和访问范围，再明确确认。

已移除浏览器请求控制台、邮件邀请、笔记界面和授权仪表板。签名撤销 API 与参考资源后端仍保留，用于接入方控制授权，以及验证独立会话的实际访问范围。

## 验证结果

| 检查 | 结果与范围 |
| --- | --- |
| Rust 测试 | 28 项通过，覆盖实际调度器、身份验证与会话行为。 |
| Python 测试 | 157 项通过，覆盖客户端、SQL 规则、前端模块与契约。 |
| 实际 HTTP 链路 | 七组通过，使用本地 Rust 服务验证登录链接及会话链路。 |
| 格式、静态与契约检查 | `cargo fmt`、Clippy、文档、技能、Schema 与 OpenAPI 检查通过。 |
| 移动端布局 | 390px 视口下首页、完成页无横向溢出；确认页扣除滚动条后可用宽度为 375px，`scrollWidth` 同为 375px。 |

以上结果针对仓库实现和本地验证环境。接入外部网站仍需对接该网站真实的账号认证与权限系统；本次没有验证所有外部网站的通用登录能力。

## 页面预览

| 预览 | 来源 |
| --- | --- |
| [桌面首页](../previews/home-desktop.jpg) | 实际本地服务。 |
| [桌面登录页](../previews/login-desktop.jpg) | 实际本地服务。 |
| [移动端布局](../previews/mobile-layouts.jpg) | 390px 视口，使用真实前端资产和合成账号数据的渲染 fixture；不包含真实账号已登录状态。 |

## 升级说明

旧配置文件应移除 `mail` 字段。旧数据库中的投递表不强制删除，现有数据库记录继续保留。
