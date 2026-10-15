import pytest
import sympy as s
from hp48g.engine import Calculator,CalculatorError,expression
from hp48g.serialization import encode,decode,write_json,read_json

@pytest.mark.parametrize('mode,degrees',[('DEG','90'),('RAD','pi/2'),('GRAD','100')])
def test_typed_trig_matches_keypad(mode,degrees):
    c=Calculator(); c.execute(f'{mode} {degrees} SIN sin({degrees})')
    assert c.stack==[1,1]
    c.execute('1 ASIN asin(1)')
    assert s.simplify(c.stack[-1]-c.stack[-2])==0

@pytest.mark.parametrize('source,expected',[
    ('[1,2] [3,4] +',[4,6]),('[1,2] [3,4] -',[-2,-2]),
    ('[1,2] 2 *',[2,4]),('2 [1,2] *',[2,4]),('[2,4] 2 /',[1,2]),
    ('([1,2]*2)',[2,4]),('[1,2] NEG',[-1,-2]),
])
def test_vector_arithmetic(source,expected):
    c=Calculator(); c.execute(source); assert c.stack==[expected]

@pytest.mark.parametrize('source',['[1,2] [3] +','[1,2] [3,4] *','[1,2] 1 +','[1,2] 0 /'])
def test_vector_errors_rollback(source):
    c=Calculator(); c.execute('42')
    with pytest.raises(CalculatorError): c.execute(source)
    assert c.stack==[42]


def test_unknown_commands_and_symbols():
    c=Calculator()
    with pytest.raises(CalculatorError,match='Unknown command'): c.execute('SNI')
    c.execute("'velocity' x 'x^2' 42 'answer' STO answer")
    assert c.stack[-1]==42
    with pytest.raises(CalculatorError,match='reserved'): c.execute("42 'SIN' STO")


def test_deep_stack_commands():
    c=Calculator(); c.execute(' '.join(map(str,range(1,21))))
    c.execute('20 PICK'); assert c.stack[-1]==1 and len(c.stack)==21
    c.execute('DROP 20 ROLL'); assert c.stack[-1]==1 and len(c.stack)==20
    c.undo(); assert c.stack[-1]==1 and len(c.stack)==21


def test_eigenvalues_preserve_multiplicity():
    c=Calculator(); c.execute('[[2,0],[0,2]] EIGENVAL'); assert c.stack==[[2,2]]


def test_symbolic_session_roundtrips(tmp_path):
    x=s.Symbol('x'); y=s.Symbol('y',positive=True)
    values=[s.Integral(s.sin(x**x),x),s.Derivative(s.sin(x**x),x,evaluate=False),
            s.Piecewise((x,x>0),(0,True)),s.Sum(x,(x,1,10)),s.CRootOf(x**5-x+1,0),
            s.Float('0.12345678901234567890123456789',40),s.Matrix([[s.Rational(1,3),y]]),{x:[1,2]},s.Dummy('k')]
    path=tmp_path/'session.json'; write_json(path,{'values':[encode(v) for v in values]})
    loaded=[decode(v) for v in read_json(path)['values']]
    assert loaded==values


def test_legacy_unevaluated_integral():
    x=s.Symbol('x')
    assert decode({'expr':'Integral(sin(x**x), x)'})==s.Integral(s.sin(x**x),x)

@pytest.mark.parametrize('payload',[{'node':{'name':'__import__','args':[]}},{'expr':"__import__('os').system('echo bad')"},{'expr':'open(1)'}])
def test_session_decoder_rejects_code(payload):
    with pytest.raises((CalculatorError,ValueError)): decode(payload)


def test_atomic_save_preserves_existing_file_on_failure(tmp_path):
    path=tmp_path/'session.json'; write_json(path,{'valid':1})
    with pytest.raises(ValueError): write_json(path,{'bad':float('nan')})
    assert read_json(path)=={'valid':1}
