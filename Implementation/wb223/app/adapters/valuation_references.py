"""Enrich existing valuation data with current/historical multiples and optional peers."""
from datetime import date,datetime,timezone
from ..core.fx import conv_rows,conv_estimates
from ..core.multiples import multiple_context,method_fit
from ..core.period_table import build_period_table
from ..core.valuation_defaults import build_defaults,growth_refs
from ..core.valuation_context import meaningful,withheld_note,num,ratio,historical_pe,to_date,consensus_period_end,earnings_quality_flags,fcf_anchors,earnings_dislocation,industry_summary,consensus_quarter_end

SCHEMA='valuation-data-v4'
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
    fx=data.get('fx') or {};conv=fx['rate'] if fx.get('applied') else 1.0
    if fx.get('applied'):
        # Everything the provider reports in the financial currency is turned into the quote currency once, here,
        # so the rest of the app sees one currency. The original numbers stay in data['raw'].
        conv_estimates(data['estimates'],fx)
        conv_rows(data['historical'],conv,('revenue','net_income','diluted_eps','ebitda'))
        conv_rows(data['anchors'],conv,('value',))
        conv_rows(data.get('cashflow'),conv,('ocf','capex','fcf','sbc'))
        if data.get('cashflow_ttm'): conv_rows([data['cashflow_ttm']],conv,('ocf','capex','fcf','sbc'))
        for r in data['historical']+data['anchors']:
            if r.get('currency')==fx['from']: r['currency']=fx['to'];r['fx_from']=fx['from']
        for a_ in data['anchors']: a_['basis']=(a_.get('basis') or '')+' '+fx['text']
    def eps_in_quote(eps,pe):
        """The provider's own P/E is price ÷ EPS in the quote currency. If that reproduces it, the EPS is already in the quote currency."""
        return bool(eps and pe and price and eps>0 and pe>0 and abs(price/eps/pe-1)<.04)
    t_eps=num(info.get('trailingEps'));f_eps=num(info.get('forwardEps'))
    t_quote=eps_in_quote(t_eps,num(info.get('trailingPE')))
    if fx.get('applied') and not t_quote and t_eps is not None: t_eps_q=t_eps*conv
    else: t_eps_q=t_eps
    if fx.get('applied') and not eps_in_quote(f_eps,num(info.get('forwardPE'))) and f_eps is not None: f_eps=f_eps*conv
    current=dict(trailing_pe=num(info.get('trailingPE')),forward_pe=num(info.get('forwardPE')),
                 trailing_eps=t_eps_q,forward_eps=f_eps,
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
    fin_cur=(currency if fx.get('applied') else financial_currency) or currency
    def fact(id_,value,category,period_end,basis,unit,src,convert=True,already_quote=False):
        k=conv if (convert and not already_quote) else 1.0
        note=(' '+fx['text']) if fx.get('applied') and (convert and not already_quote) else ''
        out=dict(id=id_,value=value*k,category=category,source=src,currency=fin_cur,period_end=period_end,basis=basis+note,
                    published_at=None,retrieved_at=now,unit=unit,source_url=f"https://finance.yahoo.com/quote/{data['ticker']}/")
        if fx.get('applied') and (not convert or k!=1.0): out['fx_from']=fx['from']
        return out
    lead=[];rlead=[]
    q_end=to_date(info.get('mostRecentQuarter'))
    if num(info.get('trailingEps')) and q_end:
        lead.append(fact('ttm',num(info['trailingEps']),'ttm_reported',q_end.isoformat(),'Trailing-twelve-month EPS to the latest reported quarter (provider field; GAAP/adjusted basis unverified)'+(' The provider EPS already matches its own P/E in the quote currency, so it was not converted.' if fx.get('applied') and t_quote else ''),'currency_per_share',source,already_quote=t_quote))
    if num(info.get('totalRevenue')) and q_end:
        rlead.append(fact('revenue:ttm',num(info['totalRevenue']),'ttm_reported',q_end.isoformat(),'Trailing-twelve-month revenue to the latest reported quarter (provider field)','full_currency_units',source))
    for x in data['estimates']:
        if x.get('period') in ('0y','+1y') and x.get('period_end') and num(x.get('avg')) is not None:
            if x['metric']=='eps':
                lead.append(fact('consensus:'+x['period'],x['avg'],'market_consensus',x['period_end'],'Analyst mean EPS for the fiscal year ending on this date (basis GAAP/adjusted unverified). Not reported.'+((' '+fx['text']) if fx.get('applied') else ''),'currency_per_share',x['source'],convert=False))
            else:
                rlead.append(fact('revenue:consensus:'+x['period'],x['avg'],'market_consensus',x['period_end'],'Analyst mean revenue for the fiscal year ending on this date. Not reported.'+((' '+fx['text']) if fx.get('applied') else ''),'full_currency_units',x['source'],convert=False))
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
    rate=num(info.get('dividendRate')) or num(info.get('trailingAnnualDividendRate'))
    dy=rate/price if rate and price and price>0 else None
    current['dividend_yield']=dy if dy is not None and 0<dy<0.25 else None      # annual dividend per share ÷ price, both in the trading currency
    current['dividend_basis']='Provider annual dividend per share ÷ price. A rough guide: the lab\'s returns are price returns and do not include it.'
    data['analyst_targets']=dict(mean=num(info.get('targetMeanPrice')),median=num(info.get('targetMedianPrice')),
        low=num(info.get('targetLowPrice')),high=num(info.get('targetHighPrice')),analysts=num(info.get('numberOfAnalystOpinions')),
        currency=currency,source=source,retrieved_at=now,published_at=None,horizon=None,
        basis='Provider analyst price targets; individual dates and target horizon unavailable; not this model result.')
    def c_(v): return None if v is None else v*conv
    ev_raw=num(info.get('enterpriseValue'));debt_c=c_(num(info.get('totalDebt')));cash_c=c_(num(info.get('totalCash')))
    ev_pick=c_(ev_raw)
    if fx.get('applied') and ev_raw and shares_now and price and debt_c is not None and cash_c is not None:
        mk=price*shares_now+(debt_c-cash_c)      # which reading of the provider EV matches price × shares + net debt?
        if abs(ev_raw/mk-1)<abs(ev_raw*conv/mk-1): ev_pick=ev_raw
    data['market_baseline']=dict(currency=(currency if fx.get('applied') else financial_currency),total_debt=debt_c,
        total_cash=cash_c,shares=shares_now,ebitda=c_(num(info.get('ebitda'))),
        enterprise_value=ev_pick,net_debt=None,source=source,retrieved_at=now,
        balance_date=None,shares_date=None,basis='Latest available provider balance amounts and outstanding shares; not a target-date forecast. Balance dates unspecified.')
    b=data['market_baseline']
    if b['total_debt'] is not None and b['total_cash'] is not None: b['net_debt']=b['total_debt']-b['total_cash']
    if b['enterprise_value'] and b['net_debt'] is not None and b['shares'] and price:
        r=(price*b['shares']+b['net_debt'])/b['enterprise_value'];data['ev_check']=dict(ratio=r,ok=.75<=r<=1.33)
    own_ev=(price*b['shares']+b['net_debt'])/b['ebitda'] if (b.get('ebitda') and b['ebitda']>0 and b.get('net_debt') is not None and b.get('shares') and price) else None
    prov_ev=current.get('enterprise_to_ebitda')
    if own_ev and prov_ev and abs(prov_ev/own_ev-1)>.3:
        current['enterprise_to_ebitda_provider']=prov_ev;current['enterprise_to_ebitda']=own_ev
        current['ev_ebitda_note']=f'The provider\'s EV/EBITDA ({prov_ev:,.1f}x) does not match market value + net debt over EBITDA ({own_ev:,.1f}x, calculated here). The calculated figure is shown.'
        data['warnings'].append(current['ev_ebitda_note'])
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
    data['period_table']=build_period_table(data)
    data['method_fit']=method_fit(data)
    data['defaults']=build_defaults(data,data['method_fit'])
    data['growth_refs']=growth_refs(data)
    if fx.get('applied'):
        data['warnings'].append(fx['text'])
        pe_t=num(info.get('trailingPE'));tt=next((x for x in data['anchors'] if x['id']=='ttm'),None)
        if pe_t and tt and price and abs(price/tt['value']/pe_t-1)>.15: data['warnings'].append('The converted trailing EPS gives a P/E that differs from the provider P/E by more than 15%; check the currency of the provider EPS before relying on P/E.')
    elif fx.get('needed'): data['warnings'].append('Quote and accounts are in different currencies and no exchange rate was available: '+str(fx.get('reason'))+'. Valuation methods that mix them are blocked.')
    data['multiple_context']={m:multiple_context(data,m) for m in ('pe','p_fcf','ev_ebitda')}
    return clean(data)


