"""Structured UserRPL parser and interpreter.

Parsing finishes before execution. All execution paths share the calculator's
instruction budget, including empty loops and nested program evaluation.
"""
from __future__ import annotations
import ast
import copy
import json
import math
import operator
import re
import sympy as s
from .rpl_objects import RPLList, BinaryInteger, Command, Tagged

STRUCTURAL = set('IF IFERR THEN ELSE END CASE START FOR NEXT STEP DO UNTIL WHILE REPEAT →'.split())
RPL_COMMANDS = set('''DUP2 DUPN DROP2 DROPN ROLLD UNROT →LIST LIST→ →ARRY ARRY→
OBJ→ →STR STR→ TYPE VTYPE SAME == ≠ < > ≤ ≥ IFT IFTE →NUM →Q →Qπ
GET GETI PUT PUTI SUB POS HEAD TAIL REVLIST SORT SIZE ADD DOLIST STREAM SEQ
SF CF FS? FC? FS?C FC?C STWS RCWS BIN OCT DEC HEX R→B B→R SL SR ASR RL RR SLB SRB RLB RRB
AND OR XOR NOT R→C C→R →TAG DTAG CHR NUM STO+ STO- STO* STO/ INCR DECR
CRDIR HOME UPDIR PATH VARS ORDER PURGE RCL STO EVAL ERRM ERRN ERRC DOERR
SIGN MANT XPON MAXR MINR EXPM LNP1 %T ! PI π E I IDN TRN CNRM RNRM
V→ RND TRNC CEIL FLOOR INV NEG ABS MIN MAX = ∂ ∫ XROOT TAYLR EGV EGVL PCOEF PEVAL PROOT RREF DEFINE EXPAN COLCT
'''.split())


def error(message):
    from .engine import CalculatorError
    return CalculatorError(message)


def lex(source):
    """Retain nested object literals and quoted text as single tokens."""
    if len(source)>100000: raise error('Program is too long')
    result=[]; i=0
    opening={'[':']','{':'}','(':')','«':'»','<<':'>>'}
    def scan_object(pos):
        opener='<<' if source.startswith('<<',pos) else source[pos]
        closer=opening[opener]; start=pos; pos+=len(opener)
        while pos<len(source):
            if source.startswith(closer,pos): return source[start:pos+len(closer)],pos+len(closer)
            ch=source[pos]
            if ch in "'\"": _,pos=scan_quote(pos)
            elif source.startswith('<<',pos) or ch in opening: _,pos=scan_object(pos)
            elif ch in ']})»': raise error('Unbalanced delimiters')
            else: pos+=1
        raise error('Unclosed expression or program')
    def scan_quote(pos):
        start=pos; quote=source[pos]; pos+=1
        while pos<len(source):
            if source[pos]=='\\' and quote=='"': pos+=2; continue
            if source[pos]==quote: return source[start:pos+1],pos+1
            pos+=1
        raise error('Unclosed quoted object')
    while i<len(source):
        if source[i].isspace(): i+=1; continue
        if source[i]==':':
            end=source.find(':',i+1)
            if end<0: raise error('A tag needs two colons')
            prefix=source[i:end+1]; i=end+1
            while i<len(source) and source[i].isspace(): i+=1
            if i>=len(source): raise error('A tag needs an object')
            if source[i] in "'\"": value,i=scan_quote(i)
            elif source.startswith('<<',i) or source[i] in opening: value,i=scan_object(i)
            else:
                start=i
                while i<len(source) and not source[i].isspace(): i+=1
                value=source[start:i]
            token=prefix+value
        elif source[i] in "'\"": token,i=scan_quote(i)
        elif source.startswith('<<',i) or source[i] in opening: token,i=scan_object(i)
        elif source[i] in ']})»' or source.startswith('>>',i): raise error('Unbalanced delimiters')
        else:
            start=i
            while i<len(source) and not source[i].isspace(): i+=1
            token=source[start:i]
            if token=='#':
                while i<len(source) and source[i].isspace(): i+=1
                start=i
                while i<len(source) and not source[i].isspace(): i+=1
                token='#'+source[start:i]
        result.append(token)
    return result


def parse(source):
    tokens=lex(source); index=0
    def sequence(stops=frozenset()):
        nonlocal index
        nodes=[]
        while index<len(tokens) and tokens[index].upper() not in stops:
            token=tokens[index]; op=token.upper(); index+=1
            if op in ('IF','IFERR'):
                test=sequence({'THEN'}); take('THEN'); yes=sequence({'ELSE','END'}); no=[]
                if peek()=='ELSE': index+=1; no=sequence({'END'})
                take('END'); nodes.append((op,test,yes,no))
            elif op in ('FOR','START'):
                name=None
                if op=='FOR':
                    if index>=len(tokens) or not tokens[index].isidentifier(): raise error('FOR needs an index name')
                    name=tokens[index]; index+=1
                body=sequence({'NEXT','STEP'}); end=peek()
                if end not in ('NEXT','STEP'): raise error('Loop needs NEXT or STEP')
                index+=1; nodes.append(('LOOP',name,body,end))
            elif op=='WHILE':
                test=sequence({'REPEAT'}); take('REPEAT'); body=sequence({'END'}); take('END'); nodes.append((op,test,body))
            elif op=='DO':
                body=sequence({'UNTIL'}); take('UNTIL'); test=sequence({'END'}); take('END'); nodes.append((op,body,test))
            elif op=='CASE':
                clauses=[]; default=[]
                while True:
                    test=sequence({'THEN','END'})
                    if peek()=='END': index+=1; default=test; break
                    take('THEN'); body=sequence({'END'}); take('END'); clauses.append((test,body))
                nodes.append((op,clauses,default))
            elif op in ('→','->'):
                names=[]
                while index<len(tokens) and not tokens[index].startswith(('«','<<',"'")):
                    name=tokens[index]; index+=1
                    if not name.isidentifier(): raise error('Invalid local variable name')
                    names.append(name)
                if not names or index>=len(tokens): raise error('→ needs names followed by a program or algebraic')
                body=tokens[index]; index+=1; nodes.append(('LOCAL',names,body))
            elif op in STRUCTURAL: raise error(f'Unexpected {op}')
            else: nodes.append(('TOKEN',token))
        return nodes
    def peek(): return tokens[index].upper() if index<len(tokens) else None
    def take(wanted):
        nonlocal index
        if peek()!=wanted: raise error(f'Expected {wanted}')
        index+=1
    result=sequence()
    return result


class RPLRuntime:
    def init_rpl(self):
        self.rpl_state={'flags':[], 'wordsize':64, 'base':10, 'path':[], 'directories':{}, 'error':''}
        self.locals=[]

    def snapshot(self):
        return copy.deepcopy((self.stack,self.variables,self.angle,self.numeric,self.rpl_state))

    def restore(self,state):
        self.stack,self.variables,self.angle,self.numeric=copy.deepcopy(state[:4])
        if len(state)>4: self.rpl_state=copy.deepcopy(state[4])

    def tick(self):
        self._steps+=1
        if self._steps>100000: raise error('Program step limit exceeded (100000 instructions)')
        if len(self.stack)>10000: raise error('Stack size limit exceeded')

    def pop(self):
        self.require(1); return self.stack.pop()

    def integer(self,value,low=None,high=None):
        if isinstance(value,BinaryInteger): value=value.value
        if not isinstance(value,(int,s.Integer,s.Float,s.Rational)) or value!=int(value): raise error('Expected an integer')
        value=int(value)
        if (low is not None and value<low) or (high is not None and value>high): raise error('Integer out of range')
        return value

    def truth(self,value):
        if not isinstance(value,(s.Number,int,float)) or (isinstance(value,s.Number) and value.is_real is not True):
            raise error('Test needs a real number')
        return value!=0

    def visible_variables(self):
        values={}; path=self.rpl_state['path']
        for n in range(len(path)):
            values.update(self.rpl_state['directories'].get('/'.join(path[:n]),{}))
        values.update(self.variables)
        return values

    def lookup(self,name):
        for frame in reversed(self.locals):
            if name in frame: return frame[name]
        if name in self.variables: return self.variables[name]
        path=self.rpl_state['path']
        for n in range(len(path)-1,-1,-1):
            scope=self.rpl_state['directories'].get('/'.join(path[:n]),{})
            if name in scope: return scope[name]
        raise error(f'Unknown variable: {name}')

    def store(self,name,value):
        if not isinstance(name,s.Symbol): raise error('STO needs a quoted variable name')
        key=str(name)
        for frame in reversed(self.locals):
            if key in frame: frame[key]=copy.deepcopy(value); return
        if key.upper() in set(self.commands)|RPL_COMMANDS|STRUCTURAL: raise error('That name is reserved for a command')
        self.variables[key]=copy.deepcopy(value)

    def object(self,token):
        from .engine import Program, expression
        if token.startswith(':'):
            _,tag,value=token.split(':',2)
            return Tagged(tag,self.object(value))
        if token.startswith(('«','<<')):
            source=token[1:-1] if token.startswith('«') else token[2:-2]
            parse(source); return Program(source.strip())
        if token.startswith('"'):
            try: return json.loads(token)
            except ValueError: raise error('Invalid string escape; use \\" or \\\\')
        if token.startswith("'"): return expression(token[1:-1],self.angle)
        if token.startswith('{'): return RPLList(self.object(v) for v in lex(token[1:-1]))
        if token.startswith('#'):
            match=re.fullmatch(r'#\s*([0-9A-Fa-f]+?)([hHdDoObB]?)',token)
            if not match: raise error('Invalid binary integer')
            digits,suffix=match.groups(); base={'h':16,'d':10,'o':8,'b':2}.get(suffix.lower(),self.rpl_state['base'])
            try: value=int(digits,base)
            except ValueError: raise error('Invalid digit for binary integer base')
            return BinaryInteger(value&((1<<self.rpl_state['wordsize'])-1))
        if token.startswith('['):
            try: return expression(token,self.angle)
            except Exception:
                values=[self.object(v) for v in lex(token[1:-1])]
                if values and all(isinstance(v,list) for v in values): return s.Matrix(values)
                if not all(isinstance(v,s.Expr) and not v.free_symbols for v in values): raise error('Arrays require numbers')
                return values
        if token.startswith('(') and ',' in token:
            tree=ast.parse(token,mode='eval').body
            if isinstance(tree,ast.Tuple) and len(tree.elts)==2:
                real,imag=(expression(ast.unparse(v),self.angle) for v in tree.elts)
                if not all(isinstance(v,s.Expr) and v.is_real for v in (real,imag)): raise error('Complex components must be real')
                return real+s.I*imag
        if token.upper() in set(self.commands)|RPL_COMMANDS: return Command(token.upper())
        return expression(token,self.angle)

    def evaluate(self,value):
        self.tick()
        from .engine import Program
        if isinstance(value,dict) and value.get('rpl_directory'): self.change_directory(value['path'])
        elif isinstance(value,Program): self._run(value.source)
        elif isinstance(value,Command): self.run_token(value.name)
        elif isinstance(value,s.Symbol):
            try: resolved=self.lookup(str(value))
            except Exception: self.stack.append(value)
            else: self.evaluate(resolved)
        elif isinstance(value,s.Basic):
            mapping={}
            for symbol in value.free_symbols:
                try: found=self.lookup(str(symbol))
                except Exception: continue
                if isinstance(found,s.Basic): mapping[symbol]=found
            self.stack.append(value.subs(mapping))
        else: self.stack.append(copy.deepcopy(value))

    def run_nodes(self,nodes):
        for node in nodes:
            self.tick(); op=node[0]
            if op=='TOKEN': self.run_token(node[1])
            elif op in ('IF','IFERR'):
                if op=='IF': self.run_nodes(node[1]); condition=self.truth(self.pop())
                else:
                    try: self.run_nodes(node[1]); condition=False
                    except Exception as exc:
                        if 'limit exceeded' in str(exc): raise
                        self.rpl_state['error']=str(exc); condition=True
                self.run_nodes(node[2] if condition else node[3])
            elif op=='CASE':
                for test,body in node[1]:
                    self.run_nodes(test)
                    if self.truth(self.pop()): self.run_nodes(body); break
                else: self.run_nodes(node[2])
            elif op=='LOCAL':
                names=node[1]; self.require(len(names)); values=self.stack[-len(names):]; del self.stack[-len(names):]
                self.locals.append(dict(zip(names,values)))
                try: self.evaluate(self.object(node[2]))
                finally: self.locals.pop()
            elif op=='LOOP':
                self.require(2); first,last=self.stack[-2:]; del self.stack[-2:]
                if not all(isinstance(v,s.Expr) and v.is_real and not v.free_symbols for v in (first,last)): raise error('Loop bounds must be real')
                index=first; name=node[1]; frame={}; self.locals.append(frame)
                try:
                    # RPL definite loops execute the body before testing the next index.
                    while True:
                        self.tick()
                        if name: frame[name]=index
                        self.run_nodes(node[2]); step=self.pop() if node[3]=='STEP' else s.Integer(1)
                        if not isinstance(step,s.Expr) or not step.is_real or step==0: raise error('STEP needs a nonzero real increment')
                        index=(frame[name] if name else index)+step
                        if (step>0 and index>last) or (step<0 and index<last): break
                finally: self.locals.pop()
            elif op=='WHILE':
                while True:
                    self.tick(); self.run_nodes(node[1])
                    if not self.truth(self.pop()): break
                    self.run_nodes(node[2])
            elif op=='DO':
                while True:
                    self.tick(); self.run_nodes(node[1]); self.run_nodes(node[2])
                    if self.truth(self.pop()): break

    def run_token(self,token):
        # HP error trapping keeps arguments for the failing command. Top-level
        # entries additionally retain the application's transaction rollback.
        before=self.snapshot(); local_before=copy.deepcopy(self.locals)
        try: self.dispatch_token(token)
        except Exception:
            self.restore(before)
            for frame,previous in zip(self.locals,local_before): frame.clear(); frame.update(previous)
            raise

    def dispatch_token(self,token):
        command=token.upper().replace('->','→')
        command={'=<':'≤','<=':'≤','>=':'≥','=>':'≥','<>':'≠','!=':'≠'}.get(command,command)
        if not token.startswith("'"):
            try: value=self.lookup(token)
            except Exception: pass
            else:
                self.evaluate(value)
                return
        if self.rpl_command(command): return
        if token.startswith(('«','<<','{','"','#','[',':')) or (token.startswith('(') and ',' in token):
            self.stack.append(self.object(token)); return
        from .command_catalog import HP_COMMANDS
        if command in HP_COMMANDS and command not in self.commands and command not in ('DEG','RAD','GRAD','CLEAR','DUP','DROP','SWAP','OVER','ROT','DEPTH','PICK','ROLL'):
            raise error(f'{command} is an HP command that is not implemented in this engine')
        self._legacy_run(token)

    def rpl_command(self,cmd):
        from .engine import Program, format_value, arithmetic
        stack=self.stack
        def popn(n):
            self.require(n); values=stack[-n:] if n else [];
            if n: del stack[-n:]
            return values
        def push(value): stack.append(value)
        def binary(fn):
            self.require(2); a,b=stack[-2:]; result=fn(a,b); del stack[-2:]; push(result)
        def unary(fn):
            self.require(1); result=fn(stack[-1]); stack[-1]=result
        def truth_number(value): return s.Integer(bool(value))
        def dimension(value):
            if isinstance(value,RPLList): return RPLList(map(s.Integer,value.shape)) if hasattr(value,'shape') else s.Integer(len(value))
            if isinstance(value,s.MatrixBase): return RPLList(map(s.Integer,value.shape))
            if isinstance(value,list): return RPLList([s.Integer(len(value))])
            return s.Integer(len(value))
        if cmd in ('STO','RCL','EVAL','PURGE'):
            if cmd=='STO':
                self.require(2); self.store(stack[-1],stack[-2]); popn(2)
            elif cmd=='RCL': unary(lambda name:copy.deepcopy(self.lookup(str(name))))
            elif cmd=='EVAL': self.evaluate(self.pop())
            else:
                names=popn(1)[0]; names=names if isinstance(names,RPLList) else [names]
                for name in names:
                    key=str(name)
                    if key not in self.variables: raise error(f'Unknown variable: {name}')
                    del self.variables[key]
            return True
        if cmd in ('DUP2','DROP2','DUPN','DROPN','ROLLD','UNROT'):
            if cmd=='UNROT': self.require(3); stack.insert(len(stack)-3,stack.pop())
            elif cmd=='ROLLD':
                n=self.integer(self.pop(),1); self.require(n); stack.insert(len(stack)-n,stack.pop())
            else:
                n=2 if cmd.endswith('2') else self.integer(self.pop(),0,10000)
                self.require(n)
                if cmd.startswith('DUP'): stack.extend(copy.deepcopy(stack[-n:]) if n else [])
                elif n: del stack[-n:]
            return True
        if cmd in ('→LIST','LIST→','ARRY→','→ARRY','OBJ→','STR→','→STR'):
            if cmd=='→LIST': push(RPLList(popn(self.integer(self.pop(),0,10000))))
            elif cmd=='→ARRY':
                dims=self.pop(); dims=list(dims) if isinstance(dims,RPLList) else [dims]
                dims=[self.integer(v,1,10000) for v in dims]
                if len(dims) not in (1,2) or math.prod(dims)>10000: raise error('Invalid array dimensions')
                values=popn(math.prod(dims)); push(values if len(dims)==1 else s.Matrix(*dims,values))
            elif cmd=='→STR': unary(format_value)
            elif cmd=='STR→':
                value=self.pop()
                if not isinstance(value,str): raise error('STR→ needs a string')
                self._run(value)
            else:
                value=self.pop()
                if isinstance(value,RPLList): stack.extend(copy.deepcopy(value)); push(s.Integer(len(value)))
                elif cmd!='LIST→' and isinstance(value,(list,s.MatrixBase)):
                    stack.extend(list(value)); push(dimension(value))
                elif cmd=='OBJ→' and isinstance(value,str): self._run(value)
                elif cmd=='OBJ→' and isinstance(value,Tagged): stack.extend([value.value,value.tag])
                elif cmd=='OBJ→' and isinstance(value,s.Expr) and value.is_number: stack.extend([s.re(value),s.im(value)])
                else: raise error(f'{cmd}: unsupported object type')
            return True
        if cmd in ('TYPE','VTYPE'): unary(lambda v:s.Integer(self.object_type(self.lookup(str(v)) if cmd=='VTYPE' else v))); return True
        if cmd in ('SAME','==','≠','<','>','≤','≥'):
            functions={'SAME':lambda a,b:type(a)==type(b) and a==b,'==':operator.eq,'≠':operator.ne,'<':operator.lt,'>':operator.gt,'≤':operator.le,'≥':operator.ge}
            def compare(a,b):
                if cmd!='SAME' and isinstance(a,s.Expr) and isinstance(b,s.Expr) and (a.free_symbols or b.free_symbols):
                    return {'==':s.Eq,'≠':s.Ne,'<':s.Lt,'>':s.Gt,'≤':s.Le,'≥':s.Ge}[cmd](a,b)
                return truth_number(functions[cmd](a,b))
            binary(compare); return True
        if cmd in ('IFT','IFTE'):
            values=popn(2 if cmd=='IFT' else 3)
            if self.truth(values[0]): self.evaluate(values[1])
            elif cmd=='IFTE': self.evaluate(values[2])
            return True
        if cmd in ('SF','CF','FS?','FC?','FS?C','FC?C'):
            flag=self.integer(self.pop(),1,64); flags=set(self.rpl_state['flags']); isset=flag in flags
            if cmd=='SF': flags.add(flag)
            elif cmd in ('CF','FS?C','FC?C'): flags.discard(flag)
            if '?' in cmd: push(s.Integer(isset if cmd.startswith('FS') else not isset))
            self.rpl_state['flags']=sorted(flags); return True
        if cmd in ('BIN','OCT','DEC','HEX','STWS','RCWS','R→B','B→R'):
            if cmd in ('BIN','OCT','DEC','HEX'): self.rpl_state['base']={'BIN':2,'OCT':8,'DEC':10,'HEX':16}[cmd]
            elif cmd=='STWS': self.rpl_state['wordsize']=self.integer(self.pop(),1,64)
            elif cmd=='RCWS': push(s.Integer(self.rpl_state['wordsize']))
            elif cmd=='R→B': unary(lambda v:BinaryInteger(self.integer(v)&((1<<self.rpl_state['wordsize'])-1)))
            else:
                if not isinstance(stack[-1] if stack else None,BinaryInteger): raise error('B→R needs a binary integer')
                unary(lambda v:s.Integer(v.value))
            return True
        if cmd in ('AND','OR','XOR','NOT','SL','SR','ASR','RL','RR','SLB','SRB','RLB','RRB'):
            mask=(1<<self.rpl_state['wordsize'])-1; width=self.rpl_state['wordsize']
            if cmd in ('AND','OR','XOR'):
                def logical(a,b):
                    fn={'AND':operator.and_,'OR':operator.or_,'XOR':operator.xor}[cmd]
                    if isinstance(a,BinaryInteger) and isinstance(b,BinaryInteger): return BinaryInteger(fn(a.value,b.value)&mask)
                    if isinstance(a,str) and isinstance(b,str):
                        if len(a)!=len(b): raise error('String lengths must agree')
                        return ''.join(chr(fn(ord(x),ord(y))) for x,y in zip(a,b))
                    return s.Integer(fn(self.truth(a),self.truth(b)))
                binary(logical)
            elif cmd=='NOT': unary(lambda v:BinaryInteger(~v.value&mask) if isinstance(v,BinaryInteger) else ''.join(chr(ord(c)^255) for c in v) if isinstance(v,str) else s.Integer(not self.truth(v)))
            else:
                def shift(v):
                    if not isinstance(v,BinaryInteger): raise error('Shift needs a binary integer')
                    n=8 if cmd.endswith('B') else 1; x=v.value&mask
                    if cmd.startswith('SL'): x<<=n
                    elif cmd.startswith('SR'): x>>=n
                    elif cmd=='ASR': x=(x>>1)|(x&(1<<(width-1)))
                    elif cmd.startswith('RL'): n%=width; x=(x<<n)|(x>>(width-n))
                    else: n%=width; x=(x>>n)|(x<<(width-n))
                    return BinaryInteger(x&mask)
                unary(shift)
            return True
        if cmd=='+' and len(stack)>=2 and any(isinstance(v,(RPLList,str,BinaryInteger)) for v in stack[-2:]):
            def add(a,b):
                if isinstance(a,RPLList) or isinstance(b,RPLList): return RPLList((list(a) if isinstance(a,RPLList) else [a])+(list(b) if isinstance(b,RPLList) else [b]))
                if isinstance(a,str) and isinstance(b,str): return a+b
                if isinstance(a,BinaryInteger) and isinstance(b,BinaryInteger): return BinaryInteger((a.value+b.value)&((1<<self.rpl_state['wordsize'])-1))
                raise error('Incompatible addition types')
            binary(add); return True
        if cmd in ('-','*','/') and len(stack)>=2 and any(isinstance(v,BinaryInteger) for v in stack[-2:]):
            def binary_math(a,b):
                if not isinstance(a,BinaryInteger) or not isinstance(b,BinaryInteger): raise error('Binary arithmetic needs two binary integers')
                fn={'-':operator.sub,'*':operator.mul,'/':operator.floordiv}[cmd]
                return BinaryInteger(fn(a.value,b.value)&((1<<self.rpl_state['wordsize'])-1))
            binary(binary_math); return True
        if cmd=='TRN':
            def transpose(v):
                if not isinstance(v,s.MatrixBase): raise error('TRN needs a matrix')
                return v.conjugate().T
            if stack and isinstance(stack[-1],s.Symbol):
                name=self.pop(); self.store(name,transpose(self.lookup(str(name))))
            else: unary(transpose)
            return True
        if cmd in ('CNRM','RNRM'):
            def norm(v):
                if isinstance(v,s.MatrixBase): return v.norm(1 if cmd=='CNRM' else s.oo)
                if isinstance(v,list): return sum(abs(x) for x in v) if cmd=='CNRM' else max(abs(x) for x in v)
                raise error('Norm needs an array')
            unary(norm); return True
        if cmd=='V→':
            value=self.pop()
            if isinstance(value,list) and not isinstance(value,RPLList): stack.extend(value)
            elif isinstance(value,s.Expr) and value.is_number: stack.extend([s.re(value),s.im(value)])
            else: raise error('V→ needs a vector or complex number')
            return True
        if cmd in ('RND','TRNC'):
            def rounded(v,n):
                n=self.integer(n,-12,12)
                if isinstance(v,s.MatrixBase): return v.applyfunc(lambda x:rounded(x,n))
                if isinstance(v,list): return type(v)(rounded(x,n) for x in v)
                if not isinstance(v,s.Expr) or not v.is_number: raise error('Rounding needs a number')
                if v.is_real is not True: return rounded(s.re(v),n)+s.I*rounded(s.im(v),n)
                places=n if n>=0 or v==0 else -n-1-int(s.floor(s.log(abs(v),10)))
                factor=s.Integer(10)**places; scaled=abs(v)*factor
                value=s.floor(scaled+s.Rational(1,2)) if cmd=='RND' else s.floor(scaled)
                return s.sign(v)*value/factor
            binary(rounded); return True
        if cmd=='SIZE': unary(dimension); return True
        if cmd in ('HEAD','TAIL','REVLIST','SORT'):
            def change(v):
                if not isinstance(v,(RPLList,str,list)): raise error(f'{cmd} needs a sequence')
                if cmd=='HEAD':
                    if not v: raise error('Empty sequence')
                    return v[0]
                if cmd=='TAIL': return type(v)(v[1:])
                if cmd=='REVLIST': return type(v)(v[::-1])
                return type(v)(sorted(v))
            unary(change); return True
        if cmd=='ADD':
            def add(a,b):
                if isinstance(a,RPLList) and isinstance(b,RPLList):
                    if len(a)!=len(b): raise error('List lengths must agree')
                    return RPLList(arithmetic('+',x,y) for x,y in zip(a,b))
                if isinstance(a,RPLList): return RPLList(arithmetic('+',v,b) for v in a)
                if isinstance(b,RPLList): return RPLList(arithmetic('+',a,v) for v in b)
                return arithmetic('+',a,b)
            binary(add); return True
        if cmd in ('GET','GETI','PUT','PUTI'):
            self.index_command(cmd); return True
        if cmd=='SUB':
            value,start,end=popn(3); start=self.integer(start,1); end=self.integer(end,0); push(type(value)(value[start-1:end])); return True
        if cmd=='POS':
            def position(value,target):
                try: return s.Integer(value.find(target)+1 if isinstance(value,str) else value.index(target)+1)
                except ValueError: return s.Integer(0)
            binary(position); return True
        if cmd in ('DOLIST','STREAM','SEQ'):
            self.list_program(cmd); return True
        if cmd in ('→TAG','DTAG'):
            if cmd=='→TAG': value,tag=popn(2); push(Tagged(str(tag),value))
            else: unary(lambda v:v.value if isinstance(v,Tagged) else v)
            return True
        if cmd=='CHR': unary(lambda n:chr(self.integer(n,0,255))); return True
        if cmd=='NUM' and stack and isinstance(stack[-1],str):
            if not stack[-1]: raise error('NUM needs a nonempty string')
            unary(lambda v:s.Integer(ord(v[0]))); return True
        if cmd in ('R→C','C→R'):
            if cmd=='R→C': binary(lambda a,b:a+s.I*b)
            else: v=self.pop(); stack.extend([s.re(v),s.im(v)])
            return True
        if cmd in ('STO+','STO-','STO*','STO/','INCR','DECR'):
            name=self.pop(); value=self.lookup(str(name)); operand=s.Integer(1) if cmd in ('INCR','DECR') else self.pop()
            result=arithmetic('+' if cmd=='INCR' else '-' if cmd=='DECR' else cmd[-1],value,operand)
            self.store(name,result)
            if cmd in ('INCR','DECR'): push(result)
            return True
        if cmd in ('CRDIR','HOME','UPDIR','PATH','VARS','ORDER'):
            path=self.rpl_state['path']; directories=self.rpl_state['directories']
            if cmd=='PATH': push(RPLList(s.Symbol(n) for n in ['HOME']+path))
            elif cmd=='VARS': push(RPLList(s.Symbol(n) for n in self.variables))
            elif cmd=='ORDER':
                names=self.pop()
                if not isinstance(names,RPLList): raise error('ORDER needs a list of names')
                keys=list(dict.fromkeys(map(str,names)))
                if any(k not in self.variables for k in keys): raise error('Unknown variable in ORDER')
                self.variables={k:self.variables[k] for k in keys+list(self.variables) if k in self.variables}
            elif cmd=='CRDIR':
                name=self.pop()
                if not isinstance(name,s.Symbol): raise error('CRDIR needs a name')
                if str(name) in self.variables: raise error('Name already exists')
                self.variables[str(name)]={'rpl_directory':s.Integer(1),'path':path+[str(name)]}; directories['/'.join(path+[str(name)])]={}
            else: self.change_directory([] if cmd=='HOME' else path[:-1])
            return True
        if cmd in ('ERRM','ERRN','ERRC','DOERR'):
            if cmd=='ERRM': push(self.rpl_state['error'])
            elif cmd=='ERRN': push(BinaryInteger(0 if not self.rpl_state['error'] else 1))
            elif cmd=='ERRC': self.rpl_state['error']=''
            else: raise error(str(self.pop()))
            return True
        aliases={'→NUM':'NUM','→Q':'RATIONAL','→Qπ':'RATIONALPI','!':'FACT','SIGN':'SIGN','LNP1':'LNP1','EXPM':'EXPM'}
        if cmd in aliases:
            target=aliases[cmd]
            if target in self.commands:
                self._legacy_run(target)
            else:
                funcs={'RATIONAL':lambda v:s.Rational(str(v)).limit_denominator(10**12),'RATIONALPI':lambda v:s.Rational(str(s.N(v/s.pi))).limit_denominator(10**6)*s.pi,'SIGN':s.sign,'LNP1':lambda v:s.log(1+v),'EXPM':lambda v:s.exp(v)-1}
                unary(funcs[target])
            return True
        if cmd in ('PI','Π','E','I','MAXR','MINR'):
            push({'PI':s.pi,'Π':s.pi,'E':s.E,'I':s.I,'MAXR':s.Float('9.99999999999e499'),'MINR':s.Float('1e-499')}[cmd]); return True
        if cmd=='=': binary(lambda a,b:s.Eq(a,b,evaluate=False)); return True
        if cmd=='∂': binary(s.diff); return True
        if cmd=='∫':
            lower,upper,integrand,name=popn(4); push(s.integrate(integrand,(name,lower,upper))); return True
        if cmd=='XROOT':
            def root(value,n):
                if n==0: raise error('Root degree cannot be zero')
                return s.real_root(value,n) if n.is_integer and n.is_odd and value.is_real else value**(1/n)
            binary(root); return True
        if cmd=='TAYLR':
            value,name,n=popn(3); n=self.integer(n,0,1000); push(s.series(value,name,0,n+1).removeO()); return True
        if cmd in ('EGVL','RREF','EXPAN','COLCT'):
            unary({'EGVL':lambda m:[v for v,n in m.eigenvals().items() for _ in range(n)],
                   'RREF':lambda m:m.rref()[0],'EXPAN':s.expand,'COLCT':s.simplify}[cmd]); return True
        if cmd=='EGV':
            matrix=self.pop(); values=[]; vectors=[]
            for value,multiplicity,basis in matrix.eigenvects():
                if len(basis)!=multiplicity: raise error('Matrix does not have a full eigenvector basis')
                values.extend([value]*multiplicity); vectors.extend(basis)
            stack.extend([s.Matrix.hstack(*vectors),values]); return True
        if cmd in ('PCOEF','PROOT','PEVAL'):
            x=s.Dummy('x')
            if cmd=='PCOEF': unary(lambda roots:s.Poly(s.prod(x-r for r in roots),x).all_coeffs())
            elif cmd=='PROOT': unary(lambda coeff:s.Poly.from_list(list(coeff),x).all_roots())
            else: binary(lambda coeff,v:s.Poly.from_list(list(coeff),x).eval(v))
            return True
        if cmd=='DEFINE':
            equation=self.pop()
            if not isinstance(equation,s.Equality) or not isinstance(equation.lhs,s.Symbol): raise error('DEFINE currently supports name=expression')
            self.store(equation.lhs,equation.rhs); return True
        if cmd=='%T': binary(lambda total,part:100*part/total); return True
        if cmd=='IDN': unary(lambda n:s.eye(self.integer(n,1,100))); return True
        if cmd in ('MANT','XPON'):
            def component(v):
                if not v.is_real or not v.is_number: raise error('Expected a real number')
                exponent=s.Integer(0) if v==0 else s.floor(s.log(abs(v),10))
                return exponent if cmd=='XPON' else v/10**exponent
            unary(component); return True
        return False

    def change_directory(self,path):
        directories=self.rpl_state['directories']
        directories['/'.join(self.rpl_state['path'])]=self.variables
        self.variables=directories.setdefault('/'.join(path),{})
        self.rpl_state['path']=list(path)

    def index_command(self,cmd):
        put=cmd.startswith('PUT'); self.require(3 if put else 2)
        value=self.pop() if put else None; index=self.pop(); original=self.pop()
        named=isinstance(original,s.Symbol); sequence=copy.deepcopy(self.lookup(str(original)) if named else original)
        shape=list(sequence.shape) if isinstance(sequence,s.MatrixBase) else [len(sequence)]
        coords=list(index) if isinstance(index,RPLList) else [index]
        if len(coords)==2 and len(shape)==2:
            row,col=(self.integer(v,1,limit)-1 for v,limit in zip(coords,shape)); flat=row*shape[1]+col
        elif len(coords)==1: flat=self.integer(coords[0],1,math.prod(shape))-1
        else: raise error('Invalid index dimensions')
        if put:
            sequence[flat]=value
            if named: self.store(original,sequence)
            else: self.stack.append(sequence)
        else:
            if cmd=='GETI': self.stack.extend([original,index])
            self.stack.append(sequence[flat])
        if cmd.endswith('I'):
            new=(flat+1)%math.prod(shape)
            if len(coords)==2: next_index=RPLList([s.Integer(new//shape[1]+1),s.Integer(new%shape[1]+1)])
            elif isinstance(index,RPLList): next_index=RPLList([s.Integer(new+1)])
            else: next_index=s.Integer(new+1)
            if put:
                if named: self.stack.append(original)
                self.stack.append(next_index)
            else: self.stack[-2]=next_index

    def list_program(self,cmd):
        if cmd=='SEQ':
            self.require(5); obj,name,start,end,step=self.stack[-5:]; del self.stack[-5:]
            if not isinstance(name,s.Symbol) or not all(isinstance(v,s.Expr) and v.is_real and v.is_number for v in (start,end,step)) or step==0: raise error('SEQ needs a name, real bounds, and nonzero step')
            results=RPLList(); index=start; self.locals.append({})
            try:
                while (step>0 and index<=end) or (step<0 and index>=end):
                    self.tick(); self.locals[-1][str(name)]=index; self.evaluate(obj); results.append(self.pop()); index+=step
            finally: self.locals.pop()
            self.stack.append(results); return
        obj=self.pop()
        if cmd=='STREAM':
            values=self.pop()
            if not isinstance(values,RPLList) or not values: raise error('STREAM needs a nonempty list')
            self.stack.append(values[0])
            for value in values[1:]: self.tick(); self.stack.append(value); self.evaluate(obj)
        else:
            n=1
            if self.stack and isinstance(self.stack[-1],s.Number): n=self.integer(self.pop(),1,10000)
            self.require(n); lists=self.stack[-n:]; del self.stack[-n:]
            if not all(isinstance(v,RPLList) and len(v)==len(lists[0]) for v in lists): raise error('DOLIST needs lists of equal length')
            results=RPLList()
            for values in zip(*lists):
                self.tick(); baseline=len(self.stack); self.stack.extend(copy.deepcopy(values)); self.evaluate(obj)
                if len(self.stack)<baseline: raise error('List program consumed the enclosing stack')
                results.extend(self.stack[baseline:]); del self.stack[baseline:]
            self.stack.append(results)

    def object_type(self,value):
        from .engine import Program
        if isinstance(value,RPLList): return 5
        if isinstance(value,BinaryInteger): return 10
        if isinstance(value,Tagged): return 12
        if isinstance(value,Command): return 19
        if isinstance(value,Program): return 8
        if isinstance(value,str): return 2
        if isinstance(value,(list,s.MatrixBase)): return 4 if any(s.im(v)!=0 for v in value) else 3
        if isinstance(value,s.Symbol): return 7 if any(str(value) in frame for frame in self.locals) else 6
        if isinstance(value,s.Expr): return 9 if value.free_symbols else 0 if value.is_real else 1
        if isinstance(value,dict) and value.get('rpl_directory'): return 15
        raise error('Unsupported object type')
