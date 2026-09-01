#!/usr/bin/env python3
"""Tiny 6502 disassembler: disassemble a raw overlay image from a given address."""
import sys

M_IMP, M_IMM, M_ZP, M_ZPX, M_ZPY, M_ABS, M_ABX, M_ABY, M_IND, M_IZX, M_IZY, M_REL, M_ACC = range(13)
SZ = {
    M_IMP: 1, M_ACC: 1, M_IMM: 2, M_ZP: 2, M_ZPX: 2, M_ZPY: 2, M_REL: 2, M_IZX: 2, M_IZY: 2,
    M_ABS: 3, M_ABX: 3, M_ABY: 3, M_IND: 3,
}
T = {}
tab = """
00 BRK IMP;01 ORA IZX;05 ORA ZP;06 ASL ZP;08 PHP IMP;09 ORA IMM;0A ASL ACC;0D ORA ABS;0E ASL ABS
10 BPL REL;11 ORA IZY;15 ORA ZPX;16 ASL ZPX;18 CLC IMP;19 ORA ABY;1D ORA ABX;1E ASL ABX
20 JSR ABS;21 AND IZX;24 BIT ZP;25 AND ZP;26 ROL ZP;28 PLP IMP;29 AND IMM;2A ROL ACC;2C BIT ABS;2D AND ABS;2E ROL ABS
30 BMI REL;31 AND IZY;35 AND ZPX;36 ROL ZPX;38 SEC IMP;39 AND ABY;3D AND ABX;3E ROL ABX
40 RTI IMP;41 EOR IZX;45 EOR ZP;46 LSR ZP;48 PHA IMP;49 EOR IMM;4A LSR ACC;4C JMP ABS;4D EOR ABS;4E LSR ABS
50 BVC REL;51 EOR IZY;55 EOR ZPX;56 LSR ZPX;58 CLI IMP;59 EOR ABY;5D EOR ABX;5E LSR ABX
60 RTS IMP;61 ADC IZX;65 ADC ZP;66 ROR ZP;68 PLA IMP;69 ADC IMM;6A ROR ACC;6C JMP IND;6D ADC ABS;6E ROR ABS
70 BVS REL;71 ADC IZY;75 ADC ZPX;76 ROR ZPX;78 SEI IMP;79 ADC ABY;7D ADC ABX;7E ROR ABX
81 STA IZX;84 STY ZP;85 STA ZP;86 STX ZP;88 DEY IMP;8A TXA IMP;8C STY ABS;8D STA ABS;8E STX ABS
90 BCC REL;91 STA IZY;94 STY ZPX;95 STA ZPX;96 STX ZPY;98 TYA IMP;99 STA ABY;9A TXS IMP;9D STA ABX
A0 LDY IMM;A1 LDA IZX;A2 LDX IMM;A4 LDY ZP;A5 LDA ZP;A6 LDX ZP;A8 TAY IMP;A9 LDA IMM;AA TAX IMP;AC LDY ABS;AD LDA ABS;AE LDX ABS
B0 BCS REL;B1 LDA IZY;B4 LDY ZPX;B5 LDA ZPX;B6 LDX ZPY;B8 CLV IMP;B9 LDA ABY;BA TSX IMP;BC LDY ABX;BD LDA ABX;BE LDX ABY
C0 CPY IMM;C1 CMP IZX;C4 CPY ZP;C5 CMP ZP;C6 DEC ZP;C8 INY IMP;C9 CMP IMM;CA DEX IMP;CC CPY ABS;CD CMP ABS;CE DEC ABS
D0 BNE REL;D1 CMP IZY;D5 CMP ZPX;D6 DEC ZPX;D8 CLD IMP;D9 CMP ABY;DD CMP ABX;DE DEC ABX
E0 CPX IMM;E1 SBC IZX;E4 CPX ZP;E5 SBC ZP;E6 INC ZP;E8 INX IMP;E9 SBC IMM;EA NOP IMP;EC CPX ABS;ED SBC ABS;EE INC ABS
F0 BEQ REL;F1 SBC IZY;F5 SBC ZPX;F6 SBC ZPX;F8 SED IMP;F9 SBC ABY;FD SBC ABX;FE INC ABX
"""
MODES = dict(
    IMP=M_IMP, IMM=M_IMM, ZP=M_ZP, ZPX=M_ZPX, ZPY=M_ZPY, ABS=M_ABS, ABX=M_ABX, ABY=M_ABY,
    IND=M_IND, IZX=M_IZX, IZY=M_IZY, REL=M_REL, ACC=M_ACC,
)
for ent in tab.replace("\n", ";").split(";"):
    ent = ent.strip()
    if not ent:
        continue
    o, mn, md = ent.split()
    T[int(o, 16)] = (mn, MODES[md])


def fmt(pc, mn, mode, b):
    if mode == M_IMP:
        return mn
    if mode == M_ACC:
        return mn + " A"
    if mode == M_IMM:
        return f"{mn} #${b[1]:02X}"
    if mode == M_ZP:
        return f"{mn} ${b[1]:02X}"
    if mode == M_ZPX:
        return f"{mn} ${b[1]:02X},X"
    if mode == M_ZPY:
        return f"{mn} ${b[1]:02X},Y"
    if mode == M_IZX:
        return f"{mn} (${b[1]:02X},X)"
    if mode == M_IZY:
        return f"{mn} (${b[1]:02X}),Y"
    if mode == M_REL:
        off = b[1] - 256 if b[1] > 127 else b[1]
        return f"{mn} ${pc + 2 + off:04X}"
    a = b[1] | (b[2] << 8)
    if mode == M_ABS:
        return f"{mn} ${a:04X}"
    if mode == M_ABX:
        return f"{mn} ${a:04X},X"
    if mode == M_ABY:
        return f"{mn} ${a:04X},Y"
    if mode == M_IND:
        return f"{mn} (${a:04X})"
    return None


def run(path, base, start, count):
    with open(path, "rb") as f:
        data = f.read()
    pc = start
    for _ in range(count):
        i = pc - base
        if i < 0 or i >= len(data):
            break
        op = data[i]
        if op not in T:
            print(f"${pc:04X}  {op:02X}           .byte ${op:02X}")
            pc += 1
            continue
        mn, mode = T[op]
        n = SZ[mode]
        b = data[i:i + n]
        if len(b) < n:
            break
        print(f"${pc:04X}  {' '.join(f'{x:02X}' for x in b):<9s}  {fmt(pc, mn, mode, b)}")
        pc += n


if __name__ == "__main__":
    path, base, start, count = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16), int(sys.argv[4])
    run(path, base, start, count)
