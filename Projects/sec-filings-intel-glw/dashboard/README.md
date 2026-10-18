# SEC 财报实时工作台

本服务由一个 Node.js 进程提供页面、只读数据接口、PostgreSQL 实时订阅和本机资源状态。服务运行在 Windows 主机上，读取主机 CPU/RAM，并通过 mineru-api 容器读取 RTX 4070 状态。

## 位置与访问

- 应用与 npm 依赖：Projects/sec-filings-intel-glw/dashboard/
- 页面：http://127.0.0.1:8090
- 数据库：Docker 容器 mineru-postgres 中的 sec_financials
- PostgreSQL、Redis、MinerU 和 pgvector 的服务由 LongShu 根目录下的 Docker Compose 配置管理

## 启动

先在 LongShu 根目录运行 start-services.ps1 启动 Docker 基础服务，再运行 start-nodejs.ps1 启动工作台。Windows 资源管理器中可双击 start-services.bat 和 start-nodejs.bat。

运行 stop-nodejs.ps1 会停止 Node.js 工作台；restart-nodejs.ps1 会重启工作台。这两个脚本不会停止 Docker 容器。应用日志写入 LongShu 根目录下的 Logs/sec-dashboard/。若本地缺少 npm 依赖，启动脚本使用 package-lock.json 安装，并将 npm 缓存放在 LongShu/Cache/npm。

数据库账号密码默认从 LongShu 根目录下的 Docker/mineru-stack/.env 读取，也可以使用 SEC_ENV_FILE 环境变量指定配置文件；不要把密码复制到页面或日志。

## 实时数据

schema.sql 创建 pipeline_events 事件表，并在文件、页级证据、结构化信息点、解析运行记录和事件表上安装 PostgreSQL 通知触发器。数据库事务提交后，Node.js 使用 LISTEN/NOTIFY 接收变更并通过 SSE 推送给浏览器。首次打开页面会从数据库载入当前成果和事件记录；浏览器自动重连后会按事件 ID 补齐事件。

重新运行 Projects/sec-filings-intel-glw/run_pipeline.py 时，会记录源文件校验、MinerU GPU 解析、信息点提取、数据库入库和报告导出阶段。已有 SEC 记录通过 event_key 幂等写入可查看的历史时间线。

资源卡片每约 3 秒更新一次：CPU/RAM 来自主机，GPU 利用率、显存和温度由 mineru-api 容器内的 nvidia-smi 读取。

## 只读接口

- GET /api/health：应用与数据库连接状态
- GET /api/snapshot：文件、信息点、处理事件和解析运行记录的当前快照
- GET /api/resources：当前 CPU、RAM 与 GPU 状态
- GET /api/events：SSE 实时事件流
