"""Second validation direction: atoms hand-built from the spec (build2.py, build3.py)
were written into the original DLL; compare what the DLL read back (out2.txt,
out3.txt) with what memfmt decodes from the same bytes."""
import re, sys
sys.path.insert(0, '../..')
from dpcreader import memfmt as m
import build2, build3
ok = True
def expect(what, got, want):
    global ok
    good = got == want; ok &= good
    print(('PASS ' if good else 'FAIL ') + what + ('' if good else f'\n   dll    {got!r}\n   memfmt {want!r}'))
lines = [l.strip() for f in ('out2.txt', 'out3.txt') for l in open(f, errors='replace')]
get = lambda prefix: [l for l in lines if l.startswith(prefix)]
kv = lambda l: dict(re.findall(r'(\w+)=(\[[^\]]*\]|\S+)', l))
addr = lambda a: f"{a.memlist},{a.group},{a.atom}"
D = {t: m.decode_atom(1, t, b) for t, b in build2.atoms.items()}
r = kv(get('R4 ')[0]); d = D[4]
expect('summary strategy addr', r['first'], addr(d['strategy']))
expect('summary state addr', r['second'], addr(d['state']))
expect('summary n / b0 / b1 / srcd', (r['n'], r['p11'], r['p12'], r['p13']), (str(len(d['results'])), str(d['b0']), str(d['b1']), str(d['srcd'])))
expect('summary step atoms', [kv(l)['addr'].split(',')[2] for l in get('R4STEP')], [str(x) for x in d['results']])
r = kv(get('R8 ')[0]); d = D[8]
expect('prompt result', (r['defn'], float(r['value'])), (addr(d['definition']), d['value']))
r = [kv(l) for l in get('R14 ')]; d = D[14]
expect('list result', (r[0]['list'], r[0]['count']), (addr(d['list']), str(len(d['selected']))))
r = kv(get('R17 ')[0]); d = D[17]
expect('switch result', {r['a'], r['b']}, {addr(d['ref1']), addr(d['ref2'])})
r = kv(get('R18 ')[0]); d = D[18]['result_group']
expect('task result ref', (r['list'], r['group']), (str(d['memlist']), str(d['group'])))
st = m.decode_atom(1, 3, build3.state)
expect('state fully consumed', 'trailing' in st, False)
B = {(l['list'], b['id']): b for l in st['lists'] for b in l['buckets']}
S = {l.split()[1]: kv(l) for l in get('S ')}
expect('state lists', S['restore']['nlists'], str(len(st['lists'])))
expect('meas.value', float(S['meas.value']['v']), round(B[2, 18]['fields'][0], 3))
expect('meas.big (2-byte id)', float(S['meas.big']['v']), B[2, 200]['fields'][0])
expect('meas.count', int(S['meas.count']['v']), B[2, 19]['fields'][0])
expect('meas.label', S['meas.label']['v'], '[' + B[2, 20]['fields'][0] + ']')
expect('src.mode', int(S['src.mode']['v']), B[5, 3]['fields'][0])
rg = B[2, 21]['range']; r = S['range']
expect('ranged value', float(S['meas.ranged']['v']), B[2, 21]['value'])
expect('range floats', (float(r['e513']), float(r['e521']), float(r['e530'])), (rg['f0'], rg['f1'], rg['f3']))
expect('range small fields', (int(r['b2']), int(r['hi']), int(r['lo']), int(r['x4']), int(r['flag'])), (rg['b2'], rg['hi'], rg['lo'], rg['x4'], rg['flag']))
print('\nALL MATCH' if ok else '\nMISMATCHES'); sys.exit(0 if ok else 1)
