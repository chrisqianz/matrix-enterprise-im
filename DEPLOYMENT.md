# Matrix 企业自建 IM 部署指南（AppService 模式）

## 📋 目录

1. [快速开始](#快速开始)
2. [环境准备](#环境准备)
3. [配置说明](#配置说明)
4. [部署步骤](#部署步骤)
5. [验证部署](#验证部署)
6. [常见问题](#常见问题)

---

## 快速开始

```bash
# 1. 复制环境变量模板
cp .env.example .env

# 2. 修改配置
vim .env  # 修改企业微信配置和域名

# 3. 生成 Token（如果 .env 中是默认值）
AS_TOKEN=$(openssl rand -hex 32)
HS_TOKEN=$(openssl rand -hex 32)
REGISTRATION_SHARED_SECRET=$(openssl rand -hex 32)

# 4. 启动所有服务
docker-compose up -d

# 5. 访问 Element Web
# https://matrix.example.com
```

---

## 环境准备

### 系统要求

- Docker 20.10+
- Docker Compose 2.0+
- 内存：至少 4GB（推荐 8GB）
- 磁盘：至少 10GB 可用空间
- 公网域名（用于 HTTPS）

### 安装 Docker

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com | bash
sudo systemctl enable docker
sudo systemctl start docker

# Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" \
  -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

---

## 配置说明

### .env 环境变量

```bash
# Matrix 数据库
POSTGRES_PASSWORD=matrix_strong_random_password_2024

# AppService 注册密钥
REGISTRATION_SHARED_SECRET=super_secret_registration_key_2024

# 企业微信桥接数据库
WECOMP_DB_PASSWORD=wecom_db_strong_password_2024

# 企业微信配置（在企业微信管理后台获取）
WECOMP_CORP_ID=ww1234567890abcdef
WECOMP_SECRET=your_wecom_secret_here
WECOMP_AGENT_ID=1000001

# AppService Token（生成方式见下文）
AS_TOKEN=your_appservice_token_here
HS_TOKEN=your_homeserver_token_here

# 域名配置
MATRIX_DOMAIN=matrix.example.com
```

### 生成 Token

```bash
# 生成 AppService Token
AS_TOKEN=$(openssl rand -hex 32)
HS_TOKEN=$(openssl rand -hex 32)
REGISTRATION_SHARED_SECRET=$(openssl rand -hex 32)

echo "AS_TOKEN=$AS_TOKEN"
echo "HS_TOKEN=$HS_TOKEN"
echo "REGISTRATION_SHARED_SECRET=$REGISTRATION_SHARED_SECRET"
```

---

## 部署步骤

### 步骤 1: 配置域名和 SSL 证书

```bash
# 1. 域名解析到服务器 IP
# 2. 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 3. 获取证书
sudo certbot --nginx -d matrix.example.com

# 4. 证书会自动放到 /etc/letsencrypt/live/matrix.example.com/
# Docker 中映射到 ./certs 目录
```

### 步骤 2: 配置企业微信

1. 登录 [企业微信管理后台](https://work.weixin.qq.com)
2. 创建企业应用
3. 获取 `corp_id`、`secret`、`agent_id`
4. 配置接收消息：
   - URL: `https://matrix.example.com/wecom/callback`
   - Token: 自定义
   - EncodingAESKey: 自定义（34 位字符）
   - 加解密方式：aes

### 步骤 3: 启动服务

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 检查服务状态
docker-compose ps
```

### 步骤 4: 创建管理员账号

```bash
# 进入 Synapse 容器
docker-compose exec synapse bash

# 创建管理员账号
python -m synapse.registration.register \
  --config-path /data/homeserver.yaml \
  --registered-users /data/admin.json

# 按提示输入用户名和密码
```

---

## 验证部署

### 检查服务状态

```bash
# 查看所有容器
docker-compose ps

# 应该看到：
# nginx          healthy
# synapse        healthy
# element        up
# wecom-bridge   healthy
# postgres       up
# wecom-db       up
```

### 检查 AppService 注册

```bash
# 查看 Synapse 日志
docker-compose logs synapse | grep "AppService"

# 应该看到：
# "Registered appservice wecom"
```

### 测试 AppService 端点

```bash
# 测试 AppService 端点
curl -X PUT "http://wecom-bridge:8000/_matrix/app/v1/transactions/test" \
  -H "Authorization: Bearer $HS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"events": [], "timeout": 0}'

# 应该返回：{"pid": 1}
```

### 测试企业微信消息

```bash
# 发送测试消息
curl -X POST http://wecom-bridge:8000/api/send \
  -H "Content-Type: application/json" \
  -d '{
    "to_user": "test_user",
    "content": "测试消息",
    "msgtype": "text"
  }'
```

---

## 常见问题

### Q1: AppService 注册失败

**排查步骤:**

1. 检查 `wecom-registration.yaml` 是否正确挂载
2. 检查 `registration_shared_secret` 是否设置
3. 查看 Synapse 日志：
   ```bash
   docker-compose logs synapse | grep -i "appservice\|error"
   ```

### Q2: 企业微信回调收不到消息

**排查步骤:**

1. 检查回调 URL 是否可公网访问
2. 验证 Token 和 EncodingAESKey 是否正确
3. 查看 Nginx 日志：
   ```bash
   docker-compose logs nginx | grep wecom
   ```
4. 查看桥接服务日志：
   ```bash
   docker-compose logs wecom-bridge
   ```

### Q3: Matrix 消息无法转发到企业微信

**排查步骤:**

1. 检查用户映射是否创建
2. 查看桥接服务日志：
   ```bash
   docker-compose logs wecom-bridge | grep "Matrix 消息"
   ```
3. 验证企业微信 API 权限

### Q4: HTTPS 证书问题

**解决方案:**

```bash
# 重新获取证书
sudo certbot renew

# 重启 Nginx
docker-compose restart nginx
```

---

## 生产环境建议

### 1. 数据库备份

```bash
# 定期备份 Matrix 数据库
docker-compose exec matrix-postgres pg_dump -U matrix matrix > backup_$(date +%Y%m%d).sql

# 定期备份 WeCom 数据库
docker-compose exec wecom-db pg_dump -U wecom wecom > wecom_backup_$(date +%Y%m%d).sql
```

### 2. 监控告警

```bash
# 安装 Prometheus + Grafana
docker-compose up -d prometheus grafana

# 监控指标:
# - Matrix 消息延迟
# - 企业微信 API 调用次数
# - 桥接器错误率
```

### 3. 安全加固

```bash
# 1. 修改所有默认密码
# 2. 启用 fail2ban
# 3. 配置防火墙规则
# 4. 定期更新 Docker 镜像
```

---

## 架构总览

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

---

## 参考资料

- [Matrix 官方文档](https://matrix.org/docs/)
- [Synapse 文档](https://matrix-org.github.io/synapse/)
- [企业微信 API 文档](https://developer.work.weixin.qq.com/document/path/90227)
- [Matrix AppService 规范](https://matrix.org/docs/spec/application_service/r0.1.3)
