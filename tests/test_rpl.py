import copy
import pytest
import sympy as s
from hp48g.engine import Calculator, CalculatorError, Program, format_value
from hp48g.rpl_objects import RPLList, BinaryInteger, Command, Tagged
from hp48g.serialization import calculator_state,read_calculator,read_rpl,encode,decode
from hp48g.worker import compute


def run(source):
    calc=Calculator(); calc.execute(source); return calc


@pytest.mark.parametrize('source,expected',[
    ('IF 0 THEN 11 ELSE 12 END',[12]),
    ('IF 1 THEN IF 0 THEN 11 ELSE 12 END ELSE 13 END',[12]),
    ('0 1 5 FOR j j + NEXT',[15]),
    ('0 5 1 FOR j j + -1 STEP',[15]),
    ('0 1 4 START 1 + NEXT',[4]),
    ('0 DO 1 + UNTIL DUP 4 == END',[4]),
    ('0 WHILE DUP 4 < REPEAT 1 + END',[4]),
    ('0 WHILE DUP 0 > REPEAT 1 + END',[0]),
    ('CASE 0 THEN 11 END 1 THEN 12 END 13 END',[12]),
    ('CASE 0 THEN 11 END 0 THEN 12 END 13 END',[13]),
    ('1 « 2 3 + » IFT',[5]),
    ('0 « 2 » « 3 » IFTE',[3]),
    ('8 3 → a b « a b - »',[5]),
    ("8 -> a 'a^2'",[64]),
    ('8 → a « 2 → a « a SQ » a + »',[12]),
    ('<< 1 2 + >> EVAL',[3]),
    ('IFERR 1 0 / THEN DROP2 42 ELSE 99 END',[42]),
    ('IFERR 1 2 + THEN 42 ELSE 99 END',[3,99]),
    ('1 2 3 3 ROLLD',[3,1,2]),
    ('1 2 3 UNROT',[3,1,2]),
    ('1 2 2 DUPN',[1,2,1,2]),
    ('1 2 0 DUPN',[1,2]),
    ('1 2 0 DROPN',[1,2]),
    ('1 2 3 3 DROPN',[]),
    ('3 2 AND 0 NOT',[1,1]),
    ('1 SF 1 FS? 1 FC?C 1 FS?',[1,0,0]),
    ('8 STWS # FFh # 1h + B→R',[0]),
    ('8 STWS # 80h RL B→R',[1]),
    ('8 STWS # 80h ASR B→R',[192]),
    ('8 STWS # F0h NOT B→R',[15]),
    ('BIN # 101 B→R',[5]),
    ('# 255d B→R',[255]),
    ('(3,4) C→R',[3,4]),
    ('3 4 R→C ABS',[5]),
    ('"hello" " world" +',['hello world']),
    ('"abc" 2 3 SUB',['bc']),
    ('"abc" "b" POS',[2]),
    ('"abc" "z" POS',[0]),
    ('65 CHR NUM',[65]),
    ('1.235 2 RND',[s.Rational(124,100)]),
    ('-1.239 2 TRNC',[-s.Rational(123,100)]),
])
def test_rpl_execution(source,expected):
    assert run(source).stack==expected


@pytest.mark.parametrize('source,expected',[
    ('{ 1 2 } { 3 } +',RPLList([1,2,3])),
    ('{ 1 2 } 3 +',RPLList([1,2,3])),
    ('0 { 1 2 } +',RPLList([0,1,2])),
    ('{ 1 2 } 3 ADD',RPLList([4,5])),
    ('{ 1 2 3 } « SQ » DOLIST',RPLList([1,4,9])),
    ('{ 1 2 } { 3 4 } 2 « + » DOLIST',RPLList([4,6])),
    ('{ 1 2 3 4 } « + » STREAM',10),
    ("'j^2' 'j' 1 4 1 SEQ",RPLList([1,4,9,16])),
    ('1 2 3 3 →LIST',RPLList([1,2,3])),
    ('{ 1 2 3 } 2 9 PUT',RPLList([1,9,3])),
    ('[1 2 3] 2 GET',2),
    ('[[1 2] [3 4]] { 2 1 } GET',3),
    ('1 2 3 4 { 2 2 } →ARRY',s.Matrix([[1,2],[3,4]])),
    ('{ 1 « 2 » "x" { 3 } }',RPLList([1,Program('2'),'x',RPLList([3])])),
])
def test_objects(source,expected):
    actual=run(source).stack[-1]
    assert actual==expected
    assert type(actual)==type(expected) or isinstance(actual,s.Basic)


def test_list_geti_puti_and_named_put():
    assert run('{ 10 20 } 2 GETI').stack==[RPLList([10,20]),1,20]
    assert run('{ 10 20 } 2 30 PUTI').stack==[RPLList([10,30]),1]
    assert run("{ 10 20 } 'v' STO 'v' 2 30 PUT v").stack==[RPLList([10,30])]


def test_local_store_does_not_escape():
    calc=run("7 'a' STO 2 → a « 3 'a' STO a » a")
    assert calc.stack==[3,7] and not calc.locals


def test_directory_inheritance_and_workspace_transport():
    calc=run("7 'parent' STO 'child' CRDIR child 8 'own' STO parent own")
    data=compute('engine',{'state':calculator_state(calc),'source':"HOME child own UPDIR parent"})
    assert read_calculator(data)[0]==[7,8,8,7]
    assert read_rpl(data)['path']==[]


def test_undo_and_failure_include_flags_directories_modes():
    calc=run('8 STWS 1 SF HEX'); before=calc.snapshot()
    with pytest.raises(CalculatorError): calc.execute("'child' CRDIR child 2 SF 32 STWS 1 0 /")
    assert calc.snapshot()==before
    calc.undo(); assert calc.rpl_state['flags']==[] and calc.rpl_state['wordsize']==64


@pytest.mark.parametrize('source',['IF 1 2 END','THEN','1 3 FOR j j','1 → a','WHILE 1 END','CASE 1 THEN 2 END'])
def test_malformed_control_is_rejected_before_execution(source):
    calc=run('5')
    with pytest.raises(CalculatorError): calc.execute(source)
    assert calc.stack==[5]


def test_empty_infinite_loop_is_bounded():
    with pytest.raises(CalculatorError,match='limit exceeded'): run('DO UNTIL 0 END')


def test_command_args_preserved_inside_error_handler():
    assert run('IFERR { 1 } 9 GET THEN DEPTH END').stack==[RPLList([1]),9,2]


@pytest.mark.parametrize('value',[RPLList([s.Integer(1),Program('2')]),BinaryInteger(255),Command('SIN'),Tagged('answer',s.Integer(42))])
def test_object_serialization_roundtrip(value):
    result=decode(encode(value)); assert result==value and type(result)==type(value)


def test_native_object_type_codes():
    assert run('3 TYPE (3,4) TYPE "hi" TYPE [1 2] TYPE { 1 2 } TYPE \'a\' TYPE « 2 » TYPE # FFh TYPE').stack==[0,1,2,3,5,6,8,10]


def test_array_expression_regression():
    assert run('([1,2]*2)').stack==[[2,4]]


def test_string_escapes_and_program_delimiters():
    assert run(r'"a\" << b"').stack==['a" << b']
    assert run('"2 3 +" STR→').stack==[5]


def test_loop_index_i_shadows_complex_constant():
    assert run('0 1 4 FOR i i + NEXT').stack==[10]


def test_automatic_list_processing():
    calc=run('{ 30 90 } SIN { 1 2 } 3 *')
    assert calc.stack==[RPLList([s.Rational(1,2),1]),RPLList([3,6])]
    assert all(isinstance(v,RPLList) for v in calc.stack)


def test_directory_objects_eval_and_sibling_lookup():
    calc=run("'one' CRDIR 'two' CRDIR one 1 'value' STO two 2 'value' STO HOME 'one' RCL EVAL value")
    assert calc.stack==[1] and calc.rpl_state['path']==['one']


def test_known_unsupported_commands_are_explicit():
    with pytest.raises(CalculatorError,match='not implemented'): run('SYSEVAL')


@pytest.mark.parametrize('source,expected',[
    ("'x^3' 'x' ∂",3*s.Symbol('x')**2),
    ("0 3 'x^2' 'x' ∫",9),
    ('-8 3 XROOT',-2),
    ('[1 -3 2] PROOT',[1,2]),
    ('[1 2] PCOEF',[1,-3,2]),
    ('[1 -3 2] 4 PEVAL',6),
    ("'a=42' DEFINE a",42),
    ("RAD 'sin(x)' 'x' 3 TAYLR",s.Symbol('x')-s.Symbol('x')**3/6),
    ('[[1 2] [3 4]] RREF',s.eye(2)),
])
def test_hp_math_commands(source,expected):
    assert run(source).stack[-1]==expected


def test_equations_and_symbolic_comparisons():
    assert run("'x=2' 2 'x' =").stack==[s.Eq(s.Symbol('x'),2),s.Eq(2,s.Symbol('x'),evaluate=False)]
    assert run("'x' 2 <").stack==[s.Symbol('x')<2]


def test_tags_roundtrip_through_text():
    value=run(':answer:42').stack[-1]
    assert run(format_value(value)).stack==[value]
    assert run(':program:« 2 3 + » DTAG EVAL').stack==[5]


def test_inherited_variables_for_graph_context():
    calc=run("7 'a' STO 'child' CRDIR child 8 'b' STO")
    assert calc.visible_variables()['a']==7 and calc.visible_variables()['b']==8
