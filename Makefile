SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

IMAGE ?= localhost/riscv-cnn-bench:dev
CONTAINERFILE ?= Containerfile
GEM5_DIR ?= third_party/gem5
GEM5_BIN ?= $(GEM5_DIR)/build/RISCV/gem5.opt
UV_EXTRA ?= dev
JOBS ?= 4

PODMAN_RUN = podman run --rm -it --userns=keep-id \
	-v "$(CURDIR):/workspace:Z" \
	-w /workspace \
	$(IMAGE)

.PHONY: help image image-clean shell check sync lock test lint format format-check \
	gem5-status gem5-build gem5-clean toolchain-check benchmark-build smoke-test \
	clean clean-results status hello-build hello-run

help: ## Mostra os comandos disponíveis.
	@awk 'BEGIN {FS = ":.*##"}; /^[a-zA-Z0-9_-]+:.*##/ {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

image: ## Constrói a imagem de desenvolvimento do container.
	podman build -t $(IMAGE) -f $(CONTAINERFILE) .

image-clean: ## Remove a imagem local do projeto (não remove código nem resultados).
	podman rmi $(IMAGE)

shell: ## Abre um shell Bash dentro do container, na raiz do projeto.
	$(PODMAN_RUN) bash

check: ## Exibe versões de ferramentas disponíveis no container.
	$(PODMAN_RUN) bash -lc 'uname -m; python3 --version; uv --version; scons --version; git --version'

lock: ## Resolve dependências e atualiza o uv.lock.
	$(PODMAN_RUN) bash -lc 'uv lock'

sync: ## Cria/sincroniza .venv com dependências de desenvolvimento.
	$(PODMAN_RUN) bash -lc 'uv sync --extra $(UV_EXTRA)'

test: ## Executa os testes Python.
	$(PODMAN_RUN) bash -lc 'uv run pytest -q'

lint: ## Executa o linter somente no código do projeto.
	$(PODMAN_RUN) bash -lc 'uv run ruff check src tests'

format-check: ## Verifica formatação Python sem alterar arquivos.
	$(PODMAN_RUN) bash -lc 'uv run ruff format --check src tests'

format: ## Formata somente src/ e tests/; não toca no submódulo gem5.
	$(PODMAN_RUN) bash -lc 'uv run ruff format src tests && uv run ruff check --fix src tests'

gem5-status: ## Exibe o estado Git do submódulo gem5.
	@git -C $(GEM5_DIR) status --short

gem5-build: ## Compila o gem5 otimizado com suporte a RISC-V. Use JOBS=N para ajustar paralelismo.
	$(PODMAN_RUN) bash -lc 'cd $(GEM5_DIR) && scons build/RISCV/gem5.opt -j$(JOBS)'

gem5-clean: ## Remove os artefatos de build do gem5; não altera o código-fonte.
	$(PODMAN_RUN) bash -lc 'cd $(GEM5_DIR) && scons -c build/RISCV/gem5.opt && rm -f .sconsign.dblite'

benchmark-build: ## Placeholder para futura compilação de benchmarks RISC-V.
	$(PODMAN_RUN) bash -lc 'echo "Ainda não há benchmarks configurados para build."'

smoke-test: ## Executa CLI, testes, lint e verificação de formato.
	$(PODMAN_RUN) bash -lc 'uv sync --extra $(UV_EXTRA) && uv run riscvcnnbench version && uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests'

clean-results: ## Remove resultados gerados pelo framework.
	rm -rf results/*

clean: ## Remove ambientes e artefatos locais do framework; preserva fontes do gem5.
	rm -rf .venv .pytest_cache .ruff_cache
	rm -rf src/*.egg-info riscv_cnn_bench.egg-info
	rm -rf build/* results/* m5out

status: ## Exibe estado do repositório principal e do submódulo gem5.
	@git status --short
	@echo
	@echo "--- gem5 ---"
	@git -C $(GEM5_DIR) status --short

toolchain-check: ## Mostra versões e caminhos da toolchain RISC-V Linux.
	$(PODMAN_RUN) bash -lc '\
		which riscv64-linux-gnu-gcc && \
		riscv64-linux-gnu-gcc --version && \
		which riscv64-linux-gnu-g++ && \
		riscv64-linux-gnu-g++ --version && \
		which riscv64-linux-gnu-objdump && \
		riscv64-linux-gnu-objdump --version | head -n 1 \
	'

hello-build: ## Compila o benchmark RISC-V hello_riscv.
	$(PODMAN_RUN) bash -lc '$(MAKE) -C benchmarks/hello_riscv'

hello-run: ## Executa o benchmark RISC-V hello_riscv com o QEMU.
	$(PODMAN_RUN) bash -lc 'qemu-riscv64 build/benchmarks/hello_riscv'

hello-run-gem5: hello-build ## Executa hello_riscv no gem5 em modo SE.
	$(PODMAN_RUN) bash -lc '$(GEM5_BIN) --outdir=results/hello_riscv configs/gem5/se_riscv.py --binary build/benchmarks/hello_riscv'