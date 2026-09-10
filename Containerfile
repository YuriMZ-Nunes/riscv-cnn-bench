FROM docker.io/library/ubuntu:24.04

ARG DEBIAN_FRONTEND=noninteractive

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
    gcc-riscv64-linux-gnu \
    g++-riscv64-linux-gnu \
    binutils-riscv64-linux-gnu \
    libc6-dev-riscv64-cross \
    qemu-user \
    file \
    gdb \
    jq \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx \
    && uv --version

WORKDIR /workspace

CMD ["/bin/bash"]