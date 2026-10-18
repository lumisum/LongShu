# Based on the official MinerU 4.0.9 China GPU Dockerfile.
# https://github.com/opendatalab/MinerU/blob/mineru-4.0.9-released/docker/china/Dockerfile
FROM docker.m.daocloud.io/vllm/vllm-openai:v0.21.0

RUN apt-get update && \
    apt-get install -y --no-install-recommends libgl1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Pin MinerU so rebuilding this image keeps the same application version.
RUN python3 -m pip install -U 'mineru[torch]==4.0.9' \
      -i https://mirrors.aliyun.com/pypi/simple \
      --break-system-packages && \
    python3 -m pip cache purge

ENV MINERU_MODEL_SMALL_BACKEND=torch \
    MINERU_MODEL_VLM_ENGINE=vllm

# Download the standard tier models at build time from ModelScope.
RUN /bin/bash -c "mineru-kit models download --tier standard --small-backend torch --vlm-engine vllm -s modelscope"

ENTRYPOINT ["/bin/bash", "-c", "export MINERU_MODEL_SOURCE=local && exec \"$@\"", "--"]
