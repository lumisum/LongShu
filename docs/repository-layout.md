# LongShu 仓库边界

## 可提交内容

- LongShu 根目录说明、目录规则和 .gitignore。
- SEC 分析 Python 源码、Node.js 工作台源码、npm 锁文件、Schema 和操作说明。
- Docker Compose、Dockerfile、数据库初始化 SQL、.env.example。

## 仅保留在本机

- Data/：SEC PDF/HTML、MinerU 中间文件、数据库导出的报告与 CSV/JSON。
- Models/ 和 Cache/：模型权重、包缓存、浏览器缓存。
- Docker/DockerDesktopWSL/ 和 WSL/：虚拟磁盘、镜像、容器、数据库卷。
- Logs/、Tools/、DockerShare/：本机日志、安装文件和共享数据。
- 所有 .env：包含 PostgreSQL、Redis 等服务密码。仓库只保存 .env.example。

## 路径规则

项目清单中的本地文件路径使用相对于 LongShu 根目录的正斜杠路径。Python 流水线默认从 LONGSHU_HOME 环境变量定位 LongShu；未设置时从自身源码路径推导根目录。数据默认放在 Data/Finance/SEC/，可通过 SEC_DATA_DIR 覆盖。

Docker Compose 配置只定义容器和服务。Docker Desktop 的数据盘位置由本机 Docker Desktop 设置管理，不应在 Git 中记录虚拟磁盘文件。本机 Docker Desktop 的 WSL 数据路径配置为 `E:\LongShu\Docker\DockerDesktopWSL`。Docker Desktop 开机自启保持关闭，Compose 服务使用 `restart: "no"`；只能通过 LongShu 的手动启动脚本启动服务。

## 推送前检查

git status --short
git check-ignore -v Docker/mineru-stack/.env Data/Finance/SEC/raw/ Models/example-model.bin

在添加或推送前逐项检查暂存文件，并确认没有真实数据、密钥、模型文件或虚拟磁盘。
