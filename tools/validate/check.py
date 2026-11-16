"""Decode the atoms the original dpclnk3.dll produced (out.txt) with memfmt and
compare against the values gen.ps1 passed in."""
import sys, json
sys.path.insert(0, '../..')
from dpcreader import memfmt as m
atoms = {}
for line in open('out.txt', encoding='utf-8', errors='replace'):
    if line.startswith('ATOM'):
        p = line.split()
        atoms[int(p[5])] = (bytes.fromhex(p[-1]), int(p[4]), int(p[6]))
ok = True
def expect(what, got, want):
    global ok
    good = got == want
    ok &= good
    print(('PASS ' if good else 'FAIL ') + what + ('' if good else f'\n   got  {got!r}\n   want {want!r}'))
dec = {t: m.decode_atom(v, t, raw, ver) for t, (raw, v, ver) in atoms.items()}
for t, d in dec.items():
    expect(f'type {t} ({d["kind"]}) fully consumed', 'trailing' in d, False)
d = dec[9];  expect('task_start', (d['name'], d['number'], d['text']), ('PT-101 cal', 0, 'Loop check'))
d = dec[10]; expect('strategy', (d['name'], d['items']), ('5pt up', [0, 2500, 5000, 7500, 10000]))
d = dec[12]; expect('list_definition', (d['name'], d['items']), ('Condition', ['Good', 'Bad', 'Needs, repair']))
d = dec[5];  expect('strategy_ref', (d['state'], d['strategy'], d['b0'], d['b1'], d['srcd'], d['text1'], d['text2']),
                    (m.AtomAddr(1, 0, 1), m.AtomAddr(1, 0, 1), 1, 2, 0x01020304, 'viewA', 'viewB'))
d = dec[6];  expect('prompt_definition', (d['text'], d['b0'], d['b1'], d['b2'], d['text2']), ('Enter ambient temp', 2, 0, 1, 'degC'))
import struct
f32 = lambda x: struct.unpack('>f', struct.pack('>f', x))[0]
sets = [(a['id'], a['value']) for o in dec[2]['ops'] for a in o['args']]
expect('state_setup values', sets,
       [(0, 2), (18, f32(4.002)), (18, 0.0), (18, 20.0), (200, -1.5), (19, 5), (19, -200), (19, 70000), (0, 5), (3, 300), (0, 2)])
expect('state_setup op codes', [o['op'] for o in dec[2]['ops']], [1] + [2] * 11 + [4])
print('\nALL MATCH' if ok else '\nMISMATCHES')
sys.exit(0 if ok else 1)
