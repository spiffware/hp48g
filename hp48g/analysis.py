"""Numerical analysis and plot sampling, independent of Qt."""
import numpy as np
import sympy as s
from scipy import integrate, optimize, stats
from .engine import expression, CalculatorError


def function(source, variables=('x',)):
    value=expression(source)
    if not isinstance(value,s.Expr): raise CalculatorError('Enter a scalar expression')
    symbols=[s.Symbol(v) for v in variables]
    unknown=value.free_symbols-set(symbols)
    if unknown: raise CalculatorError(f'Unknown plot variables: {", ".join(map(str,unknown))}')
    return s.lambdify(symbols,value,modules='numpy',cse=True)


def sample(source, values, variable='x'):
    with np.errstate(all='ignore'):
        result=np.asarray(function(source,(variable,))(values),dtype=complex)
        result=np.broadcast_to(result,np.shape(values)).copy()
        out=np.where(np.abs(result.imag)<1e-10,result.real,np.nan)
        out[~np.isfinite(out)]=np.nan
    return out


def analyze(source, operation, a, b):
    f=function(source)
    if operation=='Root': return optimize.brentq(f,a,b)
    if operation=='Integral': return integrate.quad(f,a,b)[0]
    if operation=='Minimum':
        result=optimize.minimize_scalar(f,bounds=(a,b),method='bounded')
        if not result.success: raise CalculatorError(result.message)
        return f'x = {result.x:.12g}, y = {result.fun:.12g}'
    if operation=='Maximum':
        result=optimize.minimize_scalar(lambda x:-f(x),bounds=(a,b),method='bounded')
        if not result.success: raise CalculatorError(result.message)
        return f'x = {result.x:.12g}, y = {-result.fun:.12g}'
    if operation=='Derivative at a': return s.diff(expression(source),s.Symbol('x')).subs('x',a).evalf(12)
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
    d1,f1,o1=UNITS[source]; d2,f2,o2=UNITS[target]
    if d1!=d2: raise CalculatorError('Units must have the same dimension')
    return (value*f1+o1-o2)/f2


def statistics(source):
    rows=[[float(x) for x in row.replace(',',' ').split()] for row in source.splitlines() if row.strip()]
    if not rows: raise CalculatorError('Enter data first')
    data=np.asarray(rows)
    if data.ndim!=2 or data.shape[1] not in (1,2): raise CalculatorError('Enter one value or an x,y pair per line')
    values=data[:,-1]
    result=f'Count: {len(values)}\nSum: {values.sum():.12g}\nMean: {values.mean():.12g}\nMedian: {np.median(values):.12g}'
    if len(values)>1: result+=f'\nSample deviation: {values.std(ddof=1):.12g}\nSample variance: {values.var(ddof=1):.12g}'
    if data.shape[1]==2 and len(values)>1:
        fit=stats.linregress(data[:,0],values)
        result+=f'\n\nLinear fit: y = {fit.slope:.10g} x + {fit.intercept:.10g}\nr: {fit.rvalue:.10g}\nr²: {fit.rvalue**2:.10g}'
    return result,values


def solve_ode(source, x0, y0, end, count=400):
    """Integrate a first-order initial value problem dy/dx=f(x,y)."""
    f=function(source,('x','y'))
    if x0==end: raise CalculatorError('ODE endpoints must differ')
    result=integrate.solve_ivp(lambda x,y:[float(f(x,y[0]))],(x0,end),[y0],t_eval=np.linspace(x0,end,count),rtol=1e-8,atol=1e-10)
    if not result.success: raise CalculatorError(result.message)
    return result.t,result.y[0]


def tvm(n,rate,pv,pmt,fv,unknown):
    """End-of-period cash flows; rate is a percentage per period."""
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
