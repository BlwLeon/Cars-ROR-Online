ENTRY(hook_pad_read)
SECTIONS {
  . = 0x02114800;
  .load : {
    KEEP(*(.dbg))
    . = ALIGN(4);
    KEEP(*(.dbg2))
    . = ALIGN(4);
    KEEP(*(.cfg))
    . = ALIGN(4);
    *(.text .text.*)
    *(.rodata .rodata.*)
    *(.data .data.*)
    . = ALIGN(32);
  }
  __load_end = .;
  .bss (NOLOAD) : { *(.bss .bss.* COMMON) . = ALIGN(32); *(.logbss) . = ALIGN(32); }
  __bss_end = .;
  /DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes) *(.comment) }
}
