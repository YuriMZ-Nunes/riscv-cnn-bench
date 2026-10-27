SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

IMAGE ?= localhost/riscv-cnn-bench:dev
CONTAINERFILE ?= Containerfile
GEM5_DIR ?= third_party/gem5
GEM5_BIN ?= $(GEM5_DIR)/build/RISCV/gem5.opt
UV_EXTRA ?= dev
JOBS ?= 4

PODMAN_ARGS ?=
PODMAN_RUN = podman run --rm -it --userns=keep-id \
	-v "$(CURDIR):/workspace:Z" \
	-w /workspace \
	$(PODMAN_ARGS) \
	$(IMAGE)

# Identifica a imagem usada nos metadados de cada execução.
IMAGE_ID = $(shell podman image inspect --format '{{.Id}}' $(IMAGE) 2>/dev/null)

.PHONY: help image image-clean shell check sync lock test lint format format-check \
	gem5-status gem5-build gem5-clean toolchain-check benchmark-build smoke-test \
	clean clean-results status hello-build hello-run hello-run-gem5 e2e-test validate run runs stats compare \
	campaign-plan campaign campaign-status campaign-estimate report plot

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
	$(PODMAN_RUN) bash -lc 'python3 scripts/record-gem5-build.py --gem5 "$(GEM5_BIN)" --repo $(GEM5_DIR)'

gem5-clean: ## Remove os artefatos de build do gem5; não altera o código-fonte.
	$(PODMAN_RUN) bash -lc 'cd $(GEM5_DIR) && scons -c build/RISCV/gem5.opt && rm -f .sconsign.dblite build/RISCV/gem5.opt.build-info.json build/RISCV/gem5.opt.build.diff'

benchmark-build: ## Placeholder para futura compilação de benchmarks RISC-V.
	$(PODMAN_RUN) bash -lc 'echo "Ainda não há benchmarks configurados para build."'

smoke-test: ## Executa CLI, testes, lint e verificação de formato.
	$(PODMAN_RUN) bash -lc 'uv sync --extra $(UV_EXTRA) && uv run riscvcnnbench version && uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests'

e2e-test: ## Testes de ponta a ponta no gem5 (hello_riscv, hello_param_cache, riscvcnnbench run, cnn_insn_semantics, int8_base_example, as sete operações nas três variantes, a leitura do stats.txt nas quatro CPUs, as comparações entre variantes, os cenários de CPU e memória uma campanha pequena com o report em CSV, os gráficos e a estimativa de tempo, e o determinismo do gem5; ~8 min).
	$(PODMAN_RUN) bash -lc 'uv run pytest -m e2e -v'

validate: PODMAN_ARGS += $(if $(RCB_JOBS),-e RCB_JOBS=$(RCB_JOBS))
validate: ## Validação completa antes da campanha: e2e + equivalência das variantes (S e L, dados extremos) no QEMU e no gem5, as três variantes em S nas CPUs timing, minor e o3-edge, e o -O3 do grupo compilador da matriz final. Use RCB_JOBS=N para o paralelismo.
	$(PODMAN_RUN) bash -lc 'uv run pytest -m "e2e or validation" -v'

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

hello-run-gem5: PODMAN_ARGS += -e RCB_IMAGE="$(IMAGE)" -e RCB_IMAGE_ID="$(IMAGE_ID)"
hello-run-gem5: hello-build ## Executa hello_riscv no gem5 e preserva cada execução.
	$(PODMAN_RUN) bash -lc 'python3 scripts/run-gem5.py \
		--gem5 "$(GEM5_BIN)" \
		--binary build/benchmarks/hello_riscv \
		--config configs/gem5/se_riscv.py \
		--results-dir results/hello_riscv'

run: PODMAN_ARGS += -e RCB_IMAGE="$(IMAGE)" -e RCB_IMAGE_ID="$(IMAGE_ID)"
run: ## Executa um experimento YAML: make run EXPERIMENT=experiments/smoke_test.yaml
	@test -n "$(EXPERIMENT)" || { echo "Informe EXPERIMENT=<arquivo.yaml>"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench run "$(EXPERIMENT)" --gem5 "$(GEM5_BIN)"'

runs: ## Lista as execuções, o status e instruções/ciclos/IPC da ROI: make runs [DIR=results/<name>]
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench runs "$(or $(DIR),results)"'

stats: ## Mostra as métricas da ROI de uma execução: make stats RUN=results/<name>/<run_id>
	@test -n "$(RUN)" || { echo "Informe RUN=<pasta da execução>"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench stats "$(RUN)"'

compare: ## Compara execuções aos pares (variantes e -O2 × -O3): make compare [DIR=results/<name>]
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench compare "$(or $(DIR),results)"'

campaign-plan: ## Mostra as combinações de uma campanha: make campaign-plan MATRIX=campaigns/<nome>.yaml
	@test -n "$(MATRIX)" || { echo "Informe MATRIX=campaigns/<nome>.yaml"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench campaign plan "$(MATRIX)"'

campaign: ## Executa ou retoma uma campanha num só container: make campaign MATRIX=campaigns/<nome>.yaml [JOBS=N] [VALIDATE=1]
	@test -n "$(MATRIX)" || { echo "Informe MATRIX=campaigns/<nome>.yaml"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench campaign run "$(MATRIX)" --jobs $(JOBS) $(if $(VALIDATE),--validate)'

campaign-status: ## Estado de cada combinação de uma campanha: make campaign-status MATRIX=campaigns/<nome>.yaml
	@test -n "$(MATRIX)" || { echo "Informe MATRIX=campaigns/<nome>.yaml (ou a pasta da campanha)"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench campaign status "$(MATRIX)"'

campaign-estimate: ## Tempo estimado de uma campanha a partir de execuções medidas: make campaign-estimate MATRIX=campaigns/<nome>.yaml MEASURED="<pastas>" [JOBS=N] [CSV=<arquivo>]
	@test -n "$(MATRIX)" || { echo "Informe MATRIX=campaigns/<nome>.yaml"; exit 2; }
	@test -n "$(MEASURED)" || { echo "Informe MEASURED=\"<pasta> [<pasta>...]\" com execuções medidas"; exit 2; }
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench campaign estimate "$(MATRIX)" $(foreach d,$(MEASURED),-m "$(d)") --jobs $(JOBS) $(if $(CSV),--csv "$(CSV)")'

report: ## Exporta as execuções em CSV (runs.csv e pairs.csv): make report [DIR=results/campaigns/<nome>] [FORCE=1]
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench report "$(or $(DIR),results)" $(if $(FORCE),--force)'

plot: ## Gráficos em PDF e PNG a partir dos CSVs do report: make plot [DIR=results/campaigns/<nome>] [FORCE=1]
	$(PODMAN_RUN) bash -lc 'uv run riscvcnnbench plot "$(or $(DIR),results)" $(if $(FORCE),--force)'
