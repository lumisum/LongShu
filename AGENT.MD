# LongShu 智能体协作指南

本文件描述项目边界和本机约定，供 Codex、Cursor、Gemini 及其他开发工具使用。变更启动方式、端口、数据路径或架构时，请同步更新根目录 `README.md` 和相关组件文档。

## 项目定位

LongShu 是通用的信息提取与证据追溯服务。目标是将不同来源和不同业务场景接入清晰、可替换的处理环节，包括采集、解析、抽取、核验、入库和结果展示。组件通过接口组合，具体实现按场景选择。

当前仓库的可运行样例以 SEC 财报分析为主：MinerU 解析文档，Python 流水线提取信息并写入 PostgreSQL，Redis 保存任务状态，Node.js 工作台实时展示事件、产出和机器资源。请明确区分当前实现与目标设计：通用能力接口尚未完整抽象；招投标文件分析、废标风险与控标参数识别尚未在此仓库实现。

能力边界使用“基础能力”和“Extended Abilities（扩展能力）”描述：可复用的任务、证据、事件和观察机制属于基础能力方向；面向特定来源或领域的采集器、解析器和分析规则属于扩展能力方向。当前组件尚未全部整理为稳定接口，开发时应明确标记已实现与规划中内容。

所有分析结论都应尽可能关联来源、页码或坐标、证据片段。不能核验的内容要标记为不确定，不得把模型推测描述为事实。

## 当前目录和组件

- `Projects/sec-filings-intel-glw/run_pipeline.py`：当前 SEC 文档分析样例。
- `Projects/sec-filings-intel-glw/dashboard/`：Node.js 实时工作台，默认监听 `127.0.0.1:8090`。
- `Projects/sec-filings-intel-glw/schema.sql`：SEC 样例使用的表、事件和 PostgreSQL 通知。
- `Docker/mineru-stack/`：MinerU GPU、PostgreSQL、Redis 与 WebUI 的 Compose 配置。
- `Docker/nagarjuna-pgvector/`：独立的 pgvector PostgreSQL 开发服务，监听本机 `5433`。
- `Data/`、`Models/`、`Cache/`、`Logs/`：本机业务数据、模型、缓存和日志，禁止提交。

新增场景应优先建立明确的能力契约和可替换实现，避免把 LongShu 的通用处理流程永久绑定到 SEC、单一采集器或单一解析模型。必要时先从已有样例提炼接口，再迁移实现；不要只在文档中宣称接口已存在。

## 本机路径与 Docker 数据

- 本机项目根目录固定为 `E:\LongShu`，`LONGSHU_HOME` 可用于定位根目录。
- Docker Desktop 的自定义 WSL 目录位于 `E:\LongShu\Docker\DockerDesktopWSL`。Docker 虚拟磁盘、镜像层、容器数据和卷必须留在 E 盘，不能改回 C 盘默认数据目录。
- 本机已核对 Docker Desktop 的 `CustomWslDistroDir` 指向上述 E 盘目录，实际 Docker 数据虚拟磁盘位于该目录；提交前仍要避免将虚拟磁盘或卷加入 Git。
- `Data/` 放输入文件、解析结果和输出；`Models/` 放模型权重；`Cache/` 放依赖与下载缓存；`Logs/` 放运行日志。新增本机数据不得写入源码仓库。
- Docker Desktop 安装程序本身属于本机软件；不得将 Docker 数据目录、镜像或容器迁移到 C 盘。

## 手动启动与资源策略

基础服务严禁设置为 Windows 开机自动启动。Docker Desktop 的 AutoStart 必须保持关闭；Docker Compose 服务不得采用 `always`、`unless-stopped` 等自动重启策略。创建或更新容器时，确认容器自身重启策略也是 `no`。

- `start-services.ps1` / `start-services.bat`：手动打开 Docker Desktop（仅当 Engine 未运行时）并启动两个 Compose 服务栈；MinerU API 使用 NVIDIA GPU 0。
- `stop-services.ps1` / `stop-services.bat`：手动停止基础容器，保留数据卷；不得清理 Docker 数据。
- `start-nodejs.ps1` / `start-nodejs.bat`：独立启动 Node.js 工作台；若安装 npm 依赖，依赖位于项目目录，npm 缓存位于 `Cache/npm`。
- `stop-nodejs.ps1` / `stop-nodejs.bat` 与 `restart-nodejs.ps1` / `restart-nodejs.bat`：只管理 Node.js 工作台，不改变基础容器状态。
- SEC 分析流水线是独立批处理，不会随开机、基础服务或工作台自动运行。用户明确需要时，从根目录运行 `python Projects/sec-filings-intel-glw/run_pipeline.py`。
- 不创建 Windows 服务、计划任务、登录启动项或其他会在开机/登录时自动拉起上述组件的配置。

需要修改启动方式时，同步审计 Docker Desktop AutoStart、Windows 注册表 Run 项、启动文件夹、计划任务、Compose restart policy 和已有容器 restart policy。

## 服务和开发约定

- Node.js 工作台要求 Node.js 22 或更高版本；依赖清单和锁文件位于 `Projects/sec-filings-intel-glw/dashboard/`，通过 `npm ci` 安装。
- 维持现有 Python、Node.js ES Modules、PowerShell、SQL 编码风格。
- 优先使用项目根目录相对路径或 `LONGSHU_HOME`；不要把 `C:\Users\...` 等个人路径写入可提交配置。
- MinerU GPU 声明位于 `Docker/mineru-stack/compose.yaml`。修改容器配置时保留 GPU 预留；不要未经说明将推理改成 CPU。
- 工作台通过 PostgreSQL `LISTEN/NOTIFY` 和 SSE 更新页面。更改事件协议或数据库结构时，要同时核对生产事件的流水线与订阅事件的工作台。
- 不要在没有用户要求时运行完整业务分析，也不要用真实数据验证时将数据写入仓库。

## 数据、密钥与版本控制

- `.env`、密码、密钥、令牌和真实凭据不得提交；只提交 `.env.example`，并使用明确的示例占位值。
- SEC 原件、HTML/PDF、`filings.json`、解析中间文件、数据库导出、报告和业务记录均属于本机数据，不得提交。
- 模型权重、`Cache/`、`Logs/`、`node_modules/`、Docker 虚拟磁盘与数据卷不得提交。
- 修改 `.gitignore` 或暂存文件前，检查路径和内容；提交前复核完整暂存清单。
- LongShu 是独立仓库；不要重新添加 Sika。

## 常用入口

- 完整使用与目录说明：`README.md`
- 仓库边界：`docs/repository-layout.md`
- SEC 样例：`Projects/sec-filings-intel-glw/README.md`
- 实时工作台：`Projects/sec-filings-intel-glw/dashboard/README.md`
- Docker / MinerU：`Docker/mineru-stack/README.md`
