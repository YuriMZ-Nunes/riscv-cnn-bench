IMAGE ?= localhost/riscv-cnn-bench:dev

CONTAINER_RUN = podman run --rm -it \
	--userns=keep-id \
	-v "$(CURDIR):/workspace:Z" \
	-w /workspace \
	$(IMAGE)

container-build:
	podman build -t $(IMAGE) -f Containerfile .

shell:
	$(CONTAINER_RUN) bash

test:
	$(CONTAINER_RUN) pytest -q

build-gem5:
	$(CONTAINER_RUN) bash scripts/setup-gem5.sh

build-benchmarks:
	$(CONTAINER_RUN) bash scripts/build-benchmarks.sh

smoke-test:
	$(CONTAINER_RUN) riscvcnnbench run experiments/smoke_test.yaml

report:
	$(CONTAINER_RUN) riscvcnnbench report results/