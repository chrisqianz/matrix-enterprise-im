# 依赖声明

本项目使用了以下第三方开源库，特此声明感谢所有贡献者的工作。

## Python 依赖

| 库名 | 版本 | 许可证 | 说明 |
|------|------|--------|------|
| fastapi | 0.104.1 | MIT | 现代 Python Web 框架 |
| uvicorn | 0.24.0 | BSD-3 | ASGI 服务器 |
| sqlalchemy | 2.0.23 | MIT | Python SQL 工具包 |
| psycopg2-binary | 2.9.9 | LGPL | PostgreSQL 适配器 |
| aiohttp | 3.9.1 | Apache 2.0 | 异步 HTTP 客户端/服务器 |
| pycryptodome | 3.19.0 | Apache 2.0 | 加密库 |
| pydantic | 2.5.0 | MIT | 数据验证库 |
| python-jose | 3.3.0 | BSD | JSON Object Signing and Encryption |
| python-multipart | 0.0.6 | Apache 2.0 | Multipart 数据解析 |

## Docker 镜像依赖

| 镜像 | 版本 | 许可证 | 说明 |
|------|------|--------|------|
| matrixdotorg/synapse | 1.84.0 | Apache 2.0 | Matrix 参考服务器 |
| vectorim/element-web | 1.11.58 | Apache 2.0 | Matrix 客户端 |
| postgres | 15.4 | PostgreSQL | 关系型数据库 |
| nginx | 1.25.3 | BSD-2 | 反向代理服务器 |

## 许可证兼容性说明

本项目采用 MIT 许可证，与以上所有依赖的许可证兼容：

- MIT 许可证：完全兼容
- Apache 2.0 许可证：完全兼容（需保留版权声明）
- BSD 许可证：完全兼容
- LGPL 许可证：动态链接兼容

## 第三方代码引用

本项目未直接复制任何第三方代码，所有依赖均通过标准包管理器（pip、Docker）安装。
