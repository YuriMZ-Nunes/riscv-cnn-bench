# Regras comuns dos benchmarks de operação (RCB-12).
#
# Uso, no Makefile de benchmarks/<operação>/:
#
#     NAME := <operação>
#     include ../common/kernel.mk
#
# Cada operação tem main.c (parâmetros, dados, ROI, oráculo, verificação),
# kernel.h (assinatura do kernel) e kernel_ref.c (kernel de referência). As
# variantes da RCB-14 trocam só o arquivo do kernel.

RISCV_PREFIX ?= riscv64-linux-gnu-
CC := $(RISCV_PREFIX)gcc

PROJECT_ROOT := ../..
OUT_DIR := $(PROJECT_ROOT)/build/benchmarks
OUT := $(OUT_DIR)/$(NAME)

# Flags escolhidas pelo experimento (compiler.flags no YAML).
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

SRCS := main.c kernel_ref.c

.PHONY: all clean

all: $(OUT)

# FORCE recompila sempre, pois FLAGS pode mudar entre experimentos.
$(OUT): $(SRCS) kernel.h $(wildcard ../common/*.h) FORCE
	mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) -o $@ $(SRCS)

FORCE:

clean:
	rm -f $(OUT)
