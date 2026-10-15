"""Worker protocol: trusted JSON requests, safe value decoding, no Qt imports."""
import json
import sys
import numpy as np
from .engine import Calculator,expression,Program,tokenize
from .serialization import read_calculator,read_rpl,calculator_state,encode,decode
from .analysis import analyze,solve_ode,tvm,probability,statistics,convert


def compute(kind,payload):
    if kind=='engine':
        calc=Calculator(); calc.stack,calc.variables,calc.angle,calc.numeric=read_calculator(payload['state']); calc.rpl_state=read_rpl(payload['state'])
        if payload.get('replace') is None: calc.execute(payload['source'])
        else:
            source=payload['source'].strip()
            if len(tokenize(source))!=1: raise ValueError('Enter one object to replace a stack value')
            value=calc.object(source)
            calc.stack[payload['replace']]=value
        return calculator_state(calc)
    if kind=='plot':
        from .graph_data import prepare_plot
        return prepare_plot(payload)
    if kind=='analysis':
        values=dict(payload); values['memory']={k:decode(v) for k,v in values.get('memory',{}).items()}
        result=analyze(**values); return {'value':encode(result)}
    if kind=='ode':
        values=dict(payload); values['memory']={k:decode(v) for k,v in values.get('memory',{}).items()}
        x,y=solve_ode(**values); return {'x':x.tolist(),'y':y.tolist(),'value':encode(float(y[-1]))}
    if kind=='finance': return {'value':encode(tvm(**payload))}
    if kind=='probability': return {'value':encode(float(probability(**payload)))}
    if kind=='statistics':
        text,values,metrics=statistics(payload['source'],details=True); return {'text':text,'value':encode(metrics)}
    if kind=='units': return {'value':encode(convert(**payload))}
    raise ValueError('Unknown calculation')


def main():
    try:
        request=json.load(sys.stdin); result=compute(request['kind'],request['payload'])
        print(json.dumps({'result':result},default=lambda value:value.tolist() if isinstance(value,np.ndarray) else float(value)))
    except Exception as exc: print(json.dumps({'error':str(exc)}))


if __name__=='__main__': main()
