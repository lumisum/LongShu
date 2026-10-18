# LongShu

LongShu 是本机智能体与文档分析项目的统一根目录。仓库保存项目源码、可复用的部署配置和文档；原始文件、数据库、模型权重及运行缓存保留在本机。

## 项目结构

| 路径 | 内容 | GitHub 策略 |
|---|---|---|
| Projects/sec-filings-intel-glw/ | Intel 与 Corning SEC 文件分析、Node.js 实时工作台、数据库 Schema | 提交源码、依赖锁文件和通用配置；排除真实数据与密钥 |
| Docker/mineru-stack/ | MinerU GPU、PostgreSQL、Redis 的 Compose 和镜像构建配置 | 提交 Compose、Dockerfile、说明和 .env.example；排除 .env |
| Docker/nagarjuna-pgvector/ | pgvector 数据库 Compose 与初始化 SQL | 提交配置、初始化 SQL 和 .env.example；排除 .env 与数据库数据 |
| Data/ | SEC 原始文件、MinerU 解析结果、报告和其他业务数据 | 本机数据，不提交 |
| Models/、Cache/ | 模型权重和下载/构建缓存 | 本机缓存，不提交 |
| Docker/DockerDesktopWSL/、WSL/ | Docker 与 Ubuntu 的虚拟磁盘和运行数据 | 本机运行时，不提交 |
| Logs/、Tools/、DockerShare/ | 日志、安装工具和本机共享目录 | 默认不提交 |

## SEC 实时分析

SEC 工作流对 Intel 与 Corning 定期报告进行 MinerU GPU 解析，将页级证据和结构化信息点写入 PostgreSQL，并用 Redis 保存任务状态。Node.js 工作台通过 PostgreSQL LISTEN/NOTIFY 和 SSE 展示处理进度及 CPU、RAM、RTX 4070 状态。

- 项目说明：Projects/sec-filings-intel-glw/README.md
- 实时工作台说明：Projects/sec-filings-intel-glw/dashboard/README.md
- 本机页面：http://127.0.0.1:8090
- SEC 原件和报告输出位于 Data/Finance/SEC/，不在源码仓库中

## 本机运行配置

本机将 LONGSHU_HOME 设为 E:\LongShu，并把 Docker Desktop 的数据盘放在 Docker/DockerDesktopWSL/。.gitignore 会排除数据库密码、虚拟磁盘、容器数据、模型、缓存和原始文件。克隆到其他机器后，先复制各服务目录中的 .env.example 为 .env 并填写本机配置；.env 不得提交。

部署时应使用具备 NVIDIA Container Toolkit 支持的 Docker 环境；MinerU GPU 容器按 Compose 配置申请 GPU。

## 准备 GitHub 仓库

克隆仓库后，在服务目录中将 .env.example 复制为 .env 并填写本机配置。所有业务数据和运行时文件保存在 LongShu 根目录下的本地数据目录，不提交到 GitHub。

提交前检查：

1. git status 中不应出现 .env、SEC 原件/解析输出、模型权重、日志或 .vhdx 文件。
2. .env.example 只能包含示例值和占位密码。
3. 暂存清单只应包含源码、通用配置和文档。

目录边界与提交规则另见 docs/repository-layout.md。
