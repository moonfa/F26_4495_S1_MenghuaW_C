"""Comparable valuation references. Never treats reconstructed annual P/E as point-in-time TTM."""
from datetime import date, datetime
from statistics import median
import math


def num(value):
    if value is None or isinstance(value,bool): return None
    try:
        v=float(value)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError): return None


def ratio(price,eps):
    p,e=num(price),num(eps)
    return p/e if p is not None and p>0 and e is not None and e>0 else None


def historical_pe(rows, prices, quote_currency):
    """Close is split-adjusted but not dividend-adjusted in Yahoo auto_adjust=False.
    Annual EPS is as currently supplied/restated, hence inherently ex-post.
    Only nearby prior trading dates are accepted; never select a future close.
    """
    out=[]
    for row in rows:
        end=date.fromisoformat(row['period_end'])
        candidates=[x for x in prices if 0 <= (end-date.fromisoformat(x['date'])).days <= 7]
        close=max(candidates,key=lambda x:x['date']) if candidates else None
        price=close['close'] if close else None
        pe=ratio(price,row.get('diluted_eps')) if row.get('currency')==quote_currency and quote_currency else None
        out.append(dict(period_end=row['period_end'],eps=row.get('diluted_eps'),currency=row.get('currency'),
                        price_date=close['date'] if close else None,close=price,pe=pe,
                        basis='Ex-post fiscal-end close / same-year reported EPS; not point-in-time TTM',
                        status='available' if pe is not None else 'Missing comparable price/EPS/currency, or non-positive EPS'))
    available=[x['pe'] for x in out if x['pe'] is not None]
    return dict(rows=out,median=median(available) if available else None,low=min(available) if available else None,
                high=max(available) if available else None,count=len(available),
                limitations='Sparse annual observations; current/restated EPS and provider split conventions. Not a historical trading P/E series, not suitable for backtesting or a fair-value rule.')


def reference_price(estimate, pe, currency):
    if estimate.get('metric')!='eps' or estimate.get('period') not in ('0y','+1y'):
        raise ValueError('Use annual EPS consensus. Quarterly EPS is not annualized.')
    if not currency or estimate.get('currency')!=currency: raise ValueError('Consensus and quote currencies must match.')
    eps=num(estimate.get('avg')); multiple=num(pe)
    if eps is None or eps<=0 or multiple is None or multiple<=0: raise ValueError('Positive EPS and P/E required.')
    return eps*multiple




# ---------------------------------------------------------------------------------------------
# Dates, anchors and defaults. Pure functions so they can be tested without a network.
# ---------------------------------------------------------------------------------------------
def to_date(value):
    """Epoch seconds, ISO text or a date/datetime -> date; anything else -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=__import__('datetime').timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def add_years(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:                      # 29 February
        return day.replace(year=day.year + years, day=28)


def consensus_period_end(info, period):
    """Map Yahoo's relative annual periods to dates. 0y = the fiscal year now in progress, ending at nextFiscalYearEnd;
    +1y = the one after. Returns an ISO date, or None when the provider gave no fiscal year end."""
    end = to_date((info or {}).get('nextFiscalYearEnd'))
    if end is None or period not in ('0y', '+1y'):
        return None
    return (end if period == '0y' else add_years(end, 1)).isoformat()


def earnings_quality_flags(historical):
    """Generic one-off detection from annual rows (newest first): a net margin far from the prior years' median."""
    margins = []
    for r in historical or []:
        ni, rev = num(r.get('net_income')), num(r.get('revenue'))
        margins.append((r.get('period_end'), ni / rev if ni is not None and rev and rev > 0 else None))
    if len(margins) < 3 or margins[0][1] is None:
        return []
    prior = [m for _, m in margins[1:4] if m is not None]
    if len(prior) < 2:
        return []
    base = median(prior)
    now = margins[0][1]
    out = []
    if now is not None and base > 0.01 and (now > 2 * base or now < 0.4 * base):
        out.append(f"Net margin {now * 100:.1f}% in the latest year versus a median of {base * 100:.1f}% in the prior years: the "
                   "reported EPS may include one-off items. Check the filing before compounding it as recurring earnings.")
    return out


def pct_or_none(v):
    return None if v is None else round(v * 100, 2)


def add_months(day, months):
    y, m = divmod(day.month - 1 + months, 12)
    y, m = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(y, m, d)
        except ValueError:
            continue


def consensus_quarter_end(info, period):
    """Approximate end of Yahoo's relative quarters: 0q = the quarter after the latest reported one, +1q = the next. Quarter ends
    shift by a few days (52-week calendars), so the date is approximate."""
    last = to_date((info or {}).get('mostRecentQuarter'))
    if last is None or period not in ('0q', '+1q'):
        return None
    return add_months(last, 3 if period == '0q' else 6).isoformat()


def growth_refs(data):
    """Growth rates the data itself offers, in percent, each with its basis. No market forecast exists for free cash flow; the
    nearest forward-looking proxies are analyst EPS and revenue growth."""
    est = {(e.get('metric'), e.get('period')): num(e.get('avg')) for e in data.get('estimates') or []}
    hist = sorted(data.get('historical') or [], key=lambda r: str(r.get('period_end')), reverse=True)
    fh = sorted([r for r in data.get('fcf_history') or [] if not r.get('ttm')], key=lambda r: str(r.get('period_end')), reverse=True)
    g = lambda a, b: a / b - 1 if a is not None and b is not None and a > 0 and b > 0 else None
    r1 = lambda v: None if v is None else round(v * 100, 1)
    ends = {e.get('period'): e.get('period_end') for e in data.get('estimates') or [] if e.get('period_end')}
    span = f' (fiscal years to {ends.get("0y")} and {ends.get("+1y")})' if ends.get('0y') and ends.get('+1y') else ''

    def row(i, label, v, basis, methods):
        return dict(id=i, label=label, value=r1(v), basis=basis, methods=methods)
    return [
        row('eps_cons', 'Analyst EPS growth, next year over this year', g(est.get(('eps', '+1y')), est.get(('eps', '0y'))),
            'Consensus mean EPS' + span + '. The only forward-looking earnings growth available.', ['pe', 'p_fcf']),
        row('rev_cons', 'Analyst revenue growth, next year over this year', g(est.get(('revenue', '+1y')), est.get(('revenue', '0y'))),
            'Consensus mean revenue' + span + '. Matches the EV/EBITDA revenue path.', ['ev_ebitda', 'p_fcf']),
        row('rev_last', 'Last reported annual revenue growth', g(num(hist[0].get('revenue')) if hist else None, num(hist[1].get('revenue')) if len(hist) > 1 else None),
            'Latest fiscal year over the one before; backward-looking.', ['ev_ebitda', 'p_fcf']),
        row('eps_last', 'Last reported annual EPS growth', g(num(hist[0].get('diluted_eps')) if hist else None, num(hist[1].get('diluted_eps')) if len(hist) > 1 else None),
            'Latest fiscal year over the one before; backward-looking and noisy.', ['pe']),
        row('fcf_last', 'Last annual free cash flow per share growth', g(fh[0]['fcf_per_share'] if fh else None, fh[1]['fcf_per_share'] if len(fh) > 1 else None),
            'Latest fiscal year over the one before; swings widely when the base is small.', ['p_fcf']),
    ]


DEFAULT_FADE = 5.0   # percent a year; a long-run nominal growth assumption, shown and editable


def pick_pe_anchor(data):
    """Default starting EPS: the furthest analyst year (analysts' numbers first, our growth only after them), else TTM, else the
    latest reported year. Consensus years are used as given; their dates only matter for display."""
    rows = [a for a in data.get('anchors') or [] if (num(a.get('value')) or 0) > 0]
    by = {a['id']: a for a in rows}
    for i in ('consensus:+1y', 'consensus:0y', 'ttm'):
        if i in by:
            return by[i]
    return next((a for a in rows if a.get('category') == 'historical_reported'), None)


def multiple_by_anchor(price, anchors):
    """Today's multiple on each starting point = price / that value. Holding it flat adds nothing from the multiple, whatever
    the anchor: the multiple always sits on the same basis (trailing, or a future year) as the number it multiplies."""
    p = num(price)
    return {a['id']: round(p / a['value'], 2) for a in anchors or []
            if p and p > 0 and num(a.get('value')) and a['value'] > 0 and a.get('id')}


def status_quo(data):
    """Starting values taken from the company's own numbers, in percent units for the form. They describe 'nothing changes',
    not a view; the user edits them. Missing inputs stay None. The exit multiple is today's price divided by the SAME starting
    value the growth is applied to (trailing for TTM, a future year for consensus), so that growth, not a change of basis, is
    what moves the result."""
    cm = data.get('current_multiples') or {}
    hist = sorted(data.get('historical') or [], key=lambda r: str(r.get('period_end')), reverse=True)
    refs = {r['id']: r for r in growth_refs(data)}
    val = lambda i: (refs.get(i) or {}).get('value')
    price = (data.get('quote') or {}).get('value')
    m_ttm = num(data.get('ttm_ebitda_margin'))
    m_now = m_ttm if m_ttm is not None else next((r.get('ebitda_margin') for r in hist if r.get('ebitda_margin') is not None), None)
    pe_anchor = pick_pe_anchor(data)
    pe_map = multiple_by_anchor(price, data.get('anchors'))
    pe_now = pe_map.get(pe_anchor['id']) if pe_anchor else None
    if pe_now is None:
        pe_now = num(cm.get('trailing_pe')) or num(cm.get('forward_pe'))
    ev_now = num(cm.get('enterprise_to_ebitda'))
    r1 = lambda v: None if v is None else round(v, 1)
    fade = lambda g: DEFAULT_FADE if g is not None and g > DEFAULT_FADE else None
    g_pe = val('eps_cons')
    g_fcf, src_fcf = next(((val(i), i) for i in ('eps_cons', 'rev_cons', 'fcf_last') if val(i) is not None), (None, None))
    g_ev, src_ev = next(((val(i), i) for i in ('rev_cons', 'rev_last') if val(i) is not None), (None, None))
    return {
        'unit': 'percent / multiples',
        'note': ('Status quo starting points: start from the furthest analyst year where there is one (else trailing twelve months), '
                 f'grow it at the analyst rate fading to a long-run {DEFAULT_FADE:.0f}% by the exit date, and keep the multiple the market pays '
                 'today on that same starting number. A neutral start, not a view; change one input at a time.'),
        'pe': {'anchor_id': pe_anchor['id'] if pe_anchor else None, 'multiple_by_anchor': pe_map,
               'growth': g_pe, 'growth_source': 'eps_cons' if g_pe is not None else None, 'fade_to': fade(g_pe), 'exit_pe': r1(pe_now),
               'growth_spread': 3.0, 'pe_spread': 10.0},
        'p_fcf': {'growth': g_fcf, 'growth_source': src_fcf, 'fade_to': fade(g_fcf), 'share_change': 0.0, 'growth_spread': 3.0, 'multiple_spread': 10.0},
        'ev_ebitda': {'growth': g_ev, 'growth_source': src_ev, 'fade_to': fade(g_ev), 'margin': r1(pct_or_none(m_now)),
                      'margin_source': 'ttm' if m_ttm is not None else 'last_annual', 'exit_multiple': r1(ev_now),
                      'growth_spread': 2.0, 'margin_spread': 1.0, 'multiple_spread': 10.0},
    }


def pfcf_defaults(data, use_after_sbc):
    """(anchor, {anchor_id: price/value}) for P/FCF. The after-stock-compensation anchor gets its own multiple, so numerator and
    denominator always match."""
    rows = [a for a in data.get('fcf_anchors') or [] if (num(a.get('value')) or 0) > 0]
    by = {a['id']: a for a in rows}
    pick = (by.get('fcfsbc:ttm') if use_after_sbc else None) or by.get('fcf:ttm') or next((a for a in rows if a['id'].startswith('fcf:')), None)
    return pick, multiple_by_anchor((data.get('quote') or {}).get('value'), rows)


def _eps(anchors, i):
    return next((num(a.get('value')) for a in anchors or [] if a.get('id') == i), None)


def earnings_dislocation(data):
    """Detect a trailing EPS far from what analysts expect next (a trough or peak being recovered or given back). Facts only: the
    numbers, the multiples they produce, and the reasons the gap may not be a real recovery. Returns None when nothing stands out."""
    anchors = data.get('anchors') or []
    cm = data.get('current_multiples') or {}
    ttm = _eps(anchors, 'ttm')
    if ttm is None:
        ttm = num(cm.get('trailing_eps'))
    c0, c1 = _eps(anchors, 'consensus:0y'), _eps(anchors, 'consensus:+1y')
    cons = c0 if c0 and c0 > 0 else (c1 if c1 and c1 > 0 else None)
    if ttm is None or cons is None:
        return None
    pe_t, pe_f = num(cm.get('trailing_pe')), num(cm.get('forward_pe'))
    ends = {a['id']: a.get('period_end') for a in anchors}
    kind, jump = None, None
    if ttm <= 0:
        kind = 'loss_to_profit'
    else:
        jump = cons / ttm - 1
        gap = pe_t / pe_f if pe_t and pe_f and pe_f > 0 else None
        if jump >= 0.5 or (gap is not None and gap >= 1.6 and jump > 0.2):
            kind = 'recovery'
        elif jump <= -0.33:
            kind = 'decline'
    if kind is None:
        return None
    fx = lambda v: f'{v:,.2f}'
    hist = [(r.get('period_end'), num(r.get('diluted_eps'))) for r in data.get('historical') or [] if num(r.get('diluted_eps')) is not None]
    peak = max(hist, key=lambda x: x[1]) if hist else None
    lines = []
    parts = [f'Reported trailing EPS {fx(ttm)}']
    if c0:
        parts.append(f'analyst EPS {fx(c0)} for the year to {ends.get("consensus:0y") or "this fiscal year"}' + (f' ({(c0 / ttm - 1) * 100:+.0f}%)' if ttm > 0 else ''))
    if c1:
        parts.append(f'{fx(c1)} for the year to {ends.get("consensus:+1y") or "next year"}' + (f' ({(c1 / ttm - 1) * 100:+.0f}%)' if ttm > 0 else ''))
    lines.append('; '.join(parts) + '.')
    if pe_t and pe_f:
        lines.append(f'Trailing P/E {pe_t:.1f}× against forward {pe_f:.1f}×: the market is pricing the analysts\' numbers, not the trailing ones.')
    if peak and peak[1] > 0 and peak[0]:
        d = cons / peak[1] - 1
        lines.append(f'Highest annual EPS in the reported table: {fx(peak[1])} ({peak[0]}). Analyst EPS is {abs(d) * 100:.0f}% {"above" if d >= 0 else "below"} it.')
    lines.append('Analyst EPS is usually on an adjusted basis; reported EPS includes impairments and other one-off charges. Part of the gap may be accounting basis, not recovery: check the filing before treating the jump as a business turnaround.')
    return dict(kind=kind, ttm_eps=ttm, cons_0y=c0, cons_1y=c1, jump=jump, pe_trailing=pe_t, pe_forward=pe_f,
                peak_eps=peak[1] if peak else None, peak_end=peak[0] if peak else None, lines=lines)


# ---------------------------------------------------------------------------------------------
# Free cash flow per share (P/FCF method). Pure functions; the adapter supplies raw provider rows.
# ---------------------------------------------------------------------------------------------
def fcf_of(row):
    """Free cash flow = the provider's FCF if given, else operating cash flow minus capital expenditure."""
    f = num((row or {}).get('fcf'))
    if f is None:
        o, c = num((row or {}).get('ocf')), num((row or {}).get('capex'))
        if o is not None and c is not None:
            f = o - abs(c)
    return f


def shares_for(hist_row, fallback):
    h = hist_row or {}
    s = num(h.get('diluted_shares'))
    if s and s > 0:
        return s, 'reported diluted average shares'
    ni, eps = num(h.get('net_income')), num(h.get('diluted_eps'))
    if ni and eps and ni > 0 and eps > 0:
        return ni / eps, 'implied from net income / diluted EPS'
    if fallback and fallback > 0:
        return fallback, 'current shares outstanding (approximation)'
    return None, None


def fcf_anchors(cash_rows, ttm_row, historical, shares_now, currency, ticker, now, source, ttm_end=None):
    """Per-share FCF anchors, before and after stock-based compensation. Returns (anchors, rows).
    rows: one dict per period for the history table (fcf, sbc, shares, per-share values, conversion to net income)."""
    by_end = {r.get('period_end'): r for r in historical or []}
    url = f'https://finance.yahoo.com/quote/{ticker}/'
    anchors, rows = [], []

    def one(tag, end, raw, hist_row, ttm, extra=''):
        fcf = fcf_of(raw)
        if fcf is None:
            return
        sbc = num((raw or {}).get('sbc'))
        sh, how = shares_for(hist_row, shares_now)
        if not sh:
            return
        ps, ps_sbc = fcf / sh, (fcf - sbc) / sh if sbc is not None else None
        ni = num((hist_row or {}).get('net_income'))
        rows.append(dict(period_end=end, ttm=ttm, fcf=fcf, sbc=sbc, shares=sh, shares_basis=how, fcf_per_share=ps,
                         fcf_after_sbc_per_share=ps_sbc, conversion=fcf / ni if ni and ni > 0 else None))
        for kind, val, label in (('fcf', ps, 'free cash flow (operating cash flow − capex)'),
                                 ('fcfsbc', ps_sbc, 'free cash flow after stock-based compensation')):
            if val is None:
                continue
            anchors.append(dict(id=f'{kind}:{tag}', value=val, category='ttm_reported' if ttm else 'historical_reported',
                                source=source, currency=currency, period_end=end, published_at=None, retrieved_at=now,
                                unit='currency_per_share', source_url=url,
                                basis=f'{"Trailing twelve months" if ttm else "Annual"} {label} per share; shares: {how}.{extra}'))

    own = to_date((ttm_row or {}).get('period_end'))     # the cash flow's own period end wins; the latest quarter is only a fallback
    end_ttm = own.isoformat() if own else (str(ttm_end)[:10] if ttm_end else None)
    if ttm_row and end_ttm:
        one('ttm', end_ttm, ttm_row, None, True, '' if own else ' Period end taken from the latest reported quarter: the provider gave no date for this figure.')
    for raw in sorted(cash_rows or [], key=lambda r: str(r.get('period_end')), reverse=True):
        end = str(raw.get('period_end'))[:10]
        one(end, end, raw, by_end.get(end), False)
    return anchors, rows


def fcf_status_quo(rows, price, shares_now=None):
    """Starting growth (latest annual per-share FCF change) and multiple (price / TTM or latest FCF per share)."""
    ann = [r for r in rows if not r.get('ttm') and r.get('fcf_per_share')]
    ann.sort(key=lambda r: str(r['period_end']), reverse=True)
    g = ann[0]['fcf_per_share'] / ann[1]['fcf_per_share'] - 1 if len(ann) > 1 and ann[1]['fcf_per_share'] > 0 and ann[0]['fcf_per_share'] > 0 else None
    cur = next((r for r in rows if r.get('ttm')), ann[0] if ann else None)
    mult = price / cur['fcf_per_share'] if cur and price and cur.get('fcf_per_share') and cur['fcf_per_share'] > 0 else None
    return g, mult


# ---------------------------------------------------------------------------------------------
# Multiple references: several rulers for the exit multiple, none of them chosen for the user.
# ---------------------------------------------------------------------------------------------
def industry_summary(peers, label):
    """Medians over a peer set. A median needs at least 3 usable values; PEG = forward P/E ÷ expected EPS growth in %."""
    peers = [p for p in peers or [] if not p.get('error')]
    if len(peers) < 3:
        return None

    def med(key):
        v = [p[key] for p in peers if num(p.get(key)) is not None and p[key] > 0]
        return median(v) if len(v) >= 3 else None
    pegs = []
    for p in peers:
        pe, g = num(p.get('forward_pe')), num(p.get('eps_growth'))
        if pe and pe > 0 and g and g > 0.03:
            pegs.append(pe / (g * 100))
    return dict(label=label, count=len(peers), forward_pe=med('forward_pe'), trailing_pe=med('trailing_pe'), ev_ebitda=med('ev_ebitda'),
                price_to_fcf=med('price_to_fcf'), peg=median(pegs) if len(pegs) >= 3 else None, peg_count=len(pegs),
                growth_basis='provider forward EPS ÷ trailing EPS − 1')
