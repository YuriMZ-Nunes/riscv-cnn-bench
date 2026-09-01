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
    file \
    gdb \
    jq \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir --break-system-packages uv

WORKDIR /workspace

CMD ["/bin/bash"]