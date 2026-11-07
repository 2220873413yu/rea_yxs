"""Read a derived v24.1 metadata view; never execute or modify the APK.

The version is inferred from Unity 2018.4, the 272-byte header and table widths.
The source's protected first bytes are not recovered by this transformation.
"""
import json
import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent
raw = (ROOT / 'extracted/global-metadata.dat').read_bytes()
data = bytearray(raw)
for offset in range(len(data)):
    if offset < 0x1000 or 0x1000 <= offset % 0x10000 < 0x5000:
        data[offset] ^= 0x66
data[:8] = struct.pack('<II', 0xFAB11BAF, 24)
(ROOT / 'extracted/global-metadata.candidate-v24.1.dat').write_bytes(data)
sections = [struct.unpack_from('<II', data, 8 + index * 8) for index in range(33)]
string_offset, string_size = sections[2]


def read_name(index):
    """Read a bounded UTF-8 metadata identifier; invalid offsets fail the analysis."""
    assert 0 <= index < string_size, index
    start = string_offset + index
    return data[start:data.index(0, start, string_offset + string_size)].decode('utf-8')


method_offset, method_size = sections[5]
type_offset, type_size = sections[19]
parameter_offset, parameter_size = sections[10]
assert method_size % 52 == type_size % 100 == parameter_size % 12 == 0
types = []
for index in range(type_size // 100):
    row = struct.unpack_from('<19i8H2I', data, type_offset + index * 100)
    types.append(dict(index=index, name=read_name(row[0]), namespace=read_name(row[1]),
                      method_start=row[12], method_count=row[19]))
methods = []
for index in range(method_size // 52):
    row = struct.unpack_from('<11i4H', data, method_offset + index * 52)
    assert row[10] >> 24 == 6, index
    assert 0 <= row[1] < len(types), index
    owner = types[row[1]]
    parameters = []
    for relative in range(row[14]):
        parameter_index = row[3] + relative
        assert 0 <= parameter_index < parameter_size // 12
        name, token, type_index = struct.unpack_from('<III', data, parameter_offset + parameter_index * 12)
        assert token >> 24 == 8
        parameters.append(dict(name=read_name(name), type_index=type_index))
    methods.append(dict(index=index, name=read_name(row[0]), declaring_type=row[1],
                        owner=(owner['namespace'] + '.' if owner['namespace'] else '') + owner['name'],
                        method_index=row[5], parameters=parameters, return_type=row[2]))
owner_mismatches = []
for owner in types:
    start, count = owner['method_start'], owner['method_count']
    if count and any(method['declaring_type'] != owner['index'] for method in methods[start:start + count]):
        owner_mismatches.append(owner)
for name, value in [('metadata-custom-methods.json', methods), ('metadata-custom-types.json', types),
                    ('metadata-custom-owner-mismatches.json', owner_mismatches)]:
    (ROOT / 'evidence' / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
print('Parsed', len(types), 'types and', len(methods), 'methods;', len(owner_mismatches), 'owner-range anomalies')
print('Maximum native method index:', max(method['method_index'] for method in methods))
for method in methods:
    if re.search(r'TKUtil|AssetBundleLuaLoader|SocketConnection|TCP_Client|GameNetwork|NetWork', method['owner']):
        if re.search(r'Load|Lua|Decrypt|Encrypt|Send|Connect|Receive|Read', method['name'], re.I):
            print(json.dumps(method, ensure_ascii=False))
