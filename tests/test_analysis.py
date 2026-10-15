import numpy as np
import pytest
from hp48g.analysis import analyze,convert,sample,statistics


def test_root_integral_derivative():
    assert analyze('x^2-2','Root',0,2)==pytest.approx(2**.5)
    assert analyze('x^2','Integral',0,3)==pytest.approx(9)
    assert float(analyze('x^3','Derivative at a',2,4))==pytest.approx(12)


def test_sampling():
    assert np.allclose(sample('3',np.arange(5)),3)
    assert np.isnan(sample('sqrt(x)',np.array([-1.,1.]))[0])
    assert np.isnan(sample('1/x',np.array([0.,1.]))[0])


def test_units():
    assert convert(1,'ft','in')==pytest.approx(12)
    assert convert(32,'°F','°C')==pytest.approx(0)
    with pytest.raises(ValueError): convert(1,'m','s')


def test_regression():
    result,values=statistics('1,2\n2,4\n3,6')
    assert 'r²: 1' in result and 'y = 2 x + 0' in result


def test_ode():
    from hp48g.analysis import solve_ode
    x,y=solve_ode('y',0,1,1)
    assert y[-1]==pytest.approx(np.e,rel=1e-7)


def test_finance():
    from hp48g.analysis import tvm
    assert tvm(12,1,1000,0,0,'Future value')==pytest.approx(-1000*1.01**12)
    assert tvm(12,0,1200,0,0,'Payment')==pytest.approx(-100)
    assert tvm(0,1,1000,0,-1000*1.01**12,'Periods')==pytest.approx(12)
    assert tvm(12,0,1000,0,-1000*1.01**12,'Rate (%)')==pytest.approx(1)


def test_distributions():
    from hp48g.analysis import probability
    assert probability('Normal','CDF',0,0,1)==pytest.approx(.5)
    assert probability('Binomial','Density / mass',2,4,.5)==pytest.approx(.375)
    assert probability('Normal','Inverse CDF',.5,0,1)==pytest.approx(0)


def test_plot_variables_and_angle_modes():
    import sympy as s
    from hp48g.analysis import function
    f=function('a*sin(x)',angle='DEG',memory={'a':s.Integer(3)})
    assert f(90)==pytest.approx(3)
    with pytest.raises(ValueError,match='cyclic'): function('a*x',memory={'a':s.Symbol('b'),'b':s.Symbol('a')})


def test_adaptive_sampling_splits_poles_without_breaking_steep_lines():
    from hp48g.analysis import curve_samples
    x,y=curve_samples('1/(x-0.1234)',-1,1)
    at=np.where(np.isclose(x,.1234,atol=1e-12))[0]
    assert len(at)>0 and np.isnan(y[at]).any()
    x,y=curve_samples('1000000*x',-1,1)
    assert np.isfinite(y).all() and np.allclose(y,1000000*x)


def test_graph_analysis_selected_operations():
    assert analyze('x^2','Intersection',.5,2,other='x')==pytest.approx([1,1])
    assert analyze('x','Maximum',0,10)==pytest.approx([10,10])
    assert analyze('x','Minimum',0,10)==pytest.approx([0,0])
    table=analyze('x^2','Value table',0,2)
    assert len(table)==21 and table[-1]==[2,4]

@pytest.mark.parametrize('operation',['Root','Intersection'])
def test_discontinuity_is_not_a_root(operation):
    with pytest.raises((ValueError,ZeroDivisionError)):
        analyze('1/(x-0.1234)',operation,-1,1,other='0')


def test_non_finite_data_rejected():
    from hp48g.analysis import probability
    with pytest.raises(ValueError): statistics('1\nnan')
    with pytest.raises(ValueError): convert(float('inf'),'m','ft')
    with pytest.raises(ValueError): probability('Normal','CDF',float('nan'),0,1)
