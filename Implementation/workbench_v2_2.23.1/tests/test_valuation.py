import copy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.valuation import Assumptions,calculate
from app.api import valuation as api

@pytest.fixture
def data():
    return dict(ticker='TEST',retrieved_at='2026-01-01T00:00:00+00:00',quote=dict(value=50,currency='USD'),anchors=[dict(id='annual:2026-01-01',value=2,currency='USD',period_end='2026-01-01',category='historical_reported')])
def assumptions(**changes):
    return Assumptions(**(dict(anchor_id='annual:2026-01-01',years=3,required_return=.1,growth=.1,exit_pe=20,growth_spread=.05,pe_spread=.2,acknowledge_basis=True)|changes))
def test_formula_and_reverse(data):
    r=calculate(data,assumptions());years=r['growth_years'];expected=2*1.1**years*20
    assert r['scenarios'][1]['future_price']==pytest.approx(expected)
    assert r['scenarios'][1]['discounted_terminal']==pytest.approx(expected/1.1**3)
    assert 2*(1+r['reverse']['required_eps_growth'])**years*20==pytest.approx(50*1.1**3)
    assert r['scenarios'][0]['future_price']<expected<r['scenarios'][2]['future_price']
@pytest.mark.parametrize('value',[None,0,-2])
def test_missing_or_loss_eps(data,value):
    data['anchors'][0]['value']=value
    with pytest.raises(ValueError):calculate(data,assumptions())
def test_currency_mismatch(data):
    data['anchors'][0]['currency']='CAD'
    with pytest.raises(ValueError,match='currencies'):calculate(data,assumptions())
def test_missing_quote(data):
    data['quote']['value']=None
    with pytest.raises(ValueError,match='price'):calculate(data,assumptions())
def test_no_ack(data):
    with pytest.raises(ValueError,match='Confirm'):calculate(data,assumptions(acknowledge_basis=False))
def test_growth_boundary(data):
    with pytest.raises(ValueError):calculate(data,assumptions(growth=-.8,growth_spread=.3))
@pytest.mark.parametrize('changes',[{'growth':float('nan')},{'exit_pe':float('inf')},{'years':0},{'pe_spread':1}])
def test_invalid_assumptions(changes):
    with pytest.raises(ValueError):assumptions(**changes)
def test_no_mutation(data):
    old=copy.deepcopy(data);calculate(data,assumptions());assert data==old

def test_api_append_only_and_offline_replay(tmp_path,monkeypatch,data):
    monkeypatch.setattr(api,'DB',tmp_path/'valuation.db');monkeypatch.setattr(api,'fetch',lambda _:data)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    snap=client.post('/api/v1/valuation/TEST/fetch').json()
    req=dict(data_id=snap['id'],assumptions=assumptions().model_dump())
    one=client.post('/api/v1/valuation/calculate',json=req);two=client.post('/api/v1/valuation/calculate',json=req)
    assert one.status_code==two.status_code==200
    assert one.json()['id']!=two.json()['id']
    assert one.json()['payload']['result']==two.json()['payload']['result']
    assert client.get('/api/v1/valuation/snapshots/'+snap['id']).json()['payload']==data   # data snapshot unchanged
    assert len(client.get('/api/v1/valuation/TEST/history').json())==3
    req['data_id']=one.json()['id']
    assert client.post('/api/v1/valuation/calculate',json=req).status_code==422
    assert client.get('/api/v1/valuation/snapshots/missing').status_code==404

def test_provider_mapping_and_consensus_currency(monkeypatch):
    import pandas as pd
    import yfinance
    from types import SimpleNamespace
    from app.adapters.valuation_adapter import fetch,OpenBBAdapter
    def call(operation,fn):
        rows=[dict(last_price=50,currency='USD')] if operation=='quote' else [dict(period_ending='2026-01-31',diluted_earnings_per_share=2.5,total_revenue=1000)]
        return SimpleNamespace(results=rows,provider='yfinance',warnings=None,extra=None)
    monkeypatch.setattr(OpenBBAdapter,'_call',staticmethod(call))
    class Stock:
        def get_info(self): return dict(currency='USD',financialCurrency='USD',regularMarketPrice=50,regularMarketTime=1791576000)
        def get_earnings_estimate(self): return pd.DataFrame([dict(avg=3,currency='USD',numberOfAnalysts=10)],index=['0y'])
        get_revenue_estimate=get_earnings_estimate
    monkeypatch.setattr(yfinance,'Ticker',lambda _:Stock())
    d=fetch('TEST')
    assert d['anchors'][0]['value']==2.5
    assert d['historical'][0]['revenue']==1000
    assert d['quote']['observed_at']=='2026-10-09T20:00:00+00:00'
    assert len(d['estimates'])==2
    assert d['estimates'][0]['published_at'] is None
    assert d['estimates'][0]['period_end'] is None
    assert all(x['category']=='historical_reported' for x in d['anchors'])

def test_provider_failure_does_not_invent(monkeypatch):
    import yfinance
    from app.adapters.valuation_adapter import fetch,OpenBBAdapter
    def fail(*a,**k): raise RuntimeError('offline test')
    monkeypatch.setattr(OpenBBAdapter,'_call',staticmethod(fail))
    monkeypatch.setattr(yfinance,'Ticker',fail)
    d=fetch('TEST')
    assert d['quote']['value'] is None and d['anchors']==[] and d['estimates']==[]
    assert any('offline test' in w for w in d['warnings'])

from datetime import date
from app.core.valuation import EbitdaAssumptions,anniversary,consensus_bridge
from app.core.valuation_context import historical_pe

def ev_assumptions(**changes):
    return EbitdaAssumptions(**(dict(method='ev_ebitda',anchor_id='revenue:2026-01-01',years=2,required_return=.1,
        growth=.1,growth_spread=.05,margin=.2,margin_spread=.05,exit_multiple=15,multiple_spread=.1,
        target_net_debt=100,target_shares=10,other_claims=20,balance_assumption='user_forecast',acknowledge_basis=True)|changes))

@pytest.fixture
def ev_data(data):
    data['revenue_anchors']=[dict(id='revenue:2026-01-01',value=1000,currency='USD',period_end='2026-01-01')]
    data['market_baseline']=dict(currency='USD',net_debt=100,shares=10)
    return data

def test_calendar_anniversary():
    assert anniversary(date(2026,10,10),2)==date(2028,10,10)
    assert anniversary(date(2024,2,29),1)==date(2025,2,28)

def test_ev_equity_bridge_and_reverse(ev_data):
    a=ev_assumptions();r=calculate(ev_data,a);b=r['scenarios'][1]
    assert b['revenue']==pytest.approx(1000*1.1**r['growth_years'])
    assert b['ebitda']==pytest.approx(b['revenue']*.2)
    assert b['future_price']==pytest.approx((b['ebitda']*15-100-20)/10)
    needed=r['reverse']['required_ebitda']
    assert (needed*15-100-20)/10==pytest.approx(50*1.1**2)
    assert r['reverse']['required_margin']*b['revenue']==pytest.approx(needed)
    assert b['ebitda']*r['reverse']['required_exit_multiple']-120==pytest.approx(50*1.1**2*10)
    assert r['required_exit_price']==pytest.approx(60.5)

def test_ev_net_cash_and_limited_equity(ev_data):
    cash=calculate(ev_data,ev_assumptions(target_net_debt=-100))
    debt=calculate(ev_data,ev_assumptions(target_net_debt=100))
    assert cash['scenarios'][1]['future_price']-debt['scenarios'][1]['future_price']==pytest.approx(20)
    loss=calculate(ev_data,ev_assumptions(target_net_debt=1e9))['scenarios'][1]
    assert loss['future_price']==0 and loss['price_cagr']==-1 and loss['equity_floor_applied']

@pytest.mark.parametrize('changes',[dict(margin=.02,margin_spread=.05),dict(margin=.95,margin_spread=.1),dict(balance_assumption='hold_current_constant',target_shares=11)])
def test_ev_invalid_basis(ev_data,changes):
    with pytest.raises(ValueError):calculate(ev_data,ev_assumptions(**changes))

def test_ev_fixed_balance_is_explicit(ev_data):
    assert calculate(ev_data,ev_assumptions(balance_assumption='hold_current_constant'))['assumptions']['balance_assumption']=='hold_current_constant'
    ev_data['market_baseline']['net_debt']=None
    with pytest.raises(ValueError):calculate(ev_data,ev_assumptions(balance_assumption='hold_current_constant'))

def test_historical_pe_no_future_price_or_negative_eps():
    rows=[dict(period_end='2025-12-31',diluted_eps=2,currency='USD'),dict(period_end='2024-12-31',diluted_eps=-1,currency='USD')]
    prices=[dict(date='2025-12-30',close=40),dict(date='2026-01-01',close=1000),dict(date='2024-12-31',close=20)]
    r=historical_pe(rows,prices,'USD');assert r['rows'][0]['pe']==20
    assert r['rows'][0]['price_date']=='2025-12-30'
    assert r['rows'][1]['pe'] is None and r['count']==1
    assert historical_pe(rows,prices,'CAD')['count']==0
    assert historical_pe(rows,[dict(date='2025-12-01',close=40)],'USD')['count']==0

def test_consensus_bridge_not_quarter_annualization(data):
    data['estimates']=[dict(metric='eps',period='0q',avg=1,currency='USD'),dict(metric='eps',period='+1y',avg=4,currency='USD')]
    r=consensus_bridge(data,20,.1)
    assert len(r['rows'])==1
    assert [x['price'] for x in r['rows'][0]['prices']]==[72,80,88]
    assert 'price_cagr' not in r['rows'][0]['prices'][0]
    data['estimates'][1]['currency']='CAD'
    assert 'error' in consensus_bridge(data,20,.1)['rows'][0]

def test_api_second_method_and_references(tmp_path,monkeypatch,ev_data):
    monkeypatch.setattr(api,'DB',tmp_path/'valuation.db');monkeypatch.setattr(api,'fetch',lambda _:ev_data)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    snap=client.post('/api/v1/valuation/TEST/fetch').json()
    req=dict(data_id=snap['id'],assumptions=ev_assumptions().model_dump())
    r=client.post('/api/v1/valuation/calculate',json=req)
    assert r.status_code==200 and r.json()['payload']['result']['method']=='ev_ebitda'
    assert client.post('/api/v1/valuation/reference-prices',json=dict(data_id=snap['id'],pe=25,spread=.05)).status_code==200
    assert client.post('/api/v1/valuation/TEST/fetch',json=dict(peers=['A']*6)).status_code==422

def test_reference_enrichment_with_stubbed_history(monkeypatch):
    import pandas as pd
    from app.adapters.valuation_references import enrich
    class Stock:
        def history(self,**kwargs):
            assert kwargs['auto_adjust'] is False
            return pd.DataFrame({'Close':[50]},index=pd.to_datetime(['2025-12-31']))
    d=dict(ticker='TEST',retrieved_at='2026-10-10T00:00:00+00:00',quote=dict(value=60,currency='USD'),estimates=[],historical=[dict(period_end='2025-12-31',currency='USD',diluted_eps=2,revenue=1000,source='fixture')],anchors=[],revenue_anchors=[],warnings=[],raw={},methods={})
    info=dict(financialCurrency='USD',totalCash=10,totalDebt=50,sharesOutstanding=100,targetMeanPrice=70,trailingPE=30,forwardPE=20)
    r=enrich(d,Stock(),info)
    assert r['historical_pe']['rows'][0]['pe']==25
    assert r['market_baseline']['net_debt']==40
    assert r['analyst_targets']['mean']==70 and r['analyst_targets']['horizon'] is None
    assert r['current_multiples']['forward_pe']==20

def test_saved_market_comparison_replays(tmp_path,monkeypatch,data):
    monkeypatch.setattr(api,'DB',tmp_path/'valuation.db')
    data['estimates']=[dict(metric='eps',period='+1y',avg=4,currency='USD')]
    monkeypatch.setattr(api,'fetch',lambda _:data)
    app=FastAPI();app.include_router(api.router);client=TestClient(app)
    s=client.post('/api/v1/valuation/TEST/fetch').json()
    r=client.post('/api/v1/valuation/calculate',json=dict(data_id=s['id'],assumptions=assumptions().model_dump(),reference=dict(pe=25,spread=.1)))
    assert r.status_code==200
    saved=r.json();assert saved['payload']['market_comparison']['rows'][0]['prices'][1]['price']==100
    assert client.get('/api/v1/valuation/snapshots/'+saved['id']).json()==saved


