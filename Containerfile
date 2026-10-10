# Digest fixado para que reconstruções usem a mesma imagem base.
# Para atualizar: podman pull ubuntu:24.04 && podman image inspect --format '{{.Digest}}' ubuntu:24.04
FROM docker.io/library/ubuntu:24.04@sha256:1e0a86e57d247923571b75e0aaf48a1449cf8c543d51fb3e07a4a7d7bfa79316

ARG DEBIAN_FRONTEND=noninteractive
ARG UV_VERSION=0.12.23

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    scons \
    m4 \
    zlib1g \
    zlib1g-dev \
    libprotobuf-dev \
    protobuf-compiler \
    libprotoc-dev \
    libgoogle-perftools-dev \
    libboost-all-dev \
    libhdf5-serial-dev \
    libcapstone-dev \
    libpng-dev \
    libelf-dev \
    pkg-config \
    cmake \
    ninja-build \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv \
    python3-tk \
    python3-pydot \
    python3-yaml \
    python3-pandas \
    python3-matplotlib \
    python3-pytest \
    gcc-riscv64-linux-gnu=4:13.2.0-7ubuntu1 \
    g++-riscv64-linux-gnu=4:13.2.0-7ubuntu1 \
    binutils-riscv64-linux-gnu=2.42-4ubuntu2.10 \
    libc6-dev-riscv64-cross=2.39-0ubuntu8cross1 \
    qemu-user=1:8.2.2+ds-0ubuntu1.18 \
    file \
    gdb \
    jq \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/${UV_VERSION}/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && uv --version

WORKDIR /workspace

CMD ["/bin/bash"]