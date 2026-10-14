"""Enrich existing valuation data with current/historical multiples and optional peers."""
from datetime import date,datetime,timezone
from ..core.multiples import multiple_context,method_fit
from ..core.valuation_context import num,ratio,historical_pe,to_date,consensus_period_end,earnings_quality_flags,status_quo,fcf_anchors,pfcf_defaults,earnings_dislocation,industry_summary,consensus_quarter_end,growth_refs

SCHEMA='valuation-data-v3'
KNOWN_NOTES={
 'MRVL':('MRVL FY2026 includes a large automotive Ethernet disposal gain. Do not compound reported EPS as recurring earnings without review. EBITDA also requires definition/one-off checks.',
         ['https://investor.marvell.com/sec-filings/all-sec-filings/content/0001104659-26-060265/0001104659-26-060265.pdf']),
 'TSLA':('A low or volatile earnings base makes P/E highly sensitive. Future business lines not represented in the earnings path are not separately valued. EV/EBITDA does not solve that omission.',[]),
}


def enrich(data,stock,info,peer_symbols=()):
    from .valuation_adapter import clean
    data['schema_version']=SCHEMA
    now=data['retrieved_at'];price=data['quote'].get('value');currency=data['quote'].get('currency')
    source='yfinance/Yahoo: get_info'
    financial_currency=info.get('financialCurrency')
    current=dict(trailing_pe=num(info.get('trailingPE')),forward_pe=num(info.get('forwardPE')),
                 trailing_eps=num(info.get('trailingEps')),forward_eps=num(info.get('forwardEps')),
                 enterprise_to_ebitda=num(info.get('enterpriseToEbitda')),
                 source=source,retrieved_at=now,published_at=None,
                 basis='Provider current metrics. Forward EPS horizon and GAAP/adjusted basis unspecified. Do not assume +1y EPS equals provider forward EPS.')
    data['current_multiples']=current
    data['annual_eps_multiples']=[dict(period=x.get('period'),eps=x.get('avg'),
        implied_pe=ratio(price,x.get('avg')) if x.get('currency')==currency and currency else None,
        basis='Current price / this consensus EPS; not an independent price forecast')
        for x in data['estimates'] if x.get('metric')=='eps' and x.get('period') in ('0y','+1y')]
    for x in data['estimates']:
        if x.get('period') in ('0y','+1y') and not x.get('period_end'): x['period_end']=consensus_period_end(info,x['period'])
    for x in data['estimates']:
        if x.get('period') in ('0q','+1q') and not x.get('period_end'):
            x['period_end']=consensus_quarter_end(info,x['period']);x['period_end_approx']=True
    fin_cur=financial_currency or currency
    def fact(id_,value,category,period_end,basis,unit,src):
        return dict(id=id_,value=value,category=category,source=src,currency=fin_cur,period_end=period_end,basis=basis,
                    published_at=None,retrieved_at=now,unit=unit,source_url=f"https://finance.yahoo.com/quote/{data['ticker']}/")
    lead=[];rlead=[]
    q_end=to_date(info.get('mostRecentQuarter'))
    if num(info.get('trailingEps')) and q_end:
        lead.append(fact('ttm',num(info['trailingEps']),'ttm_reported',q_end.isoformat(),'Trailing-twelve-month EPS to the latest reported quarter (provider field; GAAP/adjusted basis unverified)','currency_per_share',source))
    if num(info.get('totalRevenue')) and q_end:
        rlead.append(fact('revenue:ttm',num(info['totalRevenue']),'ttm_reported',q_end.isoformat(),'Trailing-twelve-month revenue to the latest reported quarter (provider field)','full_currency_units',source))
    for x in data['estimates']:
        if x.get('period') in ('0y','+1y') and x.get('period_end') and num(x.get('avg')) is not None:
            if x['metric']=='eps':
                lead.append(fact('consensus:'+x['period'],x['avg'],'market_consensus',x['period_end'],'Analyst mean EPS for the fiscal year ending on this date (basis GAAP/adjusted unverified). Not reported.','currency_per_share',x['source']))
            else:
                rlead.append(fact('revenue:consensus:'+x['period'],x['avg'],'market_consensus',x['period_end'],'Analyst mean revenue for the fiscal year ending on this date. Not reported.','full_currency_units',x['source']))
    order={'consensus:0y':0,'consensus:+1y':1}
    lead.sort(key=lambda a:(a['id']!='ttm',order.get(a['id'],9)))
    data['anchors']=lead+data['anchors']
    mcap=num(info.get('marketCap'));outstanding=num(info.get('sharesOutstanding'))
    shares_now=mcap/price if mcap and price and price>0 else outstanding
    data['share_check']=dict(shares_used=shares_now,shares_outstanding=outstanding,market_cap=mcap,
        basis='Share count = provider market cap / price, so per-share values match the market valuation (covers several share classes).',
        differs=bool(shares_now and outstanding and abs(shares_now/outstanding-1)>.25))
    data['fcf_anchors'],data['fcf_history']=fcf_anchors(data.pop('cashflow',[]),data.pop('cashflow_ttm',None),data['historical'],shares_now,
        fin_cur,data['ticker'],now,'yfinance/Yahoo: cash flow statement',q_end.isoformat() if q_end else None)
    ttm_row=next((r for r in data['fcf_history'] if r.get('ttm')),None) or (data['fcf_history'][0] if data['fcf_history'] else None)
    current['price_to_fcf']=ratio(price,ttm_row['fcf_per_share']) if ttm_row else None
    current['fcf_basis']=('TTM free cash flow per share' if ttm_row and ttm_row.get('ttm') else 'latest annual free cash flow per share') if ttm_row else None
    for r in data['historical']:
        h=next((x for x in data['fcf_history'] if x['period_end']==r['period_end'] and not x.get('ttm')),None)
        if h: r.update(fcf=h['fcf'],sbc=h['sbc'],fcf_conversion=h['conversion'])
    data['analyst_targets']=dict(mean=num(info.get('targetMeanPrice')),median=num(info.get('targetMedianPrice')),
        low=num(info.get('targetLowPrice')),high=num(info.get('targetHighPrice')),analysts=num(info.get('numberOfAnalystOpinions')),
        currency=currency,source=source,retrieved_at=now,published_at=None,horizon=None,
        basis='Provider analyst price targets; individual dates and target horizon unavailable; not this model result.')
    data['market_baseline']=dict(currency=financial_currency,total_debt=num(info.get('totalDebt')),
        total_cash=num(info.get('totalCash')),shares=shares_now,ebitda=num(info.get('ebitda')),
        enterprise_value=num(info.get('enterpriseValue')),net_debt=None,source=source,retrieved_at=now,
        balance_date=None,shares_date=None,basis='Latest available provider balance amounts and outstanding shares; not a target-date forecast. Balance dates unspecified.')
    b=data['market_baseline']
    if b['total_debt'] is not None and b['total_cash'] is not None: b['net_debt']=b['total_debt']-b['total_cash']
    if b['enterprise_value'] and b['net_debt'] is not None and b['shares'] and price:
        r=(price*b['shares']+b['net_debt'])/b['enterprise_value'];data['ev_check']=dict(ratio=r,ok=.75<=r<=1.33)
    data['revenue_anchors']=rlead+[dict(id='revenue:'+r['period_end'],value=r['revenue'],period_end=r['period_end'],
        currency=r.get('currency'),category='historical_reported',source=r['source'],retrieved_at=now,
        published_at=None,unit='full_currency_units') for r in data['historical'] if num(r.get('revenue')) is not None and r['revenue']>0]
    prices=[]
    if stock is not None:
        try:
            frame=stock.history(period='5y',auto_adjust=False,actions=False,timeout=20)
            for idx,row in frame.iterrows():
                p=num(row.get('Close'))
                if p is not None: prices.append(dict(date=str(idx)[:10],close=p))
        except Exception as exc: data['warnings'].append('Historical close: '+str(exc)[:200])
    data['historical_pe']=historical_pe(data['historical'],prices,currency)
    data['historical_pe'].update(source='yfinance/Yahoo: history(auto_adjust=False) + current annual income',retrieved_at=now)
    used={x['price_date'] for x in data['historical_pe']['rows'] if x.get('price_date')}
    data['raw']['historical_close_for_pe']=[p for p in prices if p['date'] in used]
    data['peers']=[]
    for symbol in peer_symbols:
        peer=dict(ticker=symbol,source=source,retrieved_at=datetime.now(timezone.utc).isoformat(),published_at=None)
        try:
            import yfinance as yf
            p=yf.Ticker(symbol).get_info() or {}
            peer.update(name=p.get('longName'),sector=p.get('sector'),industry=p.get('industry'),
                        trailing_pe=num(p.get('trailingPE')),forward_pe=num(p.get('forwardPE')),
                        ev_ebitda=num(p.get('enterpriseToEbitda')),currency=p.get('currency'),
                        eps_growth=(num(p.get('forwardEps'))/num(p.get('trailingEps'))-1) if num(p.get('forwardEps')) and num(p.get('trailingEps')) and num(p.get('forwardEps'))>0 and num(p.get('trailingEps'))>0 else None,
                        price_to_fcf=(num(p.get('marketCap'))/num(p.get('freeCashflow'))) if num(p.get('marketCap')) and num(p.get('freeCashflow')) and num(p.get('freeCashflow'))>0 else None)
        except Exception as exc: peer['error']=str(exc)[:180]
        data['peers'].append(peer)
    data['industry_ref']=industry_summary(data['peers'],data.get('peer_source') or 'peer set')
    data['peer_basis']='User-selected comparison companies; not an industry average. Different businesses and accounting bases may not be comparable.'
    data['sector']=info.get('sector');data['industry']=info.get('industry')
    data['method_notes']=[
        'P/E works best with a positive, representative earnings base; reported EPS may contain one-offs.',
        'EV/EBITDA excludes capital expenditure, taxes, working capital and dilution economics; it is a cross-check, not a cash-flow valuation.',
        'A common exit multiple across unlike businesses is a user hypothesis, not a market fact.']
    note=KNOWN_NOTES.get(data['ticker'])
    if note:
        data['method_notes'].append(note[0])
        if note[1]: data['method_note_sources']=note[1]
    data['earnings_quality_flags']=earnings_quality_flags(sorted(data['historical'],key=lambda r:str(r.get('period_end')),reverse=True))
    data['method_notes']+=data['earnings_quality_flags']
    data['methods']['ev_ebitda']='Available with a revenue anchor and explicit margin, multiple, target net debt, shares and other claims assumptions.'
    rev_ttm=next((x['value'] for x in data['revenue_anchors'] if x['id']=='revenue:ttm'),None)
    if b.get('ebitda') and b['ebitda']>0 and rev_ttm and rev_ttm>0 and b.get('currency') in (None,fin_cur):
        data['ttm_ebitda_margin']=b['ebitda']/rev_ttm
    data['earnings_dislocation']=earnings_dislocation(data)
    if data['earnings_dislocation']: data['method_notes']+=data['earnings_dislocation']['lines'][-1:]
    data['defaults']=status_quo(data)
    data['growth_refs']=growth_refs(data)
    data['method_fit']=method_fit(data)
    pick,mm=pfcf_defaults(data,(data['method_fit'].get('p_fcf') or {}).get('use_after_sbc'))
    pf=data['defaults']['p_fcf'];pf['anchor_id']=pick['id'] if pick else None;pf['multiple_by_anchor']=mm
    pf['exit_multiple']=round(mm[pick['id']],1) if pick and pick['id'] in mm else None
    data['multiple_context']={m:multiple_context(data,m) for m in ('pe','p_fcf','ev_ebitda')}
    return clean(data)


