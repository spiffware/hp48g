"""Validate the complete workspace before replacing any live application state."""
import copy
import math
from .serialization import read_calculator,decode
from .engine import CalculatorError


def validate_session(data):
    if not isinstance(data,dict) or data.get('version') not in (1,2): raise CalculatorError('Unsupported session version')
    calculator=read_calculator(data)
    workspace=copy.deepcopy(data.get('workspace'))
    if workspace is None: return calculator,None
    def require(condition,message='Invalid workspace data'):
        if not condition: raise CalculatorError(message)
    def strings(mapping,keys):
        require(isinstance(mapping,dict) and set(mapping)==set(keys))
        require(all(isinstance(v,str) and len(v)<=100000 for v in mapping.values()))
    require(isinstance(workspace,dict))
    require(isinstance(workspace.get('rpl_source',''),str) and len(workspace.get('rpl_source',''))<=100000)
    strings(workspace['inputs'],('entry','statistics','unit_value','unit_from','unit_to','stats_result','stats_choice','unit_result'))
    require(workspace['inputs']['stats_choice'] in ('Data','Count','Sum','Mean','Median','Sample deviation','Sample variance','Slope','Intercept','Correlation r','r²'))
    from .analysis import UNITS
    require(workspace['inputs']['unit_from'] in UNITS and workspace['inputs']['unit_to'] in UNITS)
    graph=workspace['graph']
    from .plot import EXAMPLES
    require(graph['mode'] in EXAMPLES and graph['mode'] in graph['states'])
    require(set(graph['states']).issubset(EXAMPLES))
    for state in graph['states'].values():
        require(isinstance(state,dict))
        strings({k:v for k,v in state.items() if k!='view'},('expr','second','low','high','ymin','ymax','angle'))
        require(state['angle'] in ('Calculator','DEG','RAD','GRAD'))
        if 'view' in state:
            view=state['view']
            for key in ('x','y','domain'):
                values=view[key]; require(isinstance(values,list) and len(values)==2 and all(type(v) in (int,float) and math.isfinite(v) for v in values) and values[0]!=values[1])
            if 'z' in view:
                require(len(view['z'])==2 and all(math.isfinite(v) for v in view['z']))
                require(all(math.isfinite(view[k]) for k in ('elev','azim')))
    require(graph.get('operation','Root') in ('Root','Integral','Minimum','Maximum','Derivative at a','Value at a','Intersection','Value table'))
    require(all(type(graph.get(key,0)) is int and -1<=graph.get(key,0)<=20 for key in ('curve','other')))
    solvers=workspace['solvers']
    fields={'ode':('source','x0','y0','end'),'finance':('n','rate','pv','pmt','fv','unknown'),'probability':('distribution','operation','x','p1','p2')}
    require(set(solvers['fields'])==set(fields))
    for key,names in fields.items(): strings(solvers['fields'][key],names)
    require(solvers['fields']['finance']['unknown'] in ('Periods','Rate (%)','Present value','Payment','Future value'))
    require(solvers['fields']['probability']['distribution'] in ('Normal','Student t','Chi-square','Binomial','Poisson'))
    require(solvers['fields']['probability']['operation'] in ('CDF','Density / mass','Inverse CDF'))
    require(type(solvers['tab']) is int and 0<=solvers['tab']<3)
    require(set(solvers.get('values',{})).issubset(fields))
    for value in solvers.get('values',{}).values(): decode(value)
    require(set(solvers.get('results',{})).issubset(fields) and all(isinstance(v,str) for v in solvers.get('results',{}).values()))
    layout=workspace['layout']; require(type(layout['visible']) is bool and type(layout['tab']) is int and 0<=layout['tab']<6)
    for key in ('size','split'):
        require(len(layout[key])==2 and all(type(v) is int and 0<v<=20000 for v in layout[key]))
    for key in ('stats_value','unit_value'):
        if workspace.get(key) is not None: decode(workspace[key])
    return calculator,workspace
