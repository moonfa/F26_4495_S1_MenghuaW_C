"""Where might an exit multiple sit? Reference points for judging the multiple you choose.

Nothing here is a fair value. A multiple is what the market pays for a growth and risk profile, and it changes as that profile
changes: a company growing 20% today may grow 10% in three years and be priced accordingly. So the page shows several anchors
side by side (today, own history, peers you chose, a rough sector band, growth-implied) and lets the user pick.

SECTOR_BANDS are rough long-run forward P/E ranges kept as plain data so they can be edited (reviewed 2026-10). They are
heuristics, not market data. Live peers, when given, take priority over them.
"""
from statistics import median
from .valuation_context import num

SECTOR_BANDS = {  # (low, high) forward P/E
    'Technology': (18, 30), 'Communication Services': (14, 24), 'Consumer Cyclical': (14, 24),
    'Consumer Defensive': (16, 24), 'Healthcare': (15, 25), 'Financial Services': (9, 15),
    'Industrials': (15, 23), 'Energy': (8, 14), 'Utilities': (13, 19), 'Basic Materials': (11, 18),
}
INDUSTRY_BANDS = {
    'Semiconductors': (12, 22), 'Semiconductor Equipment & Materials': (14, 24), 'Auto Manufacturers': (8, 16),
    'Software - Infrastructure': (22, 35), 'Software - Application': (20, 33), 'Discount Stores': (20, 28),
}
CYCLICAL = {'Semiconductors', 'Semiconductor Equipment & Materials', 'Auto Manufacturers', 'Steel', 'Chemicals',
            'Oil & Gas E&P', 'Oil & Gas Integrated', 'Copper', 'Aluminum', 'Airlines'}
# Rough long-run ranges for the other two multiples, same caveats: hand-set rules of thumb (reviewed 2026-10), not market data.
FCF_BANDS = {'Technology': (20, 35), 'Communication Services': (14, 24), 'Consumer Cyclical': (14, 25), 'Consumer Defensive': (18, 28),
             'Healthcare': (16, 26), 'Industrials': (16, 26), 'Energy': (7, 14), 'Basic Materials': (10, 18)}
FCF_INDUSTRY = {'Semiconductors': (15, 30), 'Semiconductor Equipment & Materials': (18, 30), 'Auto Manufacturers': (8, 16)}
EV_BANDS = {'Technology': (14, 24), 'Communication Services': (7, 12), 'Consumer Cyclical': (8, 14), 'Consumer Defensive': (11, 17),
            'Healthcare': (11, 18), 'Industrials': (10, 16), 'Energy': (4, 8), 'Utilities': (9, 13), 'Basic Materials': (6, 10)}
EV_INDUSTRY = {'Semiconductors': (10, 20), 'Semiconductor Equipment & Materials': (12, 20), 'Auto Manufacturers': (5, 10)}
BAND_SOURCE = 'hand-set long-run range, not computed from data; edit in core/multiples.py; peers override it'
PEG = (1.0, 2.0)   # price/earnings-to-growth range used for the growth-implied check


def current_multiple(data, method):
    d = data.get('defaults') or {}
    return {'pe': (d.get('pe') or {}).get('exit_pe'), 'p_fcf': (d.get('p_fcf') or {}).get('exit_multiple'),
            'ev_ebitda': (d.get('ev_ebitda') or {}).get('exit_multiple')}.get(method)


def sector_band(data, method='pe'):
    ind, sec = data.get('industry'), data.get('sector')
    by_ind, by_sec = {'pe': (INDUSTRY_BANDS, SECTOR_BANDS), 'p_fcf': (FCF_INDUSTRY, FCF_BANDS), 'ev_ebitda': (EV_INDUSTRY, EV_BANDS)}[method]
    if ind in by_ind:
        return by_ind[ind], f'industry rule of thumb ({ind})'
    if sec in by_sec:
        return by_sec[sec], f'sector rule of thumb ({sec})'
    return None, None


def peer_values(data, method):
    key = {'pe': 'forward_pe', 'p_fcf': 'price_to_fcf', 'ev_ebitda': 'ev_ebitda'}[method]
    vals = []
    for p in data.get('peers') or []:
        v = num(p.get(key)) if method != 'pe' else (num(p.get('forward_pe')) or num(p.get('trailing_pe')))
        if v and v > 0:
            vals.append(v)
    return vals


def _today_points(data, method):
    """'Today' rows: price divided by each starting value the method can use, so every row says what the market pays on THAT number."""
    d = data.get('defaults') or {}
    key = {'pe': 'pe', 'p_fcf': 'p_fcf'}.get(method)
    mm = (d.get(key) or {}).get('multiple_by_anchor') or {} if key else {}
    ends = {a['id']: a.get('period_end') for a in (data.get('anchors') or []) + (data.get('fcf_anchors') or [])}
    out = []
    if method == 'pe':
        for i, label, basis in (('ttm', 'Today · on trailing EPS', 'Price ÷ the last twelve months of reported EPS'),
                                ('consensus:0y', 'Today · on this year\'s analyst EPS', 'Price ÷ analyst EPS for the year to {end}'),
                                ('consensus:+1y', 'Today · on next year\'s analyst EPS', 'Price ÷ analyst EPS for the year to {end}')):
            if i in mm:
                out.append(dict(key='today', anchor=i, label=label, low=mm[i], high=mm[i],
                                basis=basis.format(end=ends.get(i) or 'that year') + '. Use the row that matches your starting point: holding it flat adds nothing from the multiple.'))
    elif method == 'p_fcf':
        for i, label in (('fcf:ttm', 'Today · before stock compensation'), ('fcfsbc:ttm', 'Today · after stock compensation')):
            if i in mm:
                out.append(dict(key='today', anchor=i, label=label, low=mm[i], high=mm[i], basis='Price ÷ trailing free cash flow per share on this basis. Use the row that matches your starting point.'))
    if not out:
        cur = current_multiple(data, method)
        if cur:
            out.append(dict(key='today', anchor=None, label='Today', low=cur, high=cur, basis='What the market pays now (default exit multiple)'))
    return out


def multiple_context(data, method):
    """Reference points for the chosen method: list of {key,label,low,high,basis}; plus the single `reference` value used when a
    de-rating case is shown. The reference comes only from data: the median of at least 3 peers, else the company's own annual
    P/E history (P/E, at least 3 years). The hand-set sector bands are shown but never enter a calculation."""
    cur = current_multiple(data, method)
    pts, ref, ref_basis = _today_points(data, method), None, None
    peers = peer_values(data, method)
    if len(peers) >= 2:
        lo, hi, med = min(peers), max(peers), median(peers)
        auto = data.get('peer_source', '').startswith('Yahoo')
        pts.append(dict(key='peers', label=f'{"Industry peers" if auto else "Your peers"} ({len(peers)})', low=lo, high=hi, median=med,
                        basis=f'median {med:.1f}x; ' + (data.get('peer_source') + ', the largest companies, not an industry average' if auto else 'a set you chose, not an industry average')
                              + ('' if len(peers) >= 3 else '; fewer than 3 peers, so not used for the de-rating case')))
        if len(peers) >= 3:
            ref, ref_basis = med, f'median of {len(peers)} ' + ('industry peers' if auto else 'your peers')
    if method == 'pe':
        hp = data.get('historical_pe') or {}
        if (hp.get('count') or 0) >= 2 and hp.get('low') is not None:
            pts.append(dict(key='history', label='Own history (annual, trailing)', low=hp['low'], high=hp['high'],
                            basis=f'median {hp["median"]:.1f}x over {hp["count"]} years; fiscal-year-end price over same-year EPS'))
            if ref is None and (hp.get('count') or 0) >= 3 and hp.get('median'):
                ref, ref_basis = hp['median'], 'own historical median (annual, trailing basis)'
    band, why = sector_band(data, method)
    if band:
        pts.append(dict(key='sector', label='Sector rule of thumb', low=band[0], high=band[1], basis=why + '; ' + BAND_SOURCE + '; shown for context, never used in a calculation'))
    notes = []
    if method == 'pe' and data.get('industry') in CYCLICAL:
        notes.append('Cyclical industry: earnings swing with the cycle, so a P/E on peak or trough EPS misleads. Prefer a mid-cycle earnings base or P/FCF, and expect the multiple to look low at the peak.')
    if method == 'ev_ebitda' and data.get('sector') in ('Financial Services', 'Real Estate'):
        notes.append('EV/EBITDA is not meaningful for banks, insurers and REITs.')
    peg, peg_basis = PEG, 'rule of thumb: PEG 1 to 2'
    ind = data.get('industry_ref') or {}
    if ind.get('peg'):
        peg, peg_basis = (round(ind['peg'] * 0.8, 2), round(ind['peg'] * 1.2, 2)), f'peer median PEG {ind["peg"]:.2f} ± 20% ({ind["peg_count"]} peers)'
    return dict(method=method, current=cur, points=pts, reference=ref, reference_basis=ref_basis, peg=peg, peg_basis=peg_basis, notes=notes)


def derate_target(data, method, held):
    """Exit multiple for the de-rating case: the reference if it is below the held multiple, else the held multiple."""
    ctx = multiple_context(data, method)
    ref = ctx['reference']
    if ref is None or held is None:
        return held, None
    return min(held, ref), ctx['reference_basis']


def method_fit(data):
    """How well each method suits this company, with reasons: {method: {level: fit|caution|avoid, reasons: [...]}, 'recommended': id, 'why': text}.
    Rules of thumb on public data (industry, sector, earnings quality, cash conversion, stock compensation); they guide, they do not decide."""
    ind, sec = data.get('industry'), data.get('sector')
    flags = data.get('earnings_quality_flags') or []
    cm = data.get('current_multiples') or {}
    fcf_rows = [r for r in data.get('fcf_history') or []]
    latest = next((r for r in fcf_rows if r.get('ttm')), fcf_rows[0] if fcf_rows else None)
    out = {m: dict(level='fit', reasons=[]) for m in ('pe', 'p_fcf', 'ev_ebitda')}

    def mark(m, level, why):
        rank = {'fit': 0, 'caution': 1, 'avoid': 2}
        if rank[level] > rank[out[m]['level']]:
            out[m]['level'] = level
        out[m]['reasons'].append(why)
    cyc = ind in CYCLICAL
    fin = sec in ('Financial Services', 'Real Estate')
    if cyc:
        mark('pe', 'caution', 'Cyclical industry: EPS at a peak or trough misleads. If you use P/E, normalise the earnings base.')
        mark('ev_ebitda', 'caution', 'Cyclical industry: EBITDA swings with the cycle and ignores heavy capital spending.')
        out['p_fcf']['reasons'].append('Cash flow is also cyclical, but it already nets out heavy capital spending, so it is the steadier base here.')
    if (num(cm.get('trailing_eps')) or 0) <= 0:
        mark('pe', 'avoid', 'Trailing EPS is zero or negative.')
    for f in flags:
        mark('pe', 'caution', 'Reported earnings look unusual versus prior years (possible one-off).')
        break
    dis = data.get('earnings_dislocation')
    if dis and dis.get('kind') in ('recovery', 'decline'):
        mark('pe', 'caution', 'Reported EPS and analyst EPS are far apart (earnings recovering or falling back): start from the analyst year, not trailing earnings, and read the "what you must believe" grid.')
    if fin:
        mark('ev_ebitda', 'avoid', 'Not meaningful for banks, insurers and REITs.')
        mark('p_fcf', 'avoid', 'Free cash flow is not meaningful for banks and insurers.')
    anchors = [a for a in data.get('fcf_anchors') or [] if (a.get('value') or 0) > 0]
    if not anchors:
        mark('p_fcf', 'avoid', 'No positive free cash flow per share.')
    elif latest:
        conv = latest.get('conversion')
        if conv is not None and (conv < .5 or conv > 1.5):
            mark('p_fcf', 'caution', f'Free cash flow is {conv * 100:.0f}% of net income: unusual conversion, check capex timing and one-offs.')
        if latest.get('sbc') and latest.get('fcf') and latest['fcf'] > 0 and latest['sbc'] / latest['fcf'] > .25:
            out['p_fcf']['use_after_sbc'] = True
            mark('p_fcf', 'caution', f'Stock-based compensation is {latest["sbc"] / latest["fcf"] * 100:.0f}% of free cash flow: use the "after stock compensation" starting point.')
    if (data.get('market_baseline') or {}).get('net_debt') is None or not (cm.get('enterprise_to_ebitda')):
        mark('ev_ebitda', 'avoid', 'No net debt or EV/EBITDA from the provider.')
    ec = data.get('ev_check')
    if ec and not ec.get('ok'):
        mark('ev_ebitda', 'avoid', 'Share count, net debt and provider enterprise value do not reconcile (ADR or share-class mismatch).')
    sc = data.get('share_check') or {}
    if sc.get('differs'):
        mark('p_fcf', 'caution', 'Provider share count and market cap / price differ by more than 25% (share classes or ADR ratio); per-share cash flow is approximate.')
    order = ('p_fcf', 'pe', 'ev_ebitda') if cyc else ('pe', 'p_fcf', 'ev_ebitda')
    good = [m for m in order if out[m]['level'] == 'fit'] or [m for m in order if out[m]['level'] == 'caution']
    rec = good[0] if good else None
    why = {'p_fcf': 'cash flow is the steadier, cost-aware base for this company', 'pe': 'earnings are positive and no rule flags them',
           'ev_ebitda': 'the other methods do not fit'}.get(rec)
    out['recommended'] = rec
    out['why'] = why
    return out
