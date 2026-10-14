"""Deterministic scenario/return tests; market references never become assumptions silently."""
from datetime import date
from typing import Literal
import math
from math import isclose
from pydantic import BaseModel, ConfigDict, Field
from .valuation_context import reference_price

class Assumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra='forbid')
    method: Literal['pe']='pe'
    anchor_id: str
    years: int = Field(ge=1,le=10)
    required_return: float = Field(gt=-1,le=1)
    growth: float = Field(gt=-1,le=2)
    exit_pe: float = Field(gt=0,le=500)
    growth_spread: float = Field(ge=0,le=1)
    fade_to: float | None = Field(default=None,gt=-1,le=2)
    pe_spread: float = Field(ge=0,lt=1)
    acknowledge_basis: bool

class EbitdaAssumptions(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False,extra='forbid')
    method: Literal['ev_ebitda']
    anchor_id: str
    years: int = Field(ge=1,le=10)
    required_return: float = Field(gt=-1,le=1)
    growth: float = Field(gt=-1,le=2)
    growth_spread: float = Field(ge=0,le=1)
    fade_to: float | None = Field(default=None,gt=-1,le=2)
    margin: float = Field(gt=0,le=1)
    margin_spread: float = Field(ge=0,lt=1)
    exit_multiple: float = Field(gt=0,le=300)
    multiple_spread: float = Field(ge=0,lt=1)
    target_net_debt: float = Field(ge=-1e15,le=1e15)
    target_shares: float = Field(gt=0,le=1e15)
    other_claims: float = Field(ge=0,le=1e15)
    balance_assumption: Literal['user_forecast','hold_current_constant']
    acknowledge_basis: bool


class PfcfAssumptions(BaseModel):
    """Price / free-cash-flow exit multiple. growth is growth of total FCF; share_change is the yearly change in share count
    (negative = buybacks, positive = dilution), so FCF per share grows at (1+growth)/(1+share_change)-1."""
    model_config = ConfigDict(allow_inf_nan=False,extra='forbid')
    method: Literal['p_fcf']
    anchor_id: str
    years: int = Field(ge=1,le=10)
    required_return: float = Field(gt=-1,le=1)
    growth: float = Field(gt=-1,le=2)
    growth_spread: float = Field(ge=0,le=1)
    fade_to: float | None = Field(default=None,gt=-1,le=2)
    share_change: float = Field(gt=-.5,lt=.5)
    exit_multiple: float = Field(gt=0,le=300)
    multiple_spread: float = Field(ge=0,lt=1)
    acknowledge_basis: bool


def growth_factor(g0,g1,gy,total=None):
    """Compound factor over gy years (may be fractional). g1=None: constant growth g0. Otherwise the yearly growth moves in a
    straight line from g0 in the first year to g1 in the last of `total` years (default gy). A part-year at the end is
    compounded at that year's rate for its fraction."""
    if gy<=0: return (1+g0)**gy if gy<0 else 1.0
    if g1 is None or abs(g1-g0)<1e-12: return (1+g0)**gy
    n=max(1,math.ceil((total if total is not None else gy)-1e-9));f=1.0;k=0;left=gy
    while left>1e-9:
        w=min(1.0,left)
        f*=(1+g0+(g1-g0)*(min(k,n-1)/(n-1) if n>1 else 0))**w
        left-=w;k+=1
    return f


def fade_of(a,shift):
    return None if a.fade_to is None else a.fade_to+shift*a.growth_spread


def anniversary(day,years):
    try: return day.replace(year=day.year+years)
    except ValueError: return day.replace(year=day.year+years,day=28)


def base_context(data,a,key):
    if not a.acknowledge_basis: raise ValueError('Confirm the financial basis and assumptions before calculating.')
    anchor=next((x for x in data.get(key,[]) if x['id']==a.anchor_id),None)
    if not anchor: raise ValueError('Selected financial anchor is unavailable.')
    if anchor.get('value') is None or anchor['value']<=0: raise ValueError('A positive financial anchor is required.')
    price=data['quote'].get('value')
    if not price or price<=0: raise ValueError('A positive observed price is required.')
    currency=data['quote'].get('currency')
    if not currency or currency!=anchor.get('currency'): raise ValueError('Quote and financial anchor currencies must be known and identical.')
    asof=date.fromisoformat(data['retrieved_at'][:10]);end=anniversary(asof,a.years)
    if a.growth-a.growth_spread<=-1: raise ValueError('Bear growth must exceed -100%.')
    # Growth is counted for exactly the holding period. The starting value and the exit multiple are on the same basis (trailing,
    # or a future year), so the basis is carried forward one holding period; no extra years are added for the date gap.
    return anchor,price,currency,asof,end,float(a.years)


def outputs(data,a,anchor,price,currency,asof,end,gy,rows,reverse):
    target=price*(1+a.required_return)**a.years
    for row in rows:
        future=row['future_price']
        row.update(discounted_terminal=future/(1+a.required_return)**a.years,
                   price_cagr=(future/price)**(1/a.years)-1,price_change=future/price-1,
                   meets_required=future>=target)
        row['return_gap']=row['price_cagr']-a.required_return
    return dict(method=a.method,formula_version='valuation-v3',currency=currency,
                valuation_date=asof.isoformat(),exit_date=end.isoformat(),growth_years=gy,
                anchor=anchor,assumptions=a.model_dump(),scenarios=rows,reverse=reverse,
                required_exit_price=target,
                limitations=['Price return excludes dividends, tax and fees.',
                  'Discounted terminal price is not a complete cash-flow valuation.',
                  'Bear/Base/Bull are user assumptions, not probabilities, bounds or analyst targets.',
                  'Growth is counted for exactly the holding period from the starting value. The exit multiple is read on the same basis as that starting value, so today\'s multiple on it (price ÷ starting value) adds nothing when held flat.'+(' Growth fades linearly from the starting rate to the fade rate by the exit date.' if getattr(a,'fade_to',None) is not None else ''),
                  'Reverse expectations are conditional on the selected multiple and other assumptions.'])


def base_path(a,anchor,price,gy,metric_of,per_year_factor=None):
    """Year-by-year Base path: metric (EPS or FCF/share) × multiple. The multiple moves in a straight line from today's
    (price ÷ starting value) to the exit multiple; the metric follows the growth path from the starting value, so year 0 reproduces
    today's price. Year 1 is comparable with analyst 12-month price targets."""
    mkey='exit_pe' if a.method=='pe' else 'exit_multiple'
    exit_m=getattr(a,mkey);start_m=price/anchor['value'];g0=a.growth;g1=a.fade_to
    drag=1+getattr(a,'share_change',0.0)
    if a.method=='p_fcf':
        g0=(1+g0)/drag-1;g1=None if g1 is None else (1+g1)/drag-1
    out=[]
    for t in range(1,a.years+1):
        value=anchor['value']*growth_factor(g0,g1,t,total=a.years)
        m=start_m+(exit_m-start_m)*t/a.years
        p=value*m
        out.append(dict(year=t,date=anniversary(date.fromisoformat(metric_of),t).isoformat(),value=value,multiple=m,price=p,
                        price_change=p/price-1,annualised=(p/price)**(1/t)-1 if p>0 else None))
    return out


def decompose(res,price,anchor,years,mkey):
    """Split each scenario's annual price return into an earnings (or cash-flow) part and a multiple part.
    Exact identity: future/price = (X_exit/X_anchor) * (M_exit/M_start), with M_start = price/X_anchor."""
    start=price/anchor['value'];res['start_multiple']=start
    for row in res['scenarios']:
        me=(row[mkey]/start)**(1/years)-1
        row['multiple_effect']=me;row['earnings_effect']=(1+row['price_cagr'])/(1+me)-1
    return res


def range_checks(data,a,anchor,gy):
    """Plausibility notes next to the result. They never change the numbers; level 'warn' means look before trusting."""
    out=[];cm=data.get('current_multiples') or {};price=data['quote']['value']
    def add(level,text): out.append(dict(level=level,text=text))
    est={e.get('period'):e.get('avg') for e in data.get('estimates',[]) if e.get('metric')=='eps'}
    today=price/anchor['value'] if anchor['value']>0 else None   # today's multiple on this very starting value
    try:
        age=(date.fromisoformat(data['retrieved_at'][:10])-date.fromisoformat(anchor['period_end'])).days/30.44
    except (ValueError,KeyError,TypeError): age=0
    if a.method=='pe':
        if today and a.exit_pe>1.5*today: add('warn',f'Exit P/E {a.exit_pe:.1f}x is more than 1.5x what the market pays today on this starting point ({today:.1f}x = price ÷ {anchor["value"]:.2f}): the result leans on multiple expansion.')
        elif today and a.exit_pe<0.5*today: add('note',f'Exit P/E {a.exit_pe:.1f}x is less than half of today\'s {today:.1f}x on this starting point: a deep de-rating is assumed.')
        ttm=cm.get('trailing_eps')
        if anchor['id'].startswith('annual:') and ttm and ttm>0 and abs(ttm/anchor['value']-1)>.25:
            add('warn',f'Annual anchor EPS {anchor["value"]:.2f} differs from TTM EPS {ttm:.2f} by more than 25%: the anchor is stale or contains one-offs.')
        if anchor['value']>0 and price/anchor['value']>60:
            add('warn',f'Price is {price/anchor["value"]:.0f}x this anchor EPS: a small EPS base makes the projection very sensitive.')
        if est.get('0y') and est.get('+1y') and est['0y']>0:
            g=est['+1y']/est['0y']-1
            if a.growth>max(2*g,g+.05): add('warn',f'Base growth {a.growth*100:.1f}% is well above the analyst +1y/0y EPS growth of {g*100:.1f}%.')
        dis=data.get('earnings_dislocation')
        if dis and dis.get('kind')=='recovery' and anchor.get('category')!='market_consensus':
            add('warn',f'Reported EPS {dis["ttm_eps"]:.2f} is far below analyst EPS {(dis.get("cons_0y") or dis.get("cons_1y")):.2f}: the price already expects a recovery, so a multiple read on trough earnings is distorted. Start from the analyst year instead, and use the "what you must believe" grid.')
    elif a.method=='p_fcf':
        if today and a.exit_multiple>1.5*today: add('warn',f'Exit P/FCF {a.exit_multiple:.1f}x is more than 1.5x what the market pays today on this starting point ({today:.1f}x): the result leans on multiple expansion.')
        elif today and a.exit_multiple<0.5*today: add('note',f'Exit P/FCF {a.exit_multiple:.1f}x is less than half of today\'s {today:.1f}x on this starting point.')
        if anchor['value']>0 and price/anchor['value']>60: add('warn',f'Price is {price/anchor["value"]:.0f}x this FCF per share: a small base makes the projection very sensitive.')
        hist=[r for r in data.get('fcf_history',[]) if r.get('conversion') is not None and not r.get('ttm')]
        if hist and (hist[0]['conversion']<.5 or hist[0]['conversion']>1.5): add('warn',f'Free cash flow is {hist[0]["conversion"]*100:.0f}% of net income in the latest year: cash conversion is unusual, so check capex timing and one-offs.')
        latest=next((r for r in data.get('fcf_history',[]) if r.get('ttm')),None) or (data.get('fcf_history') or [None])[0]
        if latest and latest.get('sbc') and latest.get('fcf') and latest['fcf']>0 and latest['sbc']/latest['fcf']>.25 and not anchor['id'].startswith('fcfsbc'):
            add('note',f'Stock-based compensation is {latest["sbc"]/latest["fcf"]*100:.0f}% of FCF. Consider the after-SBC anchor.')
        if anchor['id'].startswith('fcfsbc') and a.share_change>0:
            add('note','The after-SBC cash flow already treats stock compensation as a cost; a positive share-count change counts the same dilution a second time.')
        gs=((data.get('defaults') or {}).get('p_fcf') or {}).get('growth_source')
        if gs in ('eps_cons','rev_cons'): add('note','No analyst forecast exists for free cash flow: the default growth is the analyst '+('EPS' if gs=='eps_cons' else 'revenue')+' growth used as a stand-in, so P/E and P/FCF agreeing is not independent confirmation.')
    else:
        hist=[r.get('ebitda_margin') for r in data.get('historical',[]) if r.get('ebitda_margin') is not None]
        if hist and a.margin>1.5*max(hist): add('warn',f'Base margin {a.margin*100:.1f}% is above 1.5x the highest reported EBITDA margin ({max(hist)*100:.1f}%).')
        cur=cm.get('enterprise_to_ebitda')
        if cur and a.exit_multiple>1.5*cur: add('warn',f'Exit EV/EBITDA {a.exit_multiple:.1f}x is more than 1.5x today\'s {cur:.1f}x.')
        if anchor.get('category')=='market_consensus': add('note','The revenue starting point is a future year but the EV/EBITDA multiple from the provider is trailing: forward EBITDA times a trailing multiple overstates the result. Prefer the TTM revenue starting point.')
    if (anchor.get('category')=='historical_reported' or anchor['id'].startswith('annual:')) and age>15:
        add('warn',f'This starting point ended {age:.0f} months ago. It is grown for the holding period only, so growth since then is not in the base. Prefer the TTM or analyst starting point.')
    return out


def belief_grid(data,a,res):
    """What you must believe: the exit price for different earnings (or cash-flow) outcomes against different exit multiples.
    Rows scale the Base starting value (shortfalls of 20% and 40%, plus the reported trailing level when the start is an analyst
    year); columns are today's multiple on the starting point, your exit multiple and the reference multiples. Cell = annual price
    return. Pure arithmetic on stated inputs; it ranks nothing and picks no cell."""
    if a.method not in ('pe','p_fcf'): return None
    base=res['scenarios'][1];price=data['quote']['value'];anchor=res['anchor']
    key='eps' if a.method=='pe' else 'fcf_per_share';mkey='exit_pe' if a.method=='pe' else 'exit_multiple'
    mine=getattr(a,mkey);today=price/anchor['value'];e0=base[key]
    rows=[dict(label='Starting value delivered, then your growth',factor=1.0),dict(label='Falls 20% short',factor=.8),dict(label='Falls 40% short',factor=.6)]
    if a.method=='pe':
        ttm=next((x['value'] for x in data.get('anchors',[]) if x['id']=='ttm' and x.get('value') and x['value']>0),None)
        if ttm and anchor.get('category')=='market_consensus' and ttm/anchor['value']<.75:
            rows.append(dict(label=f'No recovery: reported trailing EPS {ttm:.2f} is the base',factor=ttm/anchor['value']))
    cols=[dict(label='Today on this starting point',value=today),dict(label='Your exit multiple',value=mine)]
    ctx=(data.get('multiple_context') or {}).get(a.method) or {}
    for pt in ctx.get('points') or []:
        k=pt.get('key')
        if k=='today' and pt.get('anchor') and pt['anchor']!=a.anchor_id: cols.append(dict(label=pt['label']+' (other basis)',value=pt['low']))
        elif k=='history': cols+=[dict(label='Own history · low (trailing)',value=pt['low']),dict(label='Own history · high (trailing)',value=pt['high'])]
        elif k=='peers' and pt.get('median'): cols.append(dict(label='Peers · median',value=pt['median']))
    uniq=[]
    for c in cols:
        if c['value'] and c['value']>0 and not any(abs(c['value']/u['value']-1)<.03 for u in uniq): uniq.append(c)
    uniq=sorted(uniq,key=lambda c:c['value'])[:6]
    ret=a.required_return
    for r in rows:
        r['value']=e0*r['factor'];r['cells']=[]
        for c in uniq:
            fp=r['value']*c['value'];cg=(fp/price)**(1/a.years)-1 if fp>0 else None
            r['cells'].append(dict(price=fp,cagr=cg,meets=cg is not None and cg>=ret))
    return dict(method=a.method,noun='EPS' if a.method=='pe' else 'FCF/share',columns=uniq,rows=rows,required_return=ret,
        note='Each cell: Base-path value at exit (shown in the row) × the multiple in the column, as an annual price return from today\'s price. The multiple should sit on the same basis as the starting value. References marked trailing are on past-year earnings, so on a forward basis read them as somewhat high.')


def calculate(data,a):
    if isinstance(a,EbitdaAssumptions): return calculate_ebitda(data,a)
    if isinstance(a,PfcfAssumptions): return calculate_pfcf(data,a)
    anchor,price,cur,asof,end,gy=base_context(data,a,'anchors');eps=anchor['value'];rows=[]
    for label,shift in (('Bear',-1),('Base',0),('Bull',1)):
        growth=a.growth+shift*a.growth_spread;pe=a.exit_pe*(1+shift*a.pe_spread)
        fade=fade_of(a,shift)
        if fade is not None and fade<=-1: raise ValueError('Bear fade growth must exceed -100%.')
        projected=eps*growth_factor(growth,fade,gy)
        rows.append(dict(scenario=label,growth=growth,exit_pe=pe,eps=projected,future_price=projected*pe))
    needed=price*(1+a.required_return)**a.years/a.exit_pe
    reverse=dict(required_eps=needed,required_eps_growth=(needed/eps)**(1/gy)-1,
                 required_exit_pe=price*(1+a.required_return)**a.years/rows[1]['eps'],
                 exit_pe=a.exit_pe,required_return=a.required_return)
    res=outputs(data,a,anchor,price,cur,asof,end,gy,rows,reverse)
    res['path']=base_path(a,anchor,price,gy,res['valuation_date'])
    decompose(res,price,anchor,a.years,'exit_pe')
    res['checks']=range_checks(data,a,anchor,gy)
    res['grid']=belief_grid(data,a,res)
    return res


def calculate_pfcf(data,a):
    anchor,price,cur,asof,end,gy=base_context(data,a,'fcf_anchors');base=anchor['value'];rows=[]
    drag=1+a.share_change
    for label,shift in (('Bear',-1),('Base',0),('Bull',1)):
        growth=a.growth+shift*a.growth_spread;multiple=a.exit_multiple*(1+shift*a.multiple_spread)
        if growth<=-1: raise ValueError('Bear growth must exceed -100%.')
        fade=fade_of(a,shift)
        if fade is not None and fade<=-1: raise ValueError('Bear fade growth must exceed -100%.')
        per_share=base*growth_factor((1+growth)/drag-1,None if fade is None else (1+fade)/drag-1,gy)
        rows.append(dict(scenario=label,growth=growth,exit_multiple=multiple,fcf_per_share=per_share,
                         fcf_yield=1/multiple,future_price=per_share*multiple))
    needed=price*(1+a.required_return)**a.years/a.exit_multiple
    reverse=dict(required_fcf_per_share=needed,required_fcf_per_share_growth=(needed/base)**(1/gy)-1,
                 required_exit_multiple=price*(1+a.required_return)**a.years/rows[1]['fcf_per_share'],
                 exit_multiple=a.exit_multiple,required_return=a.required_return)
    res=outputs(data,a,anchor,price,cur,asof,end,gy,rows,reverse)
    res['path']=base_path(a,anchor,price,gy,res['valuation_date'])
    decompose(res,price,anchor,a.years,'exit_multiple')
    res['checks']=range_checks(data,a,anchor,gy)
    res['grid']=belief_grid(data,a,res)
    res['limitations']+=['Free cash flow = operating cash flow − capital expenditure as supplied by the provider; leases, acquisitions and working-capital swings are not adjusted.',
                         'Per-share FCF uses the share count named in the anchor basis; buybacks and dilution are the share_change assumption.']
    return res


def calculate_ebitda(data,a):
    anchor,price,cur,asof,end,gy=base_context(data,a,'revenue_anchors')
    if a.margin-a.margin_spread<=0 or a.margin+a.margin_spread>1:
        raise ValueError('All EBITDA margins must be greater than zero and at most 100%.')
    baseline=data.get('market_baseline') or {}
    if a.balance_assumption=='hold_current_constant':
        if baseline.get('currency')!=cur: raise ValueError('Current balance currency does not match the quote.')
        if baseline.get('net_debt') is None or baseline.get('shares') is None: raise ValueError('Current net debt and shares are required for this assumption.')
        if not isclose(a.target_net_debt,baseline['net_debt'],rel_tol=1e-12,abs_tol=.001) or not isclose(a.target_shares,baseline['shares'],rel_tol=1e-12,abs_tol=.001):
            raise ValueError('Hold-current assumption must match the saved provider balance and share values.')
    rows=[]
    for label,shift in (('Bear',-1),('Base',0),('Bull',1)):
        growth=a.growth+shift*a.growth_spread;margin=a.margin+shift*a.margin_spread
        multiple=a.exit_multiple*(1+shift*a.multiple_spread)
        fade=fade_of(a,shift)
        if fade is not None and fade<=-1: raise ValueError('Bear fade growth must exceed -100%.')
        revenue=anchor['value']*growth_factor(growth,fade,gy);ebitda=revenue*margin;ev=ebitda*multiple
        equity=ev-a.target_net_debt-a.other_claims
        rows.append(dict(scenario=label,growth=growth,margin=margin,exit_multiple=multiple,
            revenue=revenue,ebitda=ebitda,enterprise_value=ev,equity_value=equity,
            future_price=max(0,equity)/a.target_shares,
            equity_floor_applied=equity<0))
    needed=(price*(1+a.required_return)**a.years*a.target_shares+a.target_net_debt+a.other_claims)/a.exit_multiple
    reverse=dict(required_ebitda=needed,required_margin=needed/rows[1]['revenue'],
                 required_exit_multiple=(price*(1+a.required_return)**a.years*a.target_shares+a.target_net_debt+a.other_claims)/rows[1]['ebitda'],
                 required_return=a.required_return)
    result=outputs(data,a,anchor,price,cur,asof,end,gy,rows,reverse)
    result['checks']=range_checks(data,a,anchor,gy)
    result['limitations']+=['Current net debt/shares, if reused, are explicitly assumed constant to exit; other claims are user-entered.',
                           'EBITDA excludes capex, working capital, tax and financing costs. SBC and lease definitions may differ.',
                           'Negative residual equity is floored at zero for per-share price, not represented as a negative stock price.']
    return result


def consensus_bridge(data,pe,spread):
    if not 0<pe<=500 or not 0<=spread<1: raise ValueError('Invalid P/E or range.')
    rows=[]
    for estimate in data.get('estimates',[]):
        if estimate.get('metric')!='eps' or estimate.get('period') not in ('0y','+1y'): continue
        row=dict(period=estimate['period'],eps=estimate.get('avg'),source=estimate.get('source'),
                 period_end=estimate.get('period_end'),basis=estimate.get('basis'),prices=[])
        try:
            for name,shift in (('Lower P/E',-1),('Selected P/E',0),('Higher P/E',1)):
                m=pe*(1+shift*spread);value=reference_price(estimate,m,data['quote'].get('currency'))
                price=data['quote'].get('value')
                row['prices'].append(dict(label=name,pe=m,price=value,change=value/price-1 if price and price>0 else None))
        except ValueError as exc: row['error']=str(exc)
        rows.append(row)
    return dict(rows=rows,pe=pe,spread=spread,
        explanation='Annual consensus mean EPS × user-selected P/E. A valuation sensitivity, not an analyst target. No annualized return: exact forecast dates and EPS basis remain unverified. Current price / this same EPS × this EPS reproduces the current price by identity.')


