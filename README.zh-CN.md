<p align="center"><img src="assets/wordmark.svg" alt="HumanGrant" width="100%"></p>

<p align="center">让 AI 经人类授权登录的开放协议。</p>

<p align="center"><a href="README.md">English</a> · <strong>简体中文</strong></p>

<p align="center">
  <a href="https://github.com/LIghtJUNction/humangrant/actions/workflows/ci.yml"><img src="https://github.com/LIghtJUNction/humangrant/actions/workflows/ci.yml/badge.svg?branch=main" alt="CI" height="24"></a>
  <a href="spec/v0.1.md"><img src="assets/badges/protocol.svg" alt="Protocol 0.1" height="24"></a>
  <a href="Cargo.toml"><img src="assets/badges/rust.svg" alt="Built with Rust" height="24"></a>
  <a href="migrations/0001.sql"><img src="assets/badges/sqlite.svg" alt="SQLite" height="24"></a>
  <a href="openapi.yaml"><img src="assets/badges/openapi.svg" alt="OpenAPI 3.1" height="24"></a>
  <a href="skills/"><img src="assets/badges/skills.svg" alt="2 Agent Skills" height="24"></a>
  <a href="LICENSE"><img src="assets/badges/license.svg" alt="MIT License" height="24"></a>
</p>

<p align="center"><a href="spec/v0.1.md">协议</a> · <a href="openapi.yaml">接口</a> · <a href="examples/README.md">示例</a> · <a href="docs/integration.md">接入文档</a></p>

## 让 AI 为你的项目接入 HumanGrant

HumanGrant 默认通过无头 API 和公开发现接口接入，无需在应用中添加可见按钮。
下方按钮是可选的界面示例；供人类确认授权、拒绝和撤销的页面仍然保留。

<p align="center">
  <a href="skills/humangrant-integrate/SKILL.md">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="assets/continue-with-human-beings-dark.svg">
      <img src="assets/continue-with-human-beings.svg" alt="Continue with human beings" width="368" height="64">
    </picture>
  </a>
</p>

<!-- BEGIN HUMANGRANT INTEGRATION PROMPT -->

```text
请按 https://github.com/LIghtJUNction/humangrant/blob/main/skills/humangrant-integrate/SKILL.md 为当前项目接入 HumanGrant。
```

<!-- END HUMANGRANT INTEGRATION PROMPT -->

## 如何工作

**申请 → 批准 → 执行**

AI 向你发送链接或邮件邀请。你在自己的设备上打开，选择允许的操作和资源。已登录时，直接确认授权，无需重复登录。AI 以自己的身份继续任务，你可以随时撤销授权。

## 本地运行

先安装 Rust 和 Python：

```sh
git clone https://github.com/LIghtJUNction/humangrant.git
cd humangrant
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python examples/setup_demo.py --dir .state
cargo run -- serve .state/config.json
```

服务默认以无头模式启动：<http://127.0.0.1:8787> 返回发现 JSON，不显示应用按钮。
<http://127.0.0.1:8787/.well-known/humangrant.json> 始终提供公开发现信息；即使在
`.state/config.json` 中设置 `"agent_ui": true` 启用可选的根路径演示界面，该接口也保持可用。默认值为 `false`。
AI 客户端必须独立确认所配置来源可信；发现信息只是元数据，不代表授权。
按[完整示例](examples/README.md)连接 AI 并读取一条笔记，远程运行请看[部署文档](docs/deployment.md)。

## Agent 技能

| 技能 | 用途 |
| --- | --- |
| [humangrant-integrate](skills/humangrant-integrate/SKILL.md) | 为现有项目接入 HumanGrant。 |
| [humangrant-use](skills/humangrant-use/SKILL.md) | 申请授权并继续任务。 |

将技能链接交给 AI，或把对应技能文件夹复制到客户端的技能目录。

---

[参与贡献](CONTRIBUTING.md) · [MIT 许可证](LICENSE)
