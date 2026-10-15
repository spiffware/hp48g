"""Transactional RPN engine and restricted mathematical expression parser.

Expressions are interpreted through an AST whitelist; user input is never eval'd.
"""
from __future__ import annotations
import ast
import copy
import math
import re
from dataclasses import dataclass
import sympy as s


class CalculatorError(ValueError):
    pass


@dataclass(frozen=True)
class Program:
    source: str


FUNCTIONS = {name: getattr(s, name) for name in (
    'sin cos tan asin acos atan sinh cosh tanh asinh acosh atanh exp log sqrt '
    'Abs factorial floor ceiling conjugate re im arg gamma erf binomial sign').split()}
FUNCTIONS.update(ln=s.log, abs=s.Abs, atan2=s.atan2)


def expression(source: str):
    """Parse numbers, symbolic algebra, lists, and matrices without Python execution."""
    if len(source) > 10000:
        raise CalculatorError('Expression is too long')
    source = source.strip().replace('^', '**').replace('π', 'pi').replace('−', '-')
    try:
        tree = ast.parse(source, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 1000:
            raise CalculatorError('Expression is too complex')
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float, complex):
                return s.sympify(node.value)
            if isinstance(node, ast.Name) and not node.id.startswith('_'):
                return {'pi': s.pi, 'e': s.E, 'E': s.E, 'i': s.I, 'I': s.I}.get(node.id, s.Symbol(node.id))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return -value if isinstance(node.op, ast.USub) else value
            if isinstance(node, ast.BinOp):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): return a + b
                if isinstance(node.op, ast.Sub): return a - b
                if isinstance(node.op, ast.Mult): return a * b
                if isinstance(node.op, ast.Div):
                    if b == 0: raise CalculatorError('Division by zero')
                    return a / b
                if isinstance(node.op, ast.Pow):
                    if b.is_number and abs(complex(b)) > 10000: raise CalculatorError('Exponent is too large')
                    return a ** b
            if isinstance(node, (ast.List, ast.Tuple)):
                values = [visit(v) for v in node.elts]
                if values and all(isinstance(v, list) for v in values): return s.Matrix(values)
                return values
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
                return FUNCTIONS[node.func.id](*(visit(v) for v in node.args))
            raise CalculatorError('Use mathematical expressions only')
        return visit(tree.body)
    except CalculatorError:
        raise
    except Exception as exc:
        raise CalculatorError(f'Invalid expression: {exc}') from exc


def format_value(value, numeric=False):
    if isinstance(value, Program): return f'« {value.source} »'
    if isinstance(value, list): return '[' + ', '.join(format_value(v, numeric) for v in value) + ']'
    if isinstance(value, s.MatrixBase): return str(value.tolist())
    if numeric and hasattr(value, 'evalf') and not value.free_symbols:
        value = value.evalf(12)
    return str(value).replace('**', '^')


def tokenize(source):
    tokens, start, depth, quote = [], 0, [], None
    for index, char in enumerate(source):
        if quote:
            if char == quote: quote = None
        elif char in "'\"": quote = char
        elif char in '[({«': depth.append(char)
        elif char in '])}»':
            if not depth or '[({«'.index(depth.pop()) != '])}»'.index(char):
                raise CalculatorError('Unbalanced delimiters')
        elif char.isspace() and not depth:
            if source[start:index].strip(): tokens.append(source[start:index].strip())
            start = index + 1
    if depth or quote: raise CalculatorError('Unclosed expression or program')
    if source[start:].strip(): tokens.append(source[start:].strip())
    return tokens


class Calculator:
    def __init__(self):
        self.stack = []
        self.variables = {}
        self.angle = 'DEG'
        self.numeric = False
        self.history = []
        self._steps = 0
        self.commands = {}
        self._register()

    def _register(self):
        def unary(name, fn): self.commands[name] = (1, fn)
        def binary(name, fn): self.commands[name] = (2, fn)
        for name, fn in {'+': lambda a,b:a+b, '-':lambda a,b:a-b, '*':lambda a,b:a*b,
                         '/':self._divide, '^':lambda a,b:a**b, 'MOD':lambda a,b:a%b,
                         '%':lambda a,b:a*b/100, '%CH':lambda a,b:100*(b-a)/a,
                         'MIN':s.Min, 'MAX':s.Max, 'COMB':s.binomial,
                         'PERM':lambda n,r:s.factorial(n)/s.factorial(n-r),
                         'GCD':s.gcd, 'LCM':s.lcm, 'ATAN2':lambda y,x:self._out_angle(s.atan2(y,x)),
                         'DOT':lambda a,b:s.Matrix(a).dot(s.Matrix(b)),
                         'CROSS':lambda a,b:list(s.Matrix(a).cross(s.Matrix(b))),
                         'LSOLVE':lambda a,b:a.inv()*s.Matrix(b),
                         'DIFF':lambda f,x:s.diff(f,x), 'INT':lambda f,x:s.integrate(f,x),
                         'SOLVE':lambda f,x:s.solve(f,x), 'SUBST':lambda f,p:f.subs(p[0],p[1]),
                         'AND':lambda a,b:s.Integer(int(a)&int(b)),
                         'OR':lambda a,b:s.Integer(int(a)|int(b)),
                         'XOR':lambda a,b:s.Integer(int(a)^int(b))}.items(): binary(name,fn)
        for name, fn in {'NEG':lambda x:-x, 'INV':lambda x:self._divide(1,x), 'SQ':lambda x:x*x,
                         'SQRT':s.sqrt, 'ABS':s.Abs, 'LN':s.log, 'LOG':lambda x:s.log(x,10),
                         'EXP':s.exp, 'ALOG':lambda x:10**x, 'FACT':s.factorial,
                         'SIN':lambda x:s.sin(self._in_angle(x)), 'COS':lambda x:s.cos(self._in_angle(x)),
                         'TAN':lambda x:s.tan(self._in_angle(x)), 'ASIN':lambda x:self._out_angle(s.asin(x)),
                         'ACOS':lambda x:self._out_angle(s.acos(x)), 'ATAN':lambda x:self._out_angle(s.atan(x)),
                         'SINH':s.sinh, 'COSH':s.cosh, 'TANH':s.tanh, 'ASINH':s.asinh,
                         'ACOSH':s.acosh, 'ATANH':s.atanh, 'RE':s.re, 'IM':s.im, 'CONJ':s.conjugate,
                         'ARG':lambda x:self._out_angle(s.arg(x)), 'FLOOR':s.floor, 'CEIL':s.ceiling,
                         'IP':lambda x:s.Integer(int(x)), 'FP':lambda x:x-int(x),
                         'DET':lambda x:x.det(), 'TRANS':lambda x:x.T, 'MINV':lambda x:x.inv(),
                         'RANK':lambda x:s.Integer(x.rank()), 'TRACE':lambda x:s.trace(x),
                         'EIGENVAL':lambda x:list(x.eigenvals().keys()),
                         'NORM':lambda x:s.Matrix(x).norm(), 'SUM':lambda x:sum(x),
                         'MEAN':lambda x:sum(x)/len(x), 'SDEV':self._sdev,
                         'VAR':lambda x:self._sdev(x)**2, 'MEDIAN':self._median,
                         'SIZE':lambda x:s.Integer(len(x)), 'SORT':lambda x:sorted(x),
                         'EXPAND':s.expand, 'FACTOR':s.factor, 'SIMPLIFY':s.simplify,
                         'NUM':lambda x:x.evalf(12), 'NOT':lambda x:s.Integer(~int(x)),
                         'D→R':lambda x:x*s.pi/180, 'R→D':lambda x:x*180/s.pi}.items(): unary(name, fn)
        self.commands['DINT'] = (4, lambda f,x,a,b:s.integrate(f,(x,a,b)))
        self.commands['ROOT'] = (3, lambda f,x,guess:s.nsolve(f,x,guess))

    @staticmethod
    def _divide(a,b):
        if b == 0: raise CalculatorError('Division by zero')
        return a/b

    @staticmethod
    def _sdev(values):
        if len(values)<2: raise CalculatorError('Sample deviation needs at least two values')
        mean=sum(values)/len(values)
        return s.sqrt(sum((v-mean)**2 for v in values)/(len(values)-1))

    @staticmethod
    def _median(values):
        values=sorted(values); n=len(values)
        if not n: raise CalculatorError('Empty data')
        return values[n//2] if n%2 else (values[n//2-1]+values[n//2])/2

    def _in_angle(self,x): return x*{'DEG':s.pi/180,'RAD':1,'GRAD':s.pi/200}[self.angle]
    def _out_angle(self,x): return x/{'DEG':s.pi/180,'RAD':1,'GRAD':s.pi/200}[self.angle]

    def require(self,n):
        if len(self.stack)<n: raise CalculatorError(f'Need {n} stack value(s)')

    def execute(self,source):
        before=copy.deepcopy((self.stack,self.variables,self.angle,self.numeric))
        self._steps=0
        try:
            self._run(source)
        except Exception as exc:
            self.stack,self.variables,self.angle,self.numeric=before
            raise CalculatorError(str(exc)) from exc
        self.history.append(before)
        self.history=self.history[-100:]

    def undo(self):
        if self.history: self.stack,self.variables,self.angle,self.numeric=self.history.pop()

    def _run(self,source):
        for token in tokenize(source):
            self._steps+=1
            if self._steps>1000: raise CalculatorError('Program step limit exceeded')
            command=token.upper()
            if command in self.commands:
                n,fn=self.commands[command]; self.require(n)
                args=self.stack[-n:]; result=fn(*args)
                if isinstance(result,s.Basic) and result.has(s.zoo,s.nan,s.oo,-s.oo):
                    raise CalculatorError('Undefined or infinite result')
                del self.stack[-n:]; self.stack.append(result)
            elif command in ('DEG','RAD','GRAD'): self.angle=command
            elif command=='CLEAR': self.stack.clear()
            elif command=='DUP': self.require(1); self.stack.append(copy.deepcopy(self.stack[-1]))
            elif command=='DROP': self.require(1); self.stack.pop()
            elif command=='SWAP': self.require(2); self.stack[-2:]=self.stack[-2:][::-1]
            elif command=='OVER': self.require(2); self.stack.append(copy.deepcopy(self.stack[-2]))
            elif command=='ROT': self.require(3); self.stack.append(self.stack.pop(-3))
            elif command=='DEPTH': self.stack.append(s.Integer(len(self.stack)))
            elif command=='STO':
                self.require(2); value,name=self.stack[-2:]
                if not isinstance(name,s.Symbol): raise CalculatorError('STO needs a quoted variable name')
                self.variables[str(name)]=value; del self.stack[-2:]
            elif command in ('RCL','PURGE'):
                self.require(1); name=str(self.stack[-1])
                if name not in self.variables: raise CalculatorError(f'Unknown variable: {name}')
                self.stack.pop()
                if command=='RCL': self.stack.append(copy.deepcopy(self.variables[name]))
                else: del self.variables[name]
            elif command=='EVAL':
                self.require(1); value=self.stack.pop()
                if isinstance(value,Program): self._run(value.source)
                elif isinstance(value,s.Basic): self.stack.append(value.subs({s.Symbol(k):v for k,v in self.variables.items() if isinstance(v,s.Basic)}))
                else: self.stack.append(value)
            elif token.startswith('«'): self.stack.append(Program(token[1:-1].strip()))
            elif token.startswith(("'",'"')): self.stack.append(expression(token[1:-1]))
            elif token in self.variables:
                value=copy.deepcopy(self.variables[token])
                if isinstance(value,Program): self._run(value.source)
                else: self.stack.append(value)
            else: self.stack.append(expression(token))
            if len(self.stack)>10000: raise CalculatorError('Stack size limit exceeded')
