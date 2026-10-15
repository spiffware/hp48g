"""Numerical analysis and plot sampling, independent of Qt."""
import numpy as np
import sympy as s
from scipy import integrate, optimize, stats
from .engine import expression, CalculatorError


def resolved(source, variables=('x',), angle='RAD', memory=None):
    value=expression(source,angle)
    if not isinstance(value,s.Expr): raise CalculatorError('Enter a scalar expression')
    protected={s.Symbol(v) for v in variables}
    replacements={s.Symbol(k):v for k,v in (memory or {}).items() if isinstance(v,s.Expr) and s.Symbol(k) not in protected}
    for _ in range(len(replacements)+1):
        updated=value.subs(replacements,simultaneous=True)
        if updated==value: break
        value=updated
    unknown=value.free_symbols-protected
    if unknown: raise CalculatorError(f'Unknown or cyclic variables: {", ".join(map(str,unknown))}')
    return value


def function(source, variables=('x',), angle='RAD', memory=None):
    return s.lambdify([s.Symbol(v) for v in variables],resolved(source,variables,angle,memory),modules='numpy',cse=True)


def sample(source, values, variable='x', angle='RAD', memory=None):
    with np.errstate(all='ignore'):
        result=np.asarray(function(source,(variable,),angle,memory)(values),dtype=complex)
        result=np.broadcast_to(result,np.shape(values)).copy()
        out=np.where(np.abs(result.imag)<1e-10,result.real,np.nan)
        out[~np.isfinite(out)]=np.nan
    return out


def curve_samples(source,a,b,angle='RAD',memory=None):
    """Refine curved segments and split detected poles, with bounded work."""
    f=function(source,('x',),angle,memory)
    def evaluate(x):
        with np.errstate(all='ignore'):
            raw=np.broadcast_to(np.asarray(f(x),dtype=complex),x.shape)
            return np.where((np.abs(raw.imag)<1e-10)&np.isfinite(raw),raw.real,np.nan)
    x=np.linspace(a,b,801); y=evaluate(x)
    for _ in range(6):
        mids=(x[:-1]+x[1:])/2; ym=evaluate(mids)
        with np.errstate(all='ignore'):
            deviation=np.abs(ym-(y[:-1]+y[1:])/2)
            scale=1+np.minimum(np.abs(y[:-1]),np.abs(y[1:]))
            refine=(deviation>.002*scale)|(~np.isfinite(ym)&(np.isfinite(y[:-1])|np.isfinite(y[1:])))
        if not refine.any() or len(x)+refine.sum()>20000: break
        x=np.sort(np.concatenate((x,mids[refine]))); y=evaluate(x)
    # Symbolic singularities catch poles between samples (including tan poles).
    try:
        poles=s.singularities(resolved(source,('x',),angle,memory),s.Symbol('x'))
        in_range=s.Intersection(poles,s.Interval(a,b))
        if isinstance(in_range,s.FiniteSet):
            for pole in in_range:
                at=float(pole); index=np.searchsorted(x,at)
                x=np.insert(x,index,at); y=np.insert(y,index,np.nan)
    except (NotImplementedError,TypeError,ValueError): pass
    # Unresolved near-poles are also split when midpoint error stays very large.
    mids=(x[:-1]+x[1:])/2; ym=evaluate(mids)
    with np.errstate(all='ignore'):
        broken=(np.abs(ym-(y[:-1]+y[1:])/2)>10*(1+np.minimum(np.abs(y[:-1]),np.abs(y[1:]))))
    y[1:][broken]=np.nan
    return x,y


def analyze(source, operation, a, b, angle='RAD', memory=None, other=None):
    if not np.isfinite([a,b]).all() or a>=b: raise CalculatorError('Use a finite interval with a < b')
    value=resolved(source,('x',),angle,memory); f=function(source,angle=angle,memory=memory)
    if operation=='Intersection':
        if not other: raise CalculatorError('Select a second curve for the intersection')
        g=function(other,angle=angle,memory=memory)
        root=optimize.brentq(lambda x:f(x)-g(x),a,b)
        y1,y2=float(f(root)),float(g(root))
        if not np.isfinite([y1,y2]).all() or abs(y1-y2)>1e-6*(1+min(abs(y1),abs(y2))):
            raise CalculatorError('The interval crosses a discontinuity, not a verified intersection')
        return [root,y1]
    if operation=='Root':
        root=optimize.brentq(f,a,b)
        if not np.isfinite(f(root)) or abs(f(root))>1e-6: raise CalculatorError('The interval crosses a discontinuity, not a verified root')
        return root
    if operation=='Integral':
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('error',integrate.IntegrationWarning)
            return integrate.quad(f,a,b)[0]
    if operation in ('Minimum','Maximum'):
        sign=1 if operation=='Minimum' else -1
        result=optimize.minimize_scalar(lambda x:sign*f(x),bounds=(a,b),method='bounded')
        if not result.success: raise CalculatorError(result.message)
        candidates=[(a,float(f(a))),(float(result.x),float(f(result.x))),(b,float(f(b)))]
        best=min(candidates,key=lambda point:sign*point[1])
        return list(best)
    if operation=='Derivative at a': return float(s.diff(value,s.Symbol('x')).subs('x',a).evalf(12))
    if operation=='Value at a': return float(f(a))
    if operation=='Value table':
        x=np.linspace(a,b,21); return [[float(v),float(f(v))] for v in x]
    raise CalculatorError('Unknown analysis operation')


# Scale and offset to SI, grouped by dimension.
UNITS={
    'm':('length',1,0),'cm':('length',.01,0),'mm':('length',.001,0),'km':('length',1000,0),
    'in':('length',.0254,0),'ft':('length',.3048,0),'yd':('length',.9144,0),'mi':('length',1609.344,0),
    'kg':('mass',1,0),'g':('mass',.001,0),'lb':('mass',.45359237,0),'oz':('mass',.028349523125,0),
    's':('time',1,0),'min':('time',60,0),'h':('time',3600,0),'day':('time',86400,0),
    'K':('temperature',1,0),'°C':('temperature',1,273.15),'°F':('temperature',5/9,255.3722222222222),
    'Pa':('pressure',1,0),'bar':('pressure',100000,0),'atm':('pressure',101325,0),'psi':('pressure',6894.757293,0),
    'J':('energy',1,0),'kJ':('energy',1000,0),'cal':('energy',4.184,0),'kWh':('energy',3600000,0),
    'L':('volume',.001,0),'mL':('volume',.000001,0),'gal US':('volume',.003785411784,0),
    'rad':('angle',1,0),'deg':('angle',np.pi/180,0),
}


def convert(value,source,target):
    if not np.isfinite(value): raise CalculatorError('Enter a finite value')
    d1,f1,o1=UNITS[source]; d2,f2,o2=UNITS[target]
    if d1!=d2: raise CalculatorError('Units must have the same dimension')
    return (value*f1+o1-o2)/f2


def statistics(source,details=False):
    rows=[[float(x) for x in row.replace(',',' ').split()] for row in source.splitlines() if row.strip()]
    if not rows: raise CalculatorError('Enter data first')
    data=np.asarray(rows)
    if data.ndim!=2 or data.shape[1] not in (1,2): raise CalculatorError('Enter one value or an x,y pair per line')
    if not np.isfinite(data).all(): raise CalculatorError('Data must contain finite numbers')
    values=data[:,-1]
    metrics={'Data':values.tolist(),'Count':len(values),'Sum':float(values.sum()),'Mean':float(values.mean()),'Median':float(np.median(values))}
    if len(values)>1: metrics.update({'Sample deviation':float(values.std(ddof=1)),'Sample variance':float(values.var(ddof=1))})
    result=f'Count: {len(values)}\nSum: {values.sum():.12g}\nMean: {values.mean():.12g}\nMedian: {np.median(values):.12g}'
    if len(values)>1: result+=f'\nSample deviation: {values.std(ddof=1):.12g}\nSample variance: {values.var(ddof=1):.12g}'
    if data.shape[1]==2 and len(values)>1:
        fit=stats.linregress(data[:,0],values)
        metrics.update({'Slope':float(fit.slope),'Intercept':float(fit.intercept),'Correlation r':float(fit.rvalue),'r²':float(fit.rvalue**2)})
        result+=f'\n\nLinear fit: y = {fit.slope:.10g} x + {fit.intercept:.10g}\nr: {fit.rvalue:.10g}\nr²: {fit.rvalue**2:.10g}'
    return (result,values,metrics) if details else (result,values)


def solve_ode(source, x0, y0, end, count=400, angle='RAD', memory=None):
    """Integrate a first-order initial value problem dy/dx=f(x,y)."""
    f=function(source,('x','y'),angle,memory)
    if not np.isfinite([x0,y0,end]).all(): raise CalculatorError('Initial conditions must be finite')
    if x0==end: raise CalculatorError('ODE endpoints must differ')
    result=integrate.solve_ivp(lambda x,y:[float(f(x,y[0]))],(x0,end),[y0],t_eval=np.linspace(x0,end,count),rtol=1e-8,atol=1e-10)
    if not result.success: raise CalculatorError(result.message)
    return result.t,result.y[0]


def tvm(n,rate,pv,pmt,fv,unknown):
    """End-of-period cash flows; rate is a percentage per period."""
    if not np.isfinite([n,rate,pv,pmt,fv]).all(): raise CalculatorError('Cash flows must be finite')
    def balance(n,rate,pv,pmt,fv):
        r=rate/100
        if r<=-1 or n<0: raise CalculatorError('Require rate > -100% and periods >= 0')
        if abs(r)<1e-12: return pv+pmt*n+fv
        if r>0:
            discount=np.exp(-n*np.log1p(r))
            return pv+pmt*(1-discount)/r+fv*discount
        growth=np.exp(n*np.log1p(r))
        return pv*growth+pmt*(growth-1)/r+fv
    values=[n,rate,pv,pmt,fv]; index=['Periods','Rate (%)','Present value','Payment','Future value'].index(unknown)
    def residual(value):
        args=values.copy(); args[index]=value
        return balance(*args)
    if index>=2:
        zero=residual(0); slope=residual(1)-zero
        if abs(slope)<1e-14: raise CalculatorError('Cash flows do not determine this value')
        return -zero/slope
    bracket=(0,10000) if index==0 else (-99,100)
    return optimize.brentq(residual,*bracket)


def probability(distribution,operation,x,p1,p2):
    if not np.isfinite([x,p1,p2]).all(): raise CalculatorError('Distribution parameters must be finite')
    if distribution=='Normal':
        if p2<=0: raise CalculatorError('Standard deviation must be positive')
        model=stats.norm(loc=p1,scale=p2)
    elif distribution=='Student t':
        if p1<=0: raise CalculatorError('Degrees of freedom must be positive')
        model=stats.t(df=p1)
    elif distribution=='Chi-square':
        if p1<=0: raise CalculatorError('Degrees of freedom must be positive')
        model=stats.chi2(df=p1)
    elif distribution=='Binomial':
        if p1<0 or p1!=int(p1) or not 0<=p2<=1: raise CalculatorError('Use integer n >= 0 and 0 <= p <= 1')
        model=stats.binom(n=int(p1),p=p2)
    else:
        if p1<=0: raise CalculatorError('Poisson mean must be positive')
        model=stats.poisson(mu=p1)
    if operation=='Inverse CDF':
        if not 0<x<1: raise CalculatorError('Inverse probability must be between 0 and 1')
        return model.ppf(x)
    if operation=='CDF': return model.cdf(x)
    return model.pmf(x) if distribution in ('Binomial','Poisson') else model.pdf(x)
