"""Versioned JSON values with an explicit, non-executable SymPy schema."""
import ast
import json
import os
from pathlib import Path
import tempfile
import sympy as s
from .engine import CalculatorError, Program, expression, FUNCTIONS, arithmetic
from .rpl_objects import RPLList, BinaryInteger, Command, Tagged
from sympy.functions.elementary.piecewise import ExprCondPair

CONSTRUCTORS = {name: getattr(s,name) for name in (
    'Add Mul Pow Tuple Integral Derivative Sum Product Limit Piecewise Eq Ne Lt Le Gt Ge '
    'And Or Not Mod Min Max FiniteSet Union Intersection Interval Complement Contains '
    'RootOf CRootOf RootSum Lambda Subs Order factorial2 RisingFactorial FallingFactorial '
    'polygamma loggamma lowergamma uppergamma beta erfc erfi erfinv erfcinv '
    'LambertW hyper meijerg expint Ei Si Ci fresnels fresnelc DiracDelta Heaviside '
    'KroneckerDelta sign conjugate re im arg atan2').split()}
CONSTRUCTORS.update({fn.__name__:fn for fn in FUNCTIONS.values()})
CONSTRUCTORS.update({fn.__name__:fn for fn in list(CONSTRUCTORS.values())})
CONSTRUCTORS['ExprCondPair']=ExprCondPair
CONSTANTS = {str(v):v for v in (s.pi,s.E,s.I,s.oo,-s.oo,s.zoo,s.nan,s.true,s.false,s.EulerGamma,s.Catalan)}
MAX_FILE_BYTES = 20_000_000


def encode(value):
    if isinstance(value,RPLList): return {'rpl_list':[encode(v) for v in value]}
    if isinstance(value,BinaryInteger): return {'binary_integer':str(value.value)}
    if isinstance(value,Command): return {'command':value.name}
    if isinstance(value,Tagged): return {'tagged':[value.tag,encode(value.value)]}
    if isinstance(value,str): return {'text':value}
    if isinstance(value,Program): return {'program':value.source}
    if isinstance(value,s.MatrixBase): return {'matrix':{'rows':value.rows,'cols':value.cols,'values':[encode(v) for v in value]}}
    if isinstance(value,list): return {'list':[encode(v) for v in value]}
    if isinstance(value,tuple): return {'tuple':[encode(v) for v in value]}
    if isinstance(value,dict): return {'dict':[[encode(k),encode(v)] for k,v in value.items()]}
    if type(value) in (int,float,complex): value=s.sympify(value)
    if isinstance(value,s.Integer): return {'integer':str(value)}
    if isinstance(value,s.Rational): return {'rational':[str(value.p),str(value.q)]}
    if isinstance(value,s.Float): return {'float':[str(value),value._prec]}
    if isinstance(value,s.Symbol):
        data={'name':value.name,'assumptions':value.assumptions0}
        if isinstance(value,s.Dummy): data['dummy_index']=value.dummy_index
        return {'symbol':data}
    if isinstance(value,s.Basic):
        if str(value) in CONSTANTS and value==CONSTANTS[str(value)]: return {'constant':str(value)}
        name=value.func.__name__
        if name in CONSTRUCTORS:
            return {'node':{'name':name,'args':[encode(v) for v in value.args]}}
    raise CalculatorError(f'Cannot save unsupported value type: {type(value).__name__}')


def decode(value, depth=0):
    if depth>100: raise CalculatorError('Session value is too deeply nested')
    if not isinstance(value,dict) or len(value)!=1: raise CalculatorError('Invalid session value')
    kind,data=next(iter(value.items()))
    child=lambda v:decode(v,depth+1)
    if kind=='rpl_list': return RPLList(child(v) for v in data)
    if kind=='binary_integer':
        number=int(data)
        if not 0<=number<2**64: raise CalculatorError('Invalid binary integer')
        return BinaryInteger(number)
    if kind=='command':
        from .engine import Calculator,STACK_COMMANDS
        if not isinstance(data,str) or data not in set(Calculator().commands)|STACK_COMMANDS: raise CalculatorError('Invalid command object')
        return Command(data)
    if kind=='tagged':
        if not isinstance(data,list) or len(data)!=2 or not isinstance(data[0],str): raise CalculatorError('Invalid tagged object')
        return Tagged(data[0],child(data[1]))
    if kind=='text':
        if not isinstance(data,str): raise CalculatorError('Invalid text value')
        return data
    if kind=='program':
        if not isinstance(data,str): raise CalculatorError('Invalid program')
        return Program(data)
    if kind=='expr': return legacy_expression(data)
    if kind=='integer': return s.Integer(data)
    if kind=='rational': return s.Rational(*data)
    if kind=='float':
        if not 2<=int(data[1])<=100000: raise CalculatorError('Invalid float precision')
        return s.Float(data[0],precision=data[1])
    if kind=='constant' and data in CONSTANTS: return CONSTANTS[data]
    if kind=='symbol':
        if not isinstance(data.get('name'),str): raise CalculatorError('Invalid symbol name')
        assumptions=data.get('assumptions',{})
        if not all(type(v) is bool for v in assumptions.values()): raise CalculatorError('Invalid symbol assumptions')
        if 'dummy_index' in data: return s.Dummy(data['name'],dummy_index=int(data['dummy_index']),**assumptions)
        return s.Symbol(data['name'],**assumptions)
    if kind=='matrix':
        if isinstance(data,list): return s.Matrix([[child(v) for v in row] for row in data])
        rows,cols=data['rows'],data['cols']
        if type(rows) is not int or type(cols) is not int or rows<0 or cols<0 or rows*cols!=len(data['values']):
            raise CalculatorError('Invalid matrix dimensions')
        return s.Matrix(rows,cols,[child(v) for v in data['values']])
    if kind in ('list','tuple'):
        items=[child(v) for v in data]
        return items if kind=='list' else tuple(items)
    if kind=='dict': return {child(k):child(v) for k,v in data}
    if kind=='node' and data.get('name') in CONSTRUCTORS:
        name=data['name']; args=[child(v) for v in data['args']]
        if name in ('Add','Mul','Pow','Piecewise','Eq','Ne','Lt','Le','Gt','Ge'):
            return CONSTRUCTORS[name](*args,evaluate=False)
        return CONSTRUCTORS[name](*args)
    raise CalculatorError('Unknown session value type')


def legacy_expression(source):
    """Read old mathematical display strings, including unevaluated results."""
    if not isinstance(source,str) or len(source)>10000: raise CalculatorError('Invalid legacy expression')
    tree=ast.parse(source.replace('^','**'),mode='eval')
    if sum(1 for _ in ast.walk(tree))>1000: raise CalculatorError('Expression is too complex')
    def visit(node):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and not node.keywords and node.func.id in CONSTRUCTORS:
            return CONSTRUCTORS[node.func.id](*(visit(v) for v in node.args))
        if isinstance(node,ast.Tuple): return tuple(visit(v) for v in node.elts)
        if isinstance(node,ast.Compare) and len(node.ops)==1:
            constructors={ast.Gt:s.Gt,ast.Lt:s.Lt,ast.GtE:s.Ge,ast.LtE:s.Le,ast.Eq:s.Eq,ast.NotEq:s.Ne}
            if type(node.ops[0]) in constructors: return constructors[type(node.ops[0])](visit(node.left),visit(node.comparators[0]))
        if isinstance(node,ast.Constant) and type(node.value) is bool: return s.true if node.value else s.false
        if isinstance(node,ast.BinOp):
            ops={ast.Add:'+',ast.Sub:'-',ast.Mult:'*',ast.Div:'/',ast.Pow:'^'}
            if type(node.op) in ops: return arithmetic(ops[type(node.op)],visit(node.left),visit(node.right))
        if isinstance(node,ast.UnaryOp) and isinstance(node.op,ast.USub): return -visit(node.operand)
        if isinstance(node,ast.Name) and node.id in CONSTANTS: return CONSTANTS[node.id]
        return expression(ast.unparse(node))
    return visit(tree.body)


def calculator_state(calc):
    return {'stack':[encode(v) for v in calc.stack], 'variables':{k:encode(v) for k,v in calc.variables.items()},
            'angle':calc.angle,'numeric':calc.numeric,'rpl':encode(calc.rpl_state)}


def read_rpl(data):
    from .engine import Calculator
    default=Calculator().rpl_state
    if 'rpl' not in data: return default
    state=decode(data['rpl'])
    if not isinstance(state,dict) or set(state)!=set(default): raise CalculatorError('Invalid RPL state')
    if not isinstance(state['flags'],list) or any(not isinstance(v,s.Integer) or not 1<=v<=64 for v in state['flags']): raise CalculatorError('Invalid user flags')
    if not isinstance(state['wordsize'],s.Integer) or not 1<=state['wordsize']<=64 or state['base'] not in (2,8,10,16): raise CalculatorError('Invalid binary mode')
    state['wordsize']=int(state['wordsize']); state['base']=int(state['base']); state['flags']=list(map(int,state['flags']))
    if not isinstance(state['path'],list) or any(not isinstance(v,str) or not v.isidentifier() for v in state['path']): raise CalculatorError('Invalid directory path')
    if not isinstance(state['directories'],dict) or not all(isinstance(k,str) and isinstance(v,dict) and all(isinstance(n,str) and n.isidentifier() for n in v) for k,v in state['directories'].items()): raise CalculatorError('Invalid directories')
    if not isinstance(state['error'],str): raise CalculatorError('Invalid error state')
    return state


def read_calculator(data):
    read_rpl(data)
    if data.get('angle') not in ('DEG','RAD','GRAD') or type(data.get('numeric')) is not bool:
        raise CalculatorError('Invalid calculator modes')
    if not isinstance(data.get('stack'),list) or len(data['stack'])>10000 or not isinstance(data.get('variables'),dict):
        raise CalculatorError('Invalid calculator state')
    if not all(isinstance(k,str) and k.isidentifier() for k in data['variables']):
        raise CalculatorError('Invalid variable name')
    return [decode(v) for v in data['stack']],{k:decode(v) for k,v in data['variables'].items()},data['angle'],data['numeric']


def write_json(path,data):
    """Validate first; replace atomically so a failed save preserves the old file."""
    payload=json.dumps(data,indent=2,allow_nan=False)
    if len(payload.encode())>MAX_FILE_BYTES: raise CalculatorError('Session exceeds the 20 MB limit')
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as file:
            temporary=file.name; file.write(payload); file.flush(); os.fsync(file.fileno())
        os.replace(temporary,path)
    finally:
        if temporary and os.path.exists(temporary): os.unlink(temporary)


def read_json(path):
    path=Path(path)
    if path.stat().st_size>MAX_FILE_BYTES: raise CalculatorError('Session exceeds the 20 MB limit')
    return json.loads(path.read_text(),parse_constant=lambda x:(_ for _ in ()).throw(CalculatorError('Non-finite session number')))
