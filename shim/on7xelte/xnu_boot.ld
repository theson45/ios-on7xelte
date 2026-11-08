ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.head)) *(.text*) }
    .rodata : { *(.rodata*) }
    .data : { *(.data*) }
    . = ALIGN(4096);
    _image_end = .;
    .bss : { *(.bss*) *(COMMON) }
    . = ALIGN(16);
    _end = .;
    /DISCARD/ : { *(.note*) *(.comment*) }
}
