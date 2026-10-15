"""Prepare numerical plot data off the UI thread before changing any graph."""
import numpy as np
from .analysis import function,sample,curve_samples
from .engine import CalculatorError
from .serialization import decode


def prepare_plot(request):
    mode=request['mode']; a,b=request['domain']; source=request['expr']; second=request['second']
    if not np.isfinite([a,b]).all() or a>=b: raise CalculatorError('Domain must be finite with a < b')
    angle=request['angle']; memory={k:decode(v) for k,v in request.get('memory',{}).items()}
    options={'angle':angle,'memory':memory}
    data={'mode':mode,'domain':[a,b],'series':[]}
    if mode=='Function':
        parts=[part.strip() for field in (source,second) for part in field.split(';') if part.strip()]
        if not parts: raise CalculatorError('Enter at least one function')
        if len(parts)>20: raise CalculatorError('Plot at most 20 functions at a time')
        for part in parts:
            x,y=curve_samples(part,a,b,**options)
            data['series'].append({'label':part,'x':x.tolist(),'y':y.tolist()})
    elif mode in ('Polar','Parametric'):
        t=np.linspace(a,b,4001)
        first=sample(source,t,'t',**options)
        # Matplotlib's polar coordinate axis always uses radians.
        x=t*{'RAD':1,'DEG':np.pi/180,'GRAD':np.pi/200}[angle] if mode=='Polar' else first
        y=first if mode=='Polar' else sample(second,t,'t',**options)
        data['series'].append({'label':source,'x':x.tolist(),'y':y.tolist()})
    elif mode in ('Implicit','3D surface','Slope field'):
        grid=np.linspace(a,b,25 if mode=='Slope field' else 151); X,Y=np.meshgrid(grid,grid)
        with np.errstate(all='ignore'):
            raw=np.broadcast_to(np.asarray(function(source,('x','y'),**options)(X,Y),dtype=complex),X.shape)
            Z=np.where((np.abs(raw.imag)<1e-10)&np.isfinite(raw),raw.real,np.nan)
        if not np.isfinite(Z).any(): raise CalculatorError('No finite real values in this domain')
        data.update(x=X.tolist(),y=Y.tolist(),z=Z.tolist())
    elif mode in ('Histogram','Scatter'):
        def numbers(text):
            try: values=[float(v) for v in text.replace(',',' ').split()]
            except ValueError as exc: raise CalculatorError('Enter numbers separated by commas or spaces') from exc
            if not values or not np.isfinite(values).all(): raise CalculatorError('Enter finite data values')
            return values
        data['x']=numbers(source)
        if mode=='Scatter':
            data['y']=numbers(second)
            if len(data['x'])!=len(data['y']): raise CalculatorError('Scatter x and y lists must have equal lengths')
    else: raise CalculatorError('Unknown plot type')
    return data
