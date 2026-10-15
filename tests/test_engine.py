import pytest
import sympy as s
from hp48g.engine import Calculator,CalculatorError,expression

@pytest.mark.parametrize('source,expected',[
    ('2 3 +',5),('10 3 -',7),('10 4 /',s.Rational(5,2)),('2 8 ^',256),
    ('90 SIN',1),('RAD pi 2 / SIN',1),('GRAD 100 SIN',1),('1 ASIN',90),
    ('5 FACT',120),('5 2 COMB',10),('5 2 PERM',20),('200 15 %',30),
    ('[[1,2],[3,4]] DET',-2),('[1,2,3] [4,5,6] DOT',32),
    ('[1,2,3] MEAN',2),('[1,2,3] VAR',1),('[4,1,3,2] MEDIAN',s.Rational(5,2)),
    ("'x^3' x DIFF",3*s.Symbol('x')**2),("'x^2' x 0 3 DINT",9),
    ('(2+3*i) CONJ',2-3*s.I),('« DUP * » EVAL',None),
])
def test_calculations(source,expected):
    c=Calculator()
    if expected is None:
        with pytest.raises(CalculatorError): c.execute(source)
    else:
        c.execute(source); assert s.simplify(c.stack[-1]-expected)==0


def test_rollback_and_undo():
    c=Calculator(); c.execute('9'); c.execute('2 *')
    with pytest.raises(CalculatorError): c.execute("42 'a' STO 0 /")
    assert c.stack==[18] and c.variables=={}
    c.undo(); assert c.stack==[9]


def test_program_memory():
    c=Calculator(); c.execute("« DUP * » 'square' STO 7 square")
    assert c.stack==[49]
    c.execute("'square' RCL"); assert c.stack[-1].source=='DUP *'


def test_recursive_program_rolls_back():
    c=Calculator(); c.execute("« recurse » 'recurse' STO")
    with pytest.raises(CalculatorError): c.execute('recurse')
    assert c.stack==[]

@pytest.mark.parametrize('source',["__import__('os')",'(1).__class__','[x for x in [1]]','open(1)','lambda: 2'])
def test_restricted_parser(source):
    with pytest.raises(CalculatorError): expression(source)


def test_stack_order():
    c=Calculator(); c.execute('1 2 3 ROT'); assert c.stack==[2,3,1]
    c.execute('SWAP OVER'); assert c.stack==[2,1,3,1]
