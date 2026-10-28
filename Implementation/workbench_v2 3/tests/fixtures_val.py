"""Offline company fixtures for the valuation tests: provider-shaped raw data run through the real enrichment, so the period table,
defaults, references and engine are all the production code. No network."""
from datetime import date, datetime, timezone

from app.adapters.valuation_references import enrich


def ts(s):
    y, m, d = (int(x) for x in s.split('-'))
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def company(ticker='ABC', price=44.0, valuation='2026-10-11', last_fy='2025-12-31', next_fy='2026-12-31', mrq='2026-09-30',
            eps=(1.4, 1.6, 1.8, 2.0), revenue=(730e6, 810e6, 900e6, 1000e6), ebitda=(180e6, 200e6, 225e6, 250e6), net_income=(70e6, 80e6, 90e6, 100e6),
            shares=50e6, est=(2.2, 2.5, 1100e6, 1210e6), n_est=10, ttm_eps=2.1, ttm_rev=1050e6, ttm_ebitda=270e6,
            ocf=(110e6, 120e6, 135e6, 150e6), capex=(-30e6,) * 4, sbc=(20e6,) * 4, ttm_cash=(160e6, -30e6, 22e6), cash=True,
            debt=100e6, cash_bal=40e6, sector='Industrials', industry='Machinery', currency='USD', fin_currency=None, fx=None,
            pe_t=None, pe_f=None, ev_ebitda=None):
    """Four reported fiscal years ending at `last_fy` (oldest first in the tuples), analyst estimates est=(eps0, eps1, rev0, rev1).
    Pass est=None for a company with no analyst coverage."""
    fin = fin_currency or currency
    ends = [str(date.fromisoformat(last_fy).replace(year=date.fromisoformat(last_fy).year - i)) for i in range(len(eps))][::-1]
    hist = [dict(period_end=e, diluted_eps=eps[i], currency=fin, revenue=revenue[i], net_income=net_income[i], ebitda=ebitda[i],
                 ebitda_margin=ebitda[i] / revenue[i], diluted_shares=shares, source='fixture') for i, e in enumerate(ends)]
    d = dict(ticker=ticker, retrieved_at=valuation + 'T00:00:00+00:00', quote=dict(value=price, currency=currency), warnings=[], raw={}, methods={},
             anchors=[dict(id=f'annual:{h["period_end"]}', value=h['diluted_eps'], category='historical_reported', currency=fin, period_end=h['period_end'])
                      for h in hist[::-1]],
             historical=hist[::-1], estimates=[], cashflow=[], cashflow_ttm=None)
    if est:
        for metric, period, v in (('eps', '0y', est[0]), ('eps', '+1y', est[1]), ('revenue', '0y', est[2]), ('revenue', '+1y', est[3])):
            d['estimates'].append(dict(metric=metric, period=period, avg=v, low=v * .95, high=v * 1.05, numberOfAnalysts=n_est, currency=fin, source='fixture'))
    if cash:
        d['cashflow'] = [dict(period_end=e, ocf=ocf[i], capex=capex[i], fcf=ocf[i] + capex[i], sbc=sbc[i]) for i, e in enumerate(ends)][::-1]
        d['cashflow_ttm'] = dict(period_end=mrq, ocf=ttm_cash[0], capex=ttm_cash[1], fcf=ttm_cash[0] + ttm_cash[1], sbc=ttm_cash[2])
    info = dict(trailingPE=pe_t or (price / ttm_eps if ttm_eps else None), forwardPE=pe_f or (price / est[1] if est else None), trailingEps=ttm_eps,
                forwardEps=est[1] if est else None, enterpriseToEbitda=ev_ebitda or (price * shares + debt - cash_bal) / ttm_ebitda, financialCurrency=fin,
                currency=currency, nextFiscalYearEnd=ts(next_fy), mostRecentQuarter=ts(mrq), marketCap=price * shares, sharesOutstanding=shares,
                totalDebt=debt, totalCash=cash_bal, ebitda=ttm_ebitda, enterpriseValue=price * shares + debt - cash_bal, totalRevenue=ttm_rev,
                sector=sector, industry=industry)
    if fx:
        d['fx'] = fx
    return enrich(d, None, info, ())


def days_to(d, end):
    return (date.fromisoformat(end) - date.fromisoformat(d['retrieved_at'][:10])).days / 365.25
