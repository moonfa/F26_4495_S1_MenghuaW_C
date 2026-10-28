"""Situation: what kind of business this is, what state its earnings are in, and what that means for the valuation method.

Rules on the public numbers already in the data record and the result. It changes no valuation input, never ranks a company and never
decides: every tag says what it was based on, and tags that are only candidates wait for the user to confirm or dismiss them.
Thresholds are in THRESH (one place); an industry can override some of them in INDUSTRY_THRESH.

Parts:
- archetype: the kind of business, from the industry (the user may override it);
- states: tags about earnings (observed stable earnings, volatility, recovery, accounting distortion, persistent loss);
- characteristics: dividend with coverage, leverage, capital intensity, dilution, buybacks;
- suitability: Supported / Limited / Unsupported for each method, with the reason, and a plain method warning;
- confidence: four separate evidence statements (no combined score);
- implied: the margin the price already asks for at the exit, against the margins the company has reported."""
from .multiples import CYCLICAL, method_fit
from .period_table import table_of, fy_label
from .valuation_context import num

THRESH = dict(
    stable_years=3,          # reported years needed to call earnings "observed stable"
    stable_range=0.35,       # (max − min) ÷ mean of EPS across those years
    volatile_range=0.60,     # above this the earnings are volatile
    loss_years=2,            # loss years (with a loss in the trailing figure too) for "persistent loss"
    leverage=3.0,            # net debt ÷ EBITDA
    capex_share=0.60,        # capex ÷ operating cash flow
    dividend_min=0.02,       # yield from which the dividend is shown
    eps_cover_min=1.2,       # EPS ÷ dividend per share below this: coverage warning
    fcf_cover_min=1.0,       # FCF ÷ dividends paid below this: coverage warning
    dilution=0.03,           # yearly share growth
    buyback=-0.03,           # yearly share shrink
    few_analysts=3, many_analysts=5, wide=0.5,
    implied_tiers=(1.0, 1.2, 1.5),
)
INDUSTRY_THRESH = {   # only the keys listed change
    'Utilities': dict(leverage=5.0, capex_share=0.9),
    'Telecom Services': dict(leverage=4.0, capex_share=0.8),
    'Oil & Gas Integrated': dict(volatile_range=0.9),
    'Oil & Gas E&P': dict(volatile_range=0.9),
}
LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}
LEVEL = {'fit': 'Supported', 'caution': 'Limited', 'avoid': 'Unsupported'}
RANK = {'Supported': 0, 'Limited': 1, 'Unsupported': 2}

ARCHETYPES = {
    'financial': dict(label='Financial (balance sheet is the business)', note='Debt is raw material and capital rules matter; EBITDA and free cash flow are not meaningful.',
                      methods=dict(pe=('Supported', ''), p_fcf=('Unsupported', 'Operating cash flow of a bank or insurer includes deposits and float.'),
                                   ev_ebitda=('Unsupported', 'Net debt and EBITDA are not meaningful for a financial company.'))),
    'reit': dict(label='Real-estate holder (REIT)', note='Earnings are depressed by depreciation; the usual measure is funds from operations (FFO), which this lab does not have.',
                 methods=dict(pe=('Limited', 'Depreciation makes EPS understate cash earnings; FFO is the usual measure and is not available here.'),
                              p_fcf=('Limited', 'Free cash flow after property purchases is lumpy.'), ev_ebitda=('Limited', 'Reasonable, but leverage drives the equity answer.'))),
    'utility': dict(label='Regulated / infrastructure', note='Steady, capital-heavy, debt-funded; growth is set by the regulated asset base.',
                    methods=dict(pe=('Supported', ''), p_fcf=('Limited', 'Heavy capital spending keeps free cash flow low or negative while the asset base grows.'),
                                 ev_ebitda=('Supported', ''))),
    'cyclical': dict(label='Cyclical (earnings follow the cycle)', note='Earnings and margins swing with prices or demand; a multiple on a peak or trough year misleads.',
                     methods=dict(pe=('Limited', 'EPS at a peak or trough misleads; a normalised EPS is a better base.'),
                                  p_fcf=('Limited', 'Cash flow swings with the cycle and with capital spending.'), ev_ebitda=('Limited', 'EBITDA swings with the cycle too.'))),
    'growth': dict(label='Growth / platform', note='Value rests on years of high growth; the exit multiple is a large part of the answer.',
                   methods=dict(pe=('Supported', ''), p_fcf=('Supported', ''), ev_ebitda=('Supported', ''))),
    'general': dict(label='General operating company', note='No special structure recognised from the industry.',
                    methods=dict(pe=('Supported', ''), p_fcf=('Supported', ''), ev_ebitda=('Supported', ''))),
}


def thresh(data):
    t = dict(THRESH)
    t.update(INDUSTRY_THRESH.get(data.get('industry'), {}))
    return t


def archetype_of(data):
    ind, sec = data.get('industry') or '', data.get('sector') or ''
    if 'REIT' in ind or sec == 'Real Estate':
        key = 'reit'
    elif sec == 'Financial Services' and any(w in ind for w in ('Bank', 'Insurance', 'Capital Markets', 'Credit', 'Asset Management', 'Mortgage')):
        key = 'financial'
    elif sec == 'Utilities' or ind in ('Telecom Services', 'Pipelines', 'Oil & Gas Midstream'):
        key = 'utility'
    elif ind in CYCLICAL:
        key = 'cyclical'
    elif any(w in ind for w in ('Software', 'Internet', 'Semiconductors')) and ind not in CYCLICAL:
        key = 'growth'
    else:
        key = 'general'
    return dict(key=key, label=ARCHETYPES[key]['label'], note=ARCHETYPES[key]['note'], industry=ind or None, sector=sec or None)


def _hist(data):
    """Reported annual rows, oldest first, with positive-or-not-None EPS only where it exists."""
    return [r for r in reversed(data.get('historical') or []) if r.get('diluted_eps') is not None]


def states_of(data, t):
    hist = _hist(data)
    eps = [num(r['diluted_eps']) for r in hist]
    eps = [e for e in eps if e is not None]
    out = []
    add = lambda id_, label, status, evidence: out.append(dict(id=id_, label=label, status=status, evidence=evidence))
    cm = data.get('current_multiples') or {}
    ttm = num(cm.get('trailing_eps'))
    n = len(eps)
    if n >= t['stable_years'] and all(e > 0 for e in eps):
        mean = sum(eps) / n
        rng = (max(eps) - min(eps)) / mean
        if rng <= t['stable_range']:
            add('stable', 'Observed stable earnings', 'observed',
                f'EPS positive in all {n} reported years, from {min(eps):.2f} to {max(eps):.2f} (range {rng * 100:.0f}% of the average). This describes only these {n} years; it is not a forecast.')
        elif rng > t['volatile_range']:
            add('volatile', 'Earnings volatility', 'observed', f'EPS ranged from {min(eps):.2f} to {max(eps):.2f} over {n} reported years, {rng * 100:.0f}% of the average.')
    elif n >= 2 and any(e <= 0 for e in eps):
        add('volatile', 'Earnings volatility', 'observed', f'EPS was a loss in {sum(1 for e in eps if e <= 0)} of {n} reported years.')
    losses = sum(1 for e in eps if e <= 0)
    if losses >= t['loss_years'] and (ttm is None or ttm <= 0):
        add('persistent_loss', 'Persistent loss', 'observed', f'EPS was a loss in {losses} of {n} reported years and the trailing figure is not positive.')
    dis = data.get('earnings_dislocation') or {}
    if dis.get('kind') in ('recovery', 'loss_to_profit'):
        add('recovery', 'Recovery expected', 'candidate',
            'Analysts expect earnings well above the trailing figure' + (f' (trailing EPS {ttm:.2f})' if ttm is not None else '') + '. Whether this is a real recovery or a forecast that may not come is for you to decide.')
    flags = data.get('earnings_quality_flags') or []
    if flags:
        add('distortion', 'Accounting distortion', 'candidate', flags[0])
    else:
        conv = [r.get('conversion') for r in data.get('fcf_history') or [] if not r.get('ttm') and r.get('conversion') is not None]
        if len(conv) >= 2 and (all(c < 0.3 for c in conv) or all(c > 2.5 for c in conv)):
            add('distortion', 'Accounting distortion', 'candidate',
                f'Free cash flow was {min(conv):.1f}x to {max(conv):.1f}x net income in each reported year: profit and cash tell very different stories.')
    return out


def characteristics_of(data, t):
    out = []
    add = lambda id_, label, text, warn=False: out.append(dict(id=id_, label=label, text=text, warn=warn))
    tbl = table_of(data)
    cm = data.get('current_multiples') or {}
    price = (data.get('quote') or {}).get('value')
    dy = cm.get('dividend_yield')
    if dy and dy >= t['dividend_min'] and price:
        dps = dy * price
        txt = [f'Yield about {dy * 100:.1f}% (about {dps:.2f} per share).']
        warn = False
        eps = num(cm.get('trailing_eps'))
        if eps and eps > 0:
            cover = eps / dps
            txt.append(f'Trailing EPS covers it {cover:.1f}x.')
            warn = cover < t['eps_cover_min']
        elif eps is not None:
            txt.append('Trailing EPS is not positive, so earnings do not cover it.')
            warn = True
        latest = next((r for r in data.get('fcf_history') or [] if r.get('ttm')), None) or next(iter(data.get('fcf_history') or []), None)
        sh = (data.get('market_baseline') or {}).get('shares') or (latest or {}).get('shares')
        if latest and sh and latest.get('fcf') is not None:
            cover = latest['fcf'] / (dps * sh)
            txt.append(f'Free cash flow covers it {cover:.1f}x.')
            warn = warn or cover < t['fcf_cover_min']
        else:
            txt.append('Cash coverage not evaluated (no cash-flow figure).')
        if warn:
            txt.append('Coverage warning: the dividend is not comfortably paid from earnings or cash flow. A high yield can be a sign of that.')
        add('dividend', 'Dividend', ' '.join(txt), warn)
    b = data.get('market_baseline') or {}
    if b.get('net_debt') is not None and b.get('ebitda') and b['ebitda'] > 0:
        lev = b['net_debt'] / b['ebitda']
        if lev > t['leverage']:
            add('leverage', 'High leverage', f'Net debt is {lev:.1f}x EBITDA (flag above {t["leverage"]:g}x). Interest coverage is not evaluated: the data has no interest expense.', True)
    elif b.get('net_debt') is not None and b.get('ebitda') is not None and b['ebitda'] <= 0 and b['net_debt'] > 0:
        add('leverage', 'High leverage', 'Net debt with no positive EBITDA to carry it. Interest coverage is not evaluated.', True)
    rows = [r for r in data.get('fcf_history') or [] if not r.get('ttm') and r.get('ocf') and r.get('capex') is not None]
    if rows:
        r = rows[0]
        share = abs(r['capex']) / r['ocf'] if r['ocf'] > 0 else None
        if share is not None and share > t['capex_share']:
            add('capex', 'High capital spending', f'Capital spending was {share * 100:.0f}% of operating cash flow in {fy_label(r["period_end"])} (flag above {t["capex_share"] * 100:.0f}%). Free cash flow is what is left.')
    sh = (tbl['rows'].get('shares') or {})
    cells = [sh[k] for k in ('A-2', 'A-1', 'A0') if sh.get(k) and sh[k].get('growth') is not None]
    if len(cells) >= 2:
        avg = sum(c['growth'] for c in cells) / len(cells)
        if avg >= t['dilution']:
            add('dilution', 'Dilution', f'The share count grew about {avg * 100:.1f}% a year over the last {len(cells)} reported years. Per-share growth is lower than total growth.')
        elif avg <= t['buyback']:
            add('buyback', 'Buyback-heavy', f'The share count fell about {abs(avg) * 100:.1f}% a year over the last {len(cells)} reported years. Per-share growth is higher than total growth; check it is paid from cash flow, not debt.')
    return out


def suitability_of(data, arch, states, chars):
    """{method: {level, reasons}} from the existing fit rules, the archetype and the earnings state. The worst reading wins."""
    fit = data.get('method_fit') or method_fit(data)
    ids = {s['id'] for s in states}
    out = {}
    for m in ('pe', 'p_fcf', 'ev_ebitda'):
        lvl, reasons = LEVEL[(fit.get(m) or {}).get('level', 'fit')], list((fit.get(m) or {}).get('reasons') or [])
        al, ar = ARCHETYPES[arch['key']]['methods'][m]
        if RANK[al] > RANK[lvl]:
            lvl = al
        if ar:
            reasons.append(ar)
        if m == 'pe' and 'persistent_loss' in ids:
            lvl = 'Unsupported'
            reasons.append('Earnings have been negative; a multiple of a loss means nothing.')
        if m == 'pe' and 'volatile' in ids and RANK[lvl] < 1:
            lvl = 'Limited'
            reasons.append('Earnings swing from year to year, so a multiple of one year misleads.')
        if m == 'ev_ebitda' and any(c['id'] == 'leverage' for c in chars) and RANK[lvl] < 1:
            lvl = 'Limited'
            reasons.append('With high leverage the equity value is a small difference of two large numbers.')
        out[m] = dict(level=lvl, reasons=list(dict.fromkeys(reasons)))
    return out


def confidence_of(data, suit, method, t):
    """Four separate statements about the evidence. They are not added up."""
    hist = _hist(data)
    out = []
    add = lambda id_, label, level, why: out.append(dict(id=id_, label=label, level=level, why=why))
    n = len(hist)
    has_cash = bool(data.get('fcf_history'))
    if n >= 4 and has_cash:
        add('data', 'Data quality', 'Adequate', f'{n} reported years of EPS, revenue and EBITDA, plus cash-flow history.')
    elif n >= 3:
        add('data', 'Data quality', 'Limited', f'{n} reported years' + ('' if has_cash else ' and no cash-flow history') + '.')
    else:
        add('data', 'Data quality', 'Insufficient Evidence', f'Only {n} reported year{"s" if n != 1 else ""} of earnings.')
    flags = data.get('earnings_quality_flags') or []
    eps = [num(r['diluted_eps']) for r in hist if num(r.get('diluted_eps')) is not None]
    if eps and sum(1 for e in eps if e <= 0) >= t['loss_years']:
        add('earnings', 'Earnings quality', 'Insufficient Evidence', 'Repeated losses: reported earnings are not a base to project.')
    elif flags or (data.get('earnings_dislocation') or {}).get('kind'):
        add('earnings', 'Earnings quality', 'Limited', 'The trailing figure is far from the one-off-free or the expected level; see the earnings tags.')
    elif len(eps) >= 3:
        add('earnings', 'Earnings quality', 'Adequate', 'No one-off or dislocation flagged in the reported years.')
    else:
        add('earnings', 'Earnings quality', 'Insufficient Evidence', 'Too few years to judge.')
    tbl = table_of(data)
    cells = [(tbl['rows'].get('eps') or {}).get(c['key']) for c in tbl['columns'] if c['kind'] == 'analyst']
    cells = [c for c in cells if c and c.get('kind') == 'analyst']
    if not cells:
        add('forecast', 'Forecast evidence quality', 'Insufficient Evidence', 'No analyst estimates in the data.')
    else:
        ns = [c.get('n') for c in cells]
        n_a = None if any(n is None for n in ns) else min(ns)
        wide = any(c.get('low') is not None and c.get('high') is not None and c['value'] > 0 and (c['high'] - c['low']) / c['value'] > t['wide'] for c in cells)
        if n_a is None:
            add('forecast', 'Forecast evidence quality', 'Limited', 'Estimates are present but the number of analysts behind them is not given.')
        elif n_a < t['few_analysts']:
            add('forecast', 'Forecast evidence quality', 'Insufficient Evidence', f'As few as {n_a:.0f} analysts cover an estimate year: not a consensus.')
        elif n_a < t['many_analysts'] or wide:
            add('forecast', 'Forecast evidence quality', 'Limited', f'{n_a:.0f} analysts at the thinnest year' + ('; the estimates are far apart.' if wide else '.'))
        else:
            add('forecast', 'Forecast evidence quality', 'Adequate', f'{n_a:.0f} or more analysts on every estimate year, with a reasonable spread.')
    s = suit[method]
    add('method', 'Method suitability', {'Supported': 'Adequate', 'Limited': 'Limited', 'Unsupported': 'Insufficient Evidence'}[s['level']],
        f'{LABEL[method]} is {s["level"].lower()} for this company.')
    return out


def warning_of(method, suit, states, arch):
    s = suit[method]
    if s['level'] == 'Supported':
        return None
    head = f'{LABEL[method]} is {s["level"].lower()} for this company ({arch["label"].split(" (")[0].lower()}).'
    alt = [LABEL[m] for m in ('pe', 'p_fcf', 'ev_ebitda') if m != method and suit[m]['level'] == 'Supported']
    tail = f' Better supported here: {", ".join(alt)}.' if alt else ' None of the three methods in this lab is well supported for this company; treat any result as a rough guide.'
    return dict(level=s['level'], text=head + ' ' + ' '.join(s['reasons'][:3]) + tail)


def _tier(ratio, t):
    a, b, c = t['implied_tiers']
    return 'within the range the company has reported' if ratio <= a else 'above the best reported margin' if ratio <= b else 'well above the best reported margin' if ratio <= c else 'far above anything reported'


def implied_of(data, a, res, t):
    """The margin that the required exit figure implies, against the margins reported so far. A reverse check: what the price asks for, not a forecast.
    For P/E and P/FCF the revenue at exit is the last known revenue grown at the analysts' last revenue growth (0–15%) for the user's years; approximate."""
    tbl = table_of(data)
    method = a.method
    mult = getattr(a, 'exit_pe' if method == 'pe' else 'exit_multiple')
    price_need = res.get('required_exit_price')
    rev = tbl['rows'].get('revenue') or {}
    known = [c for c in tbl['columns'] if c['kind'] in ('actual', 'analyst') and rev.get(c['key'])]
    if not price_need or not mult or not known:
        return None
    last = rev[known[-1]['key']]
    if method == 'ev_ebitda':
        r = res['reverse']
        need_margin, name = r['required_margin'], 'EBITDA margin'
        hist = [(tbl['rows'].get('ebitda_margin') or {}).get(c['key']) for c in tbl['columns'] if c['kind'] == 'actual']
        rev_note = 'on your Base revenue at the exit'
    else:
        sh = (tbl['rows'].get('shares') or {}).get('A0') or {}
        shares = sh.get('value') or (data.get('market_baseline') or {}).get('shares')
        if not shares:
            return None
        g = None
        a_rev = [rev[c['key']] for c in known if c['kind'] == 'analyst']
        if len(a_rev) >= 1:
            g = a_rev[-1].get('growth')
        g = min(max(g if g is not None else 0.0, 0.0), 0.15)
        exit_rev = last['value'] * (1 + g) ** max(res.get('user_years') or 0, 0)
        need_per_share = price_need / mult
        need_total = need_per_share * shares
        need_margin = need_total / exit_rev
        if method == 'pe':
            name = 'net margin'
            hist = []
            for c in tbl['columns']:
                if c['kind'] != 'actual':
                    continue
                row = next((r for r in data.get('historical') or [] if r.get('period_end') == rev[c['key']]['period_end']), None) if rev.get(c['key']) else None
                ni, rv = num((row or {}).get('net_income')), num((row or {}).get('revenue'))
                hist.append(dict(value=ni / rv, period_end=row['period_end']) if ni is not None and rv else None)
        else:
            name = 'free-cash-flow margin'
            hist = [(tbl['rows'].get('fcf_margin') or {}).get(c['key']) for c in tbl['columns'] if c['kind'] == 'actual']
        rev_note = f'on revenue of about {exit_rev:,.0f} at the exit (the last known figure grown {g * 100:.0f}% a year)'
    hist = [h for h in hist if h and h.get('value') is not None]
    if not hist:
        return dict(name=name, required=need_margin, tier=None, text=f'The required exit {name} is {need_margin * 100:.1f}% {rev_note}. No reported margin to compare with.')
    best = max(h['value'] for h in hist)
    last_m = hist[-1]['value']
    ratio = need_margin / best if best > 0 else None
    if need_margin <= 0:
        return dict(name=name, required=need_margin, tier=None, text=f'The required exit {name} is not positive: the price is already below what the required return needs.')
    if ratio is None:
        return dict(name=name, required=need_margin, tier=None, text=f'The required exit {name} is {need_margin * 100:.1f}%; the company reported no positive {name} to compare with.')
    tier = _tier(ratio, t)
    return dict(name=name, required=need_margin, best=best, latest=last_m, ratio=ratio, tier=tier, flag=ratio > t['implied_tiers'][1],
                text=f'To earn {a.required_return * 100:.0f}% a year at an exit multiple of {mult:g}x, the {name} must reach {need_margin * 100:.1f}% {rev_note}. '
                     f'The company reported {last_m * 100:.1f}% last and {best * 100:.1f}% at best ({len(hist)} years): the requirement is {ratio:.2f}x the best, {tier}.')


def situation(data, a, res, review=None):
    """The whole block for one result; a plain dict stored with a saved analysis. `review` is what the user saved earlier (tag statuses, archetype override, note)."""
    t = thresh(data)
    arch = archetype_of(data)
    review = review or {}
    ov = review.get('archetype')
    if ov in ARCHETYPES and ov != arch['key']:
        arch = dict(arch, key=ov, label=ARCHETYPES[ov]['label'], note=ARCHETYPES[ov]['note'], overridden=True, detected=arch['label'])
    states = states_of(data, t)
    for s in states:
        s['user'] = (review.get('states') or {}).get(s['id'])    # confirmed | dismissed | None
    chars = characteristics_of(data, t)
    suit = suitability_of(data, arch, [s for s in states if s['user'] != 'dismissed'], chars)
    try:
        imp = implied_of(data, a, res, t)
    except (KeyError, TypeError, ZeroDivisionError, ValueError):
        imp = None
    return dict(archetype=arch, states=states, characteristics=chars, suitability=suit, warning=warning_of(a.method, suit, states, arch),
                confidence=confidence_of(data, suit, a.method, t), implied=imp, review=dict(archetype=review.get('archetype'), states=review.get('states') or {}, note=review.get('note') or ''),
                archetypes={k: v['label'] for k, v in ARCHETYPES.items()})
