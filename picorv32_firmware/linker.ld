ENTRY(_start)

MEMORY
{
    RAM (rwx) : ORIGIN = 0x00000000, LENGTH = 0x20000   /* 128 KB */
}

SECTIONS
{
    .text   : { *(.text.init) *(.text*)    } > RAM
    .rodata : { *(.rodata*)                } > RAM
    .data   : { *(.data*)                  } > RAM
    .bss    : { *(.bss*) *(COMMON)         } > RAM
}
