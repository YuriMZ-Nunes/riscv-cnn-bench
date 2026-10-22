# Regras comuns dos benchmarks de operação (RCB-12).
#
# Uso, no Makefile de benchmarks/<operação>/:
#
#     NAME := <operação>
#     include ../common/kernel.mk
#
# Cada operação tem main.c (parâmetros, dados, ROI, oráculo, verificação),
# kernel.h (assinatura do kernel) e um arquivo por variante do kernel:
#
#     VARIANT=ref     kernel_ref.c     -march=rv64gc   referência escalar
#     VARIANT=custom  kernel_custom.c  -march=rv64gc   instruções personalizadas
#     VARIANT=rvv     kernel_rvv.c     -march=rv64gcv  intrínsecos RVV
#
# A variante custom usa as instruções reais (-DCNN_INSN_HW), que só existem no
# gem5 do fork. CNN_INSN=model troca as instruções pelo modelo em C de
# cnn_insn.h, para validar o kernel no QEMU. A variante rvv desliga a
# autovetorização: o código vetorial é só o dos intrínsecos.

RISCV_PREFIX ?= riscv64-linux-gnu-
CC := $(RISCV_PREFIX)gcc

PROJECT_ROOT := ../..
OUT_DIR := $(PROJECT_ROOT)/build/benchmarks
OUT := $(OUT_DIR)/$(NAME)

# Flags escolhidas pelo experimento (compiler.flags no YAML).
FLAGS ?= -O2

# Variante do kernel (benchmark.variant no YAML).
VARIANT ?= ref
CNN_INSN ?= hw

ifeq ($(VARIANT),ref)
MARCH := rv64gc
VARIANT_FLAGS :=
else ifeq ($(VARIANT),custom)
MARCH := rv64gc
ifeq ($(CNN_INSN),hw)
VARIANT_FLAGS := -DCNN_INSN_HW
else ifeq ($(CNN_INSN),model)
VARIANT_FLAGS :=
else
$(error CNN_INSN inválido: '$(CNN_INSN)'; use hw ou model)
endif
else ifeq ($(VARIANT),rvv)
MARCH := rv64gcv
VARIANT_FLAGS := -fno-tree-vectorize
else
$(error VARIANT inválida: '$(VARIANT)'; use ref, custom ou rvv)
endif

# Flags obrigatórias para executar no gem5 em modo SE, depois das do
# experimento para que o -march da variante prevaleça.
CFLAGS := \
	$(FLAGS) \
	$(VARIANT_FLAGS) \
	-DRCB_VARIANT_NAME='"$(VARIANT)"' \
	-static \
	-march=$(MARCH) \
	-mabi=lp64d \
	-Wall \
	-Wextra \
	-Werror

SRCS := main.c kernel_$(VARIANT).c

.PHONY: all clean

all: $(OUT)

# FORCE recompila sempre, pois FLAGS pode mudar entre experimentos.
$(OUT): $(SRCS) kernel.h $(wildcard *.h ../common/*.h) FORCE
	mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) -o $@ $(SRCS)

FORCE:

clean:
	rm -f $(OUT)
