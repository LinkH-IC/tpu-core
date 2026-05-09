TOOLCHAIN := riscv64-unknown-elf-
CC        := $(TOOLCHAIN)gcc
OBJCOPY   := $(TOOLCHAIN)objcopy

CFLAGS    := -march=rv32i -mabi=ilp32 -O1 \
             -ffreestanding -nostdlib -Wall -Wextra
LDFLAGS   := -T linker.ld -nostartfiles

SRCS      := start.S $(wildcard *.c)

all: firmware.hex

firmware.elf: $(SRCS) linker.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(SRCS) -lgcc

firmware.bin: firmware.elf
	$(OBJCOPY) -O binary $< $@

firmware.hex: firmware.bin
	hexdump -v -e '1/4 "%08x\n"' $< > $@

clean:
	rm -f firmware.elf firmware.bin firmware.hex

.PHONY: all clean
