# MinerU + PostgreSQL + Redis (GPU)

本机 RTX 4070 已通过 Docker NVIDIA GPU 透传检查。该配置使用 MinerU 4.0.9、CUDA 13.0 / vLLM，并在镜像构建时从 ModelScope 下载标准解析模型。

## 启动

在此目录运行：

```powershell
docker compose up -d --build
```

首次构建需要下载 CUDA/vLLM 基础镜像、Python 依赖和模型文件，耗时取决于网络。MinerU API 使用 GPU 0；WebUI 通过 Docker 内部网络连接 API，不会再启动第二个推理实例。

## 服务地址

- MinerU WebUI：<http://127.0.0.1:7860>
- MinerU API 健康状态：<http://127.0.0.1:8000/v1/health>
- MinerU API 文档：<http://127.0.0.1:8000/docs>
- PostgreSQL：`127.0.0.1:5432`，数据库和账号为 `mineru`；密码在本目录 `.env` 的 `POSTGRES_PASSWORD`
- Redis：`127.0.0.1:6379`；密码在 `.env` 的 `REDIS_PASSWORD`

从同一 Compose 网络中的其他容器访问数据库时使用主机名 `postgres` 和 `redis`。例如 PostgreSQL 主机为 `postgres`、端口 `5432`；Redis 主机为 `redis`、端口 `6379`。

PostgreSQL 与 Redis 是独立开发服务，带持久化卷；MinerU 默认不会把解析任务或文档数据写入这两个服务。

## 管理

```powershell
docker compose ps
docker compose logs -f mineru-api
docker compose stop
docker compose down
```

`docker compose down` 会保留数据库和 Redis 数据卷。删除数据卷的命令是 `docker compose down -v`。

## 版本和来源

- MinerU Dockerfile 依据官方 `mineru-4.0.9-released` China GPU Dockerfile，应用版本固定为 4.0.9。
- PostgreSQL 18.6 和 Redis 8.10.2 使用 Docker Official Images。
- MinerU 官方 Docker 部署说明：<https://opendatalab.github.io/MinerU/zh/quick_start/docker_deployment/>
