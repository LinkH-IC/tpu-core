# firmware/start.S — minimal RISC-V startup
.section .text.init
.global _start
_start:
    call main          # jal-and-link to main
1:  j 1b               # spin forever if main returns
