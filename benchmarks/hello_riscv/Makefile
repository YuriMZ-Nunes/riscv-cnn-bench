RISCV_PREFIX ?= riscv64-linux-gnu-
CC := $(RISCV_PREFIX)gcc

PROJECT_ROOT := ../..
OUT_DIR := $(PROJECT_ROOT)/build/benchmarks
OUT := $(OUT_DIR)/hello_riscv

CFLAGS := \
	-O2 \
	-static \
	-march=rv64gc \
	-mabi=lp64d \
	-Wall \
	-Wextra \
	-Werror

.PHONY: all clean

all: $(OUT)

$(OUT): main.c
	mkdir -p $(OUT_DIR)
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -f $(OUT)