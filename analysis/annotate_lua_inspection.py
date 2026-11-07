"""Add stock LuaJIT opcode labels and known constants to the existing read-only inspection output."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OPS = ('ISLT ISGE ISLE ISGT ISEQV ISNEV ISEQS ISNES ISEQN ISNEN ISEQP ISNEP ISTC ISFC IST ISF ISTYPE ISNUM '
       'MOV NOT UNM LEN ADDVN SUBVN MULVN DIVVN MODVN ADDNV SUBNV MULNV DIVNV MODNV ADDVV SUBVV MULVV '
       'DIVVV MODVV POW CAT KSTR KCDATA KSHORT KNUM KPRI KNIL UGET USETV USETS USETN USETP UCLO FNEW '
       'TNEW TDUP GGET GSET TGETV TGETS TGETB TGETR TSETV TSETS TSETB TSETM TSETR CALLM CALL CALLMT '
       'CALLT ITERC ITERN VARG ISNEXT RETM RET RET0 RET1 FORI JFORI FORL IFORL JFORL ITERL IITERL '
       'JITERL LOOP ILOOP JLOOP JMP FUNCF IFUNCF JFUNCF FUNCV IFUNCV JFUNCV FUNCC FUNCCW').split()


def annotate(text):
    """Resolve only printed constants; opcode labels explain observations without executing game code."""
    out = []
    constants, numbers, upvalues = {}, {}, {}
    for line in text.splitlines():
        if line.startswith('FUNCTION '):
            constants, numbers, upvalues = {}, {}, {}
            out.append('\n' + line)
        elif match := re.match(r'K (-\d+) (.*)', line):
            constants[-int(match[1]) - 1] = match[2]
        elif match := re.match(r'N (\d+) (.*)', line):
            numbers[int(match[1])] = match[2]
        elif match := re.match(r'UP (\d+) (\S+) (.*)', line):
            upvalues[int(match[1]) - 1] = match[2]
        elif match := re.match(r'BC (\d+) OP=(\d+) A=(\d+) B=(\d+) C=(\d+) D=(\d+)', line):
            pc, op, a, b, c, d = map(int, match.groups())
            name = OPS[op] if op < len(OPS) else str(op)
            note = ''
            if name in ('GGET', 'GSET', 'KSTR'):
                note = constants.get(d, '?')
            elif name in ('TGETS', 'TSETS'):
                note = constants.get(c, '?')
            elif name == 'UGET':
                note = upvalues.get(d, '?')
            elif name in ('ISEQN', 'ISNEN', 'KNUM'):
                note = numbers.get(d, '?')
            elif name in ('ADDVN', 'SUBVN', 'MULVN', 'DIVVN', 'MODVN'):
                note = numbers.get(c, '?')
            elif name in ('JMP', 'FORI', 'FORL', 'ITERL', 'UCLO'):
                note = '->' + str(pc + 1 + d - 32768)
            elif name == 'KSHORT':
                note = str(d if d < 32768 else d - 65536)
            out.append(f'{pc:04} {name:7} A={a} B={b} C={c} D={d} {note}')
    return '\n'.join(out)


if __name__ == '__main__':
    source = ROOT / 'evidence/dispatch-selection-algorithm.txt'
    target = ROOT / 'evidence/dispatch-selection-annotated.txt'
    target.write_text(annotate(source.read_text(encoding='utf-8')), encoding='utf-8')
    print(target)
