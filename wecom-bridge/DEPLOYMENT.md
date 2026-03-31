# 企业微信-Matrix 桥接服务 - 部署文档

## 📋 前置要求

- Docker & Docker Compose
- PostgreSQL 14+
- Python 3.10+

---

## 🚀 快速部署

### 1. 克隆项目

```bash
git clone <repository>
cd wecom-bridge
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```env
# 数据库
DATABASE_URL=postgresql://wecom:password@postgres-wecom/wecom

# Matrix
MATRIX_HOMESERVER=http://synapse:8008
MATRIX_DOMAIN=matrix.example.com
AS_TOKEN=your_as_token
HS_TOKEN=your_hs_token

# 企业微信
WECOMP_CORP_ID=your_corp_id
WECOMP_SECRET=your_secret
WECOMP_AGENT_ID=1000001
WECOMP_TOKEN=your_callback_token
WECOMP_ENCODING_AES_KEY=your_aes_key
```

### 3. 启动服务

```bash
docker-compose up -d
```

### 4. 运行数据库迁移

```bash
docker-compose exec bridge psql $DATABASE_URL -f /app/migrations/001_initial_schema.sql
```

### 5. 验证部署

```bash
curl http://localhost:8000/health
```

---

## 📊 架构说明

```
企业微信 ←→ wecom-bridge ←→ Matrix Synapse
             │
             └─→ PostgreSQL
```

---

## 🔧 配置说明

### Matrix AppService 配置

在 Synapse 的 `homeserver.yaml`：

```yaml
app_service_modules:
  - "appservice.yaml"
```

`appservice.yaml`：

```yaml
as_token: <AS_TOKEN>
hs_token: <HS_TOKEN>
sender_localpart: wecom_bridge
url: http://wecom-bridge:8000
namespaces:
  users:
    - regex: ^@wecom(_ext)?_.*$
      exclusive: true
  rooms:
    - prefix: "#wecom_"
      exclusive: true
```

---

## 📈 监控

### 健康检查

```bash
curl http://localhost:8000/health
```

### 日志查看

```bash
docker-compose logs -f bridge
```

---

## 🐛 故障排查

### 问题 1：数据库连接失败

```bash
docker-compose exec bridge psql $DATABASE_URL -c "SELECT 1"
```

### 问题 2：Matrix 连接失败

```bash
docker-compose exec bridge curl $MATRIX_HOMESERVER/_matrix/client/versions
```

### 问题 3：企业微信回调失败

检查企业微信后台配置：
- URL: `http://your-domain:8000/wecom/callback`
- Token: 与 `.env` 中一致

---

## 📝 下一步

1. 配置 Nginx 反向代理
2. 配置 SSL 证书
3. 配置监控告警
4. 配置备份策略
