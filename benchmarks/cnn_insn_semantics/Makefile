RISCV_PREFIX ?= riscv64-linux-gnu-
CC := $(RISCV_PREFIX)gcc

PROJECT_ROOT := ../..
OUT_DIR := $(PROJECT_ROOT)/build/benchmarks
OUT := $(OUT_DIR)/cnn_insn_semantics

# Flags escolhidas pelo experimento (compiler.flags no YAML).
# -DCNN_INSN_HW emite as instruções personalizadas reais (só no gem5 do fork).
FLAGS ?= -O2

# Flags obrigatórias para executar no gem5 em modo SE.
CFLAGS := \
	$(FLAGS) \
	-static \
	-march=rv64gc \
	-mabi=lp64d \
	-Wall \
	-Wextra \
	-Werror

.PHONY: all clean

all: $(OUT)

# FORCE recompila sempre, pois FLAGS pode mudar entre experimentos.
$(OUT): main.c ../common/cnn_insn.h FORCE
	mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) -o $@ $<

FORCE:

clean:
	rm -f $(OUT)
