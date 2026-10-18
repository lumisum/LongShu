# LongShu 项目指南

## 项目定位

LongShu 是本机智能体与文档分析项目的统一目录。当前已实现的业务样例是 SEC 财报处理：用本地 MinerU GPU 服务解析 Intel 与 Corning 财报，将页级证据和结构化信息写入 PostgreSQL，并通过 Node.js 实时工作台展示处理进度、结果和机器资源状态。

招投标文件分析是后续产品方向。当前代码不应被描述为已经具备完整的废标条款或控标参数识别能力。分析结论应保留原文证据、页码和可回溯来源，不应把模型推测表述成事实。

## 目录与主要组件

- Docker/mineru-stack：MinerU GPU、PostgreSQL、Redis 和 MinerU WebUI 的 Docker Compose 配置。
- Docker/nagarjuna-pgvector：独立的 pgvector PostgreSQL 服务，监听本机 5433 端口。
- Projects/sec-filings-intel-glw/run_pipeline.py：SEC 文档解析、事实提取、入库与报告导出流水线。
- Projects/sec-filings-intel-glw/dashboard：Node.js 实时工作台，默认监听 127.0.0.1:8090。
- Projects/sec-filings-intel-glw/schema.sql：SEC 工作台使用的业务表、事件表和 PostgreSQL 通知触发器。
- Data、Models、Cache、Logs：本机数据、模型、缓存和日志目录，不提交业务内容。

Node.js 工作台从 PostgreSQL 读取当前快照，使用 LISTEN/NOTIFY 订阅数据库变化，再用 SSE 推送到页面。资源卡片读取 Windows 主机 CPU、RAM 和 MinerU 容器内的 GPU 状态。

## 本机环境与路径

本机 LongShu 根目录是 E:\LongShu。Docker Desktop 的镜像、容器和卷数据应保存在 E 盘配置的数据盘内。维护 Docker 时使用本项目 Compose 文件，不要迁移或重置 Docker Desktop 数据目录。停止容器使用 Compose stop，保留数据卷。

路径应基于项目根目录或 LONGSHU_HOME 推导。新增运行数据放到 E:\LongShu 下的 Data、Cache 或 Logs。不要把下载数据、数据库导出、模型文件或日志写进 Git 仓库。

## 启动与运维

- start-services.ps1 启动 Docker Desktop（Docker Engine 未运行时）以及两个 Compose 服务栈：MinerU GPU、PostgreSQL、Redis 和 pgvector PostgreSQL。
- start-nodejs.ps1 启动 SEC 实时工作台；若缺少 npm 依赖，会将依赖安装在 E 盘项目目录，并把 npm 缓存放到 Cache/npm。
- stop-nodejs.ps1 和 restart-nodejs.ps1 只管理 Node.js 工作台，不停止 Docker 容器。
- 对应的 .bat 文件可在 Windows 资源管理器中双击运行。
- SEC 分析流水线是独立的批处理任务，不会随 Node.js 页面服务自动启动。需要运行时，从 LongShu 根目录执行 python Projects/sec-filings-intel-glw/run_pipeline.py；本机 filings.json 和 SEC 原件必须存在。
- 工作台地址为 http://127.0.0.1:8090。工作台日志在 Logs/sec-dashboard/，分析流水线日志在 Logs/sec-pipeline/。

MinerU 的 GPU 分配由 Docker/mineru-stack/compose.yaml 中的 NVIDIA 设备预留配置控制。修改时保留 GPU 设备配置。

## 数据、密钥与版本控制

- 所有 .env、密码、密钥和凭据不得提交；只提交 .env.example。
- Data 下的 SEC 原件、HTML、PDF、解析中间文件、数据库导出和报告不得提交。
- Projects/sec-filings-intel-glw/filings.json 是本机任务清单，已加入 Git 忽略规则；保留在本机，不提交。
- 模型权重、Cache、Logs、node_modules、Docker 虚拟磁盘与卷数据不得提交。
- 新文件提交前检查 Git 暂存清单，确认不含业务数据或本机密钥。
- 不要重新添加 Sika；LongShu 是独立项目。
- Docker 相关镜像和运行数据必须留在 E 盘，不要把 Docker 数据目录迁到 C 盘。

## 修改项目时

- 遵循现有 Python、Node.js ES Modules、PowerShell 与 SQL 风格。
- Node.js 依赖以 dashboard/package-lock.json 为准；新环境使用 npm ci。
- 新的应用或存储服务优先通过接口和可替换实现组合，避免把采集、解析、核验、入库流程绑定到单一供应商。
- 解析结果保存来源、页码和证据片段；无法核验的内容标记为不确定。
- 修改启动方式、端口、服务名或数据路径时，同步更新本文件和 README.md。
