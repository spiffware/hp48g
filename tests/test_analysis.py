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
