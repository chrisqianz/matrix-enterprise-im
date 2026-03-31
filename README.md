# Matrix 企业自建 IM 解决方案

基于 Matrix 协议的企业自建即时通讯系统，通过 AppService 桥接器对接企业微信，实现企业内部的统一消息平台。

## 项目简介

本项目是一个企业级即时通讯解决方案，主要特点包括：

- **完全合规**：使用企业微信官方 API，无封号风险
- **稳定可靠**：基于 Matrix 协议，支持高并发
- **易于部署**：一套 Docker Compose 配置，开箱即用
- **消息归档**：支持企业微信消息历史归档，数据永久保存
- **双向同步**：企业微信与 Matrix 消息双向实时同步
- **虚拟用户**：自动创建虚拟用户（Puppet），支持多用户管理
- **Portal 房间**：自动创建 Portal 房间，隔离不同会话

## 架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                        公网域名 (HTTPS)                           │
│                        matrix.example.com                        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         Nginx (反向代理)                         │
│  - 80/443 端口                                                   │
│  - SSL 证书 (Let's Encrypt)                                       │
│  - 路由：/_matrix → Synapse, / → Element, /wecom → Bridge        │
└─────────────────────────────┬───────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐
│ Synapse         │ │ Element Web     │ │ WeCom Bridge        │
│ (8008)          │ │ (80)            │ │ (8000)              │
│ - Matrix API    │ │ - 客户端界面    │ │ - AppService        │
│ - 消息存储      │ │                │ │ - 企业微信 API       │
│ - 用户管理      │ │                │ │ - 虚拟用户 (Puppet)   │
└────────┬────────┘ └─────────────────┘ └──────────┬──────────┘
         │                                         │
         │         AppService API                  │
         └─────────────────┬───────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ PostgreSQL      │ │ PostgreSQL      │ │ 企业微信官方 API  │
│ (matrix)        │ │ (wecom)         │ │ (完全合规)       │
│ - Matrix 数据   │ │ - 用户映射      │ │ - 无封号风险     │
│ - 消息历史      │ │ - 消息日志      │ │ - 稳定运行       │
└─────────────────┘ └─────────────────┘ └─────────────────┘
```

## 快速开始

### 1. 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 内存：至少 4GB（推荐 8GB）
- 磁盘：至少 10GB 可用空间
- 公网域名（用于 HTTPS）

### 2. 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/your-username/matrix-enterprise-im.git
cd matrix-enterprise-im

# 2. 复制环境变量模板
cp .env.example .env

# 3. 修改配置（编辑 .env 文件）
# - 设置企业微信配置
# - 设置域名
# - 生成随机 Token

# 4. 启动所有服务
docker-compose up -d

# 5. 访问 Element Web
# https://matrix.example.com
```

### 3. 配置企业微信

1. 登录 [企业微信管理后台](https://work.weixin.qq.com)
2. 创建企业应用
3. 获取 `corp_id`、`secret`、`agent_id`
4. 配置接收消息：
   - URL: `https://matrix.example.com/wecom/callback`
   - Token: 自定义
   - EncodingAESKey: 自定义（34 位字符）
   - 加解密方式：aes

详细部署指南请查看 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 技术栈

### 核心组件

| 组件 | 版本 | 说明 |
|------|------|------|
| Synapse | 1.84.0 | Matrix 协议服务器 |
| Element Web | 1.11.58 | Matrix 客户端 Web 界面 |
| FastAPI | 0.104.1 | 桥接服务 Web 框架 |
| PostgreSQL | 15.4 | 关系型数据库 |
| Nginx | 1.25.3 | 反向代理服务器 |

### Python 依赖

```python
# 桥接服务依赖
fastapi==0.104.1
uvicorn[standard]==0.24.0
sqlalchemy==2.0.23
psycopg2-binary==2.9.9
aiohttp==3.9.1
pycryptodome==3.19.0
pydantic==2.5.0
python-jose[cryptography]==3.3.0
python-multipart==0.0.6
```

## 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。

## 依赖声明

本项目使用了以下开源项目，感谢所有贡献者：

- [Synapse](https://github.com/matrix-org/synapse) - Apache 2.0 许可证
- [Element Web](https://github.com/element-hq/element-web) - Apache 2.0 许可证
- [FastAPI](https://github.com/tiangolo/fastapi) - MIT 许可证
- [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) - MIT 许可证
- [aiohttp](https://github.com/aio-libs/aiohttp) - Apache 2.0 许可证

## 贡献

欢迎提交 Issue 和 Pull Request！

## 问题反馈

如有问题，请通过以下方式联系我们：

- [GitHub Issues](https://github.com/your-username/matrix-enterprise-im/issues)
- Email: your-email@example.com

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=your-username/matrix-enterprise-im&type=Date)](https://star-history.com/#your-username/matrix-enterprise-im&Date)
