"""Generate ROM graph operations without changing the user's independent variable."""
import math
import uuid
from .rom_codec import quote_text,quote_name


def algebra(source):
    source=source.strip()
    if not source or len(source)>8000 or any(c in source for c in "'«»\n\r\x00"):
        raise ValueError('Enter an unquoted algebraic expression.')
    return quote_text("'"+source+"'")+' STR→'


def number(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('Enter a finite number')
    return format(value,'.12g')


def preserve_variable(source,variable='X'):
    name=quote_name(variable);tag=uuid.uuid4().hex
    old='saved'+tag;had='exists'+tag;err='error'+tag
    restore=f'IF {had} THEN {old} {name} STO ELSE {name} PURGE END'
    return (f'VARS {name} POS DUP IF THEN DROP {name} RCL 1 ELSE DROP 0 0 END '
            f'→ {old} {had} « IFERR {source} THEN ERRM → {err} « {restore} {err} DOERR » ELSE {restore} END »')


def analysis_source(kind,expression,other='',a=0,b=1,variable='X'):
    name=quote_name(variable);lo=number(a);hi=number(b)
    expr=algebra(expression)
    if kind=='Trace':source=f'{lo} {name} STO {expr} EVAL →NUM'
    elif kind=='Root':source=f'{expr} {name} {{ {lo} {hi} }} ROOT'
    elif kind=='Intersection':source=f'{expr} {algebra(other)} - {name} {{ {lo} {hi} }} ROOT'
    elif kind=='Stationary point':source=f'{name} PURGE {expr} {name} ∂ {name} {{ {lo} {hi} }} ROOT'
    elif kind=='Extremum':source=(f'{name} PURGE {expr} {name} ∂ DUP {name} ∂ SWAP {name} {{ {lo} {hi} }} ROOT '
                                  f'→ curvature position « position {name} STO position {expr} EVAL curvature EVAL 3 →LIST »')
    elif kind=='Integral':source=f'{lo} {hi} {expr} {name} ∫ →NUM'
    else:raise ValueError('Unknown analysis operation')
    return preserve_variable(source,variable)
