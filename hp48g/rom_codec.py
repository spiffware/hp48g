"""HP 48 character encoding and binary-object framing (no program evaluation)."""
from decimal import Decimal
import re

SPECIAL = dict(zip('∠x∇√∫Σ▶π∂≤≥≠α→←↓↑γδεηθλρστ ωΔΠΩ■∞'.replace(' ',''),range(128,160)))
# Code 129 is x-bar, not the Latin letter x.
SPECIAL.pop('x',None); SPECIAL['x̄']=129
ESCAPES = ['<)','x-','.V','v/','.S','GS','|>','pi','.d','<=','>=','=/','Ga','->','<-','|v','|^',
           'Gg','Gd','Ge','Gn','Gh','Gl','Gr','Gs','Gt','Gw','GD','PI','GW','[]','oo']
ESCAPE_CODES = {v:i+128 for i,v in enumerate(ESCAPES)}
ESCAPE_CODES.update({'<<':171,'>>':187,'^o':176,'Gm':181})
REVERSE_SPECIAL = {v:k for k,v in SPECIAL.items()}
MAX_NIBBLES=589824  # Largest supported heap: SX with two merged 128 KB cards.


def encode_text(source,transfer_escapes=True):
    """Accept Unicode HP symbols and the documented ASCII transfer escapes."""
    source=source.replace('\r\n','\n').replace('\r','\n')
    if transfer_escapes:
        def escape(match):
            text=match.group(1)
            code=int(text) if text.isdecimal() else ESCAPE_CODES[text]
            if not 0<=code<=255: raise ValueError('HP character escape must be 000–255')
            return chr(code)
        pattern=r'\\('+'|'.join(re.escape(v) for v in ESCAPE_CODES)+r'|\d{3})'
        source=re.sub(pattern,escape,source)
    for char,code in sorted(SPECIAL.items(),key=lambda pair:-len(pair[0])): source=source.replace(char,chr(code))
    try: return source.encode('latin-1')
    except UnicodeEncodeError as exc: raise ValueError(f'The character {source[exc.start]!r} is not in the HP 48 character set') from exc


def decode_text(data):
    return ''.join(REVERSE_SPECIAL.get(value,chr(value)) for value in data)


def number_nibbles(value,count=5):
    if not 0<=value<16**count: raise ValueError('Object field out of range')
    return ''.join(format((value>>(4*i))&15,'x') for i in range(count))


def to_nibbles(data): return ''.join(number_nibbles(value,2) for value in data)


def from_nibbles(nibbles):
    if any(c not in '0123456789abcdef' for c in nibbles): raise ValueError('Invalid nibble data')
    nibbles+='0'*(len(nibbles)%2)
    return bytes(int(nibbles[i+1]+nibbles[i],16) for i in range(0,len(nibbles),2))


def string_object(source):
    data=encode_text(source)
    if len(data)*2+10>MAX_NIBBLES: raise ValueError('Text exceeds calculator memory capacity')
    return number_nibbles(0x2a2c)+number_nibbles(len(data)*2+5)+to_nibbles(data)


def execution_object(source):
    """Revision R program: « <HP string> STR→ »; parsing runs in HP's ROM.

    The three routine addresses were obtained by compiling « STR→ » on the
    revision R ROM and exporting the resulting native program object.
    """
    return (number_nibbles(0x2d9d)+number_nibbles(0x2361e)+string_object(source)+
            number_nibbles(0x1cb26)+number_nibbles(0x23639)+number_nibbles(0x312b))


def object_size(nibbles,start=0,depth=0):
    """Validate length fields before transferring an HP object into RAM."""
    if len(nibbles)>MAX_NIBBLES+1 or depth>100: raise ValueError('HP object exceeds size or nesting limits')
    def field(offset,count=5):
        text=nibbles[offset:offset+count]
        if len(text)!=count or any(c not in '0123456789abcdef' for c in text): raise ValueError('Truncated or invalid HP object')
        return int(text[::-1],16)
    prolog=field(start)
    fixed={0x2911:10,0x2933:21,0x2955:26,0x2977:37,0x299d:47,0x29bf:7,0x2baa:15,0x2e92:11}
    if prolog in fixed: size=fixed[prolog]
    elif prolog in (0x2e48,0x2e6d,0x2afc):
        size=7+2*field(start+5,2)
        if prolog==0x2afc: size+=object_size(nibbles,start+size,depth+1)
    elif prolog in (0x2a74,0x2ab8,0x2ada,0x2d9d):
        size=5
        while field(start+size)!=0x312b: size+=object_size(nibbles,start+size,depth+1)
        size+=5
    elif prolog==0x2a96:
        offset=field(start+8)
        if offset==0: size=13
        else:
            size=8+offset;size+=field(start+size,2)*2+4
            size+=object_size(nibbles,start+size,depth+1)
    elif prolog in (0x29e8,0x2a0a,0x2a2c,0x2a4e,0x2b1e,0x2b40,0x2b62,0x2b88,0x2bcc,0x2bee,0x2c10,0x2dcc):
        size=5+field(start+5)
        if size<10: raise ValueError('Invalid HP object length')
    else: size=5 # ROM entry/primitive pointer inside a program.
    if start+size>len(nibbles): raise ValueError('Truncated HP object')
    return size


def import_binary(data):
    if not data.startswith(b'HPHP48-') or len(data)<11: raise ValueError('Expected an HPHP48 binary object')
    if len(data)>MAX_NIBBLES//2+9: raise ValueError('HP object is too large')
    nibbles=to_nibbles(data[8:]);size=object_size(nibbles)
    if len(nibbles)-size not in (0,1): raise ValueError('Trailing data after the HP object')
    return nibbles[:size]


def export_binary(nibbles):
    if object_size(nibbles)!=len(nibbles): raise ValueError('Trailing data after HP object')
    return b'HPHP48-R'+from_nibbles(nibbles)


def decode_real(nibbles):
    """Decode the native 12-digit BCD value for tests and stack transfer."""
    if len(nibbles)!=21 or int(nibbles[:5][::-1],16)!=0x2933: raise ValueError('Expected an HP real number')
    exponent=int(nibbles[5:8][::-1]); exponent=exponent-1000 if exponent>=500 else exponent
    mantissa=nibbles[8:20][::-1]
    return Decimal(('-' if nibbles[20]=='9' else '')+mantissa[0]+'.'+mantissa[1:]+'e'+str(exponent))


def decode_value(value):
    """Decode host-facing values; native file transfer remains byte-for-byte."""
    if value is None: raise ValueError('Calculator value exceeds inspection limits')
    kind=value['type'];raw=value.get('raw','')
    if kind==0x2a74:return [decode_value(item) for item in value['items']]
    if kind==0x2933:return decode_real(raw)
    if kind==0x2977:
        return complex(float(decode_real(number_nibbles(0x2933)+raw[5:21])),
                       float(decode_real(number_nibbles(0x2933)+raw[21:37])))
    if kind==0x2a2c:return decode_text(from_nibbles(raw[10:]))
    if kind==0x2e48:return decode_text(from_nibbles(raw[7:]))
    if kind==0x2a4e:return int(raw[10:][::-1] or '0',16)
    return value


def quote_name(name):
    if not re.fullmatch(r'[A-Za-zΑ-ω][A-Za-zΑ-ω0-9_]*',name):
        raise ValueError('Use a name starting with a letter, followed by letters, digits or underscores')
    return "'"+name+"'"


def quote_text(text):
    return '"'+text.replace('\\','\\\\').replace('"','\\"')+'"'


def query_source(source,token=None):
    # Preserve every user stack level even when the inspected command fails.
    import uuid
    saved='desktop'+uuid.uuid4().hex;result='desktop'+uuid.uuid4().hex
    if callable(source):source=source(saved)
    packet=f'"{token}" 3 →LIST' if token is not None else '2 →LIST'
    return (f'DEPTH →LIST → {saved} « IFERR {source} 1 {packet} '
            f'THEN CLEAR ERRM 0 {packet} END → {result} « CLEAR {saved} LIST→ DROP {result} » »')
