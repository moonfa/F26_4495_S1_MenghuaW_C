"""One table of fiscal periods, the single source for everything the valuation lab shows or computes from the company's numbers.

Columns run in time order: the last four reported fiscal years (A-3 … A0), the trailing twelve months (reference only, never a step in
a projection), the two analyst years (E0 = the fiscal year in progress, E1 = the next), and then the user's own years, which are only
dates here (U2 … Un: the values come from the user's growth path). Every cell says what it is: reported, TTM, analyst (mean, low,
high, number of analysts) or derived by arithmetic from another cell, with its period end, currency and source.

The engine, the defaults, the reference rows, the growth sources, the Compare page and the company-page link all read this table, so
a number cannot differ between them. Pure functions: no network, no database. Nothing here is a view or a forecast of its own."""
from .valuation_context import num, to_date, add_years

ACTUAL_KEYS = ('A-3', 'A-2', 'A-1', 'A0')
MIN_YEARS, MAX_YEARS = 0.5, 10.01      # exit options: at least half a year away, at most ten years
ROWS = ('revenue', 'ebitda', 'ebitda_margin', 'eps', 'fcf', 'fcf_per_share', 'fcf_per_share_sbc', 'fcf_margin', 'shares')
SERIES_ROW = {'pe': 'eps', 'p_fcf': 'fcf_per_share', 'p_fcf_sbc': 'fcf_per_share_sbc', 'ev_ebitda': 'revenue'}


def fy_label(end):
    return 'FY' + str(end)[:4]


def _cell(value, kind, end, cur, source, **extra):
    v = num(value)
    if v is None:
        return None
    return dict(value=v, kind=kind, period_end=end, currency=cur, source=source, derived=kind == 'derived', **extra)


def _ratio(a, b):
    return a / b - 1 if a is not None and b is not None and a > 0 and b > 0 else None


def _est(data, metric, period):
    return next((e for e in data.get('estimates') or [] if e.get('metric') == metric and e.get('period') == period and num(e.get('avg')) is not None), None)


def next_fy_end(data, last_actual, valuation):
    """End of the fiscal year in progress: the analysts' 0y period end if the provider gave one, else one year on from the last
    reported year (rolled forward past stale data until it lies after the valuation date)."""
    for m in ('eps', 'revenue'):
        e = _est(data, m, '0y')
        d = to_date(e.get('period_end')) if e else None
        if d and d > valuation:
            return d
    base = to_date(last_actual) if last_actual else None
    if base is None:
        return None
    d = add_years(base, 1)
    while d <= valuation:
        d = add_years(d, 1)
    return d


def build_period_table(data):
    cur = (data.get('quote') or {}).get('currency')
    valuation = to_date(data.get('retrieved_at')) or to_date('1970-01-01')
    hist = sorted([r for r in data.get('historical') or [] if to_date(r.get('period_end')) and to_date(r['period_end']) <= valuation],
                  key=lambda r: str(r['period_end']), reverse=True)[:4]
    fcf_by_end = {r.get('period_end'): r for r in data.get('fcf_history') or [] if not r.get('ttm')}
    fcf_ttm = next((r for r in data.get('fcf_history') or [] if r.get('ttm')), None)
    cols, rows = [], {k: {} for k in ROWS}
    src = lambda r: r.get('source') or 'provider'

    # --- reported years --------------------------------------------------------------------------------------------------
    for i, r in enumerate(reversed(hist)):
        key = ACTUAL_KEYS[len(ACTUAL_KEYS) - len(hist) + i]
        end = r['period_end']
        cols.append(dict(key=key, label=fy_label(end), kind='actual', period_end=end))
        f = fcf_by_end.get(end) or {}
        c = r.get('currency') or cur
        rev, ebitda = num(r.get('revenue')), num(r.get('ebitda'))
        for row, v in (('revenue', rev), ('ebitda', ebitda), ('eps', r.get('diluted_eps')), ('fcf', f.get('fcf')),
                       ('fcf_per_share', f.get('fcf_per_share')), ('fcf_per_share_sbc', f.get('fcf_after_sbc_per_share')),
                       ('shares', r.get('diluted_shares') or f.get('shares'))):
            rows[row][key] = _cell(v, 'actual', end, c, src(r))
        if rev and rev > 0 and ebitda is not None:
            rows['ebitda_margin'][key] = _cell(ebitda / rev, 'actual', end, c, 'EBITDA ÷ revenue')
        fv = num(f.get('fcf'))
        if rev and rev > 0 and fv is not None:
            rows['fcf_margin'][key] = _cell(fv / rev, 'actual', end, c, 'FCF ÷ revenue')

    # --- trailing twelve months: reference only --------------------------------------------------------------------------
    ttm_eps = next((a for a in data.get('anchors') or [] if a.get('id') == 'ttm' and num(a.get('value')) is not None), None)
    ttm_rev = next((a for a in data.get('revenue_anchors') or [] if a.get('id') == 'revenue:ttm' and num(a.get('value')) is not None), None)
    b = data.get('market_baseline') or {}
    end_ttm = (ttm_eps or ttm_rev or {}).get('period_end') or (fcf_ttm or {}).get('period_end')
    if end_ttm and (ttm_eps or ttm_rev or fcf_ttm):
        cols.append(dict(key='TTM', label='TTM', kind='ttm', period_end=end_ttm))
        if ttm_eps:
            rows['eps']['TTM'] = _cell(ttm_eps['value'], 'ttm', end_ttm, ttm_eps.get('currency') or cur, ttm_eps.get('source') or 'provider')
        if ttm_rev:
            rows['revenue']['TTM'] = _cell(ttm_rev['value'], 'ttm', end_ttm, ttm_rev.get('currency') or cur, ttm_rev.get('source') or 'provider')
        if ttm_rev and num(b.get('ebitda')) is not None and b.get('currency') in (None, ttm_rev.get('currency')):
            rows['ebitda']['TTM'] = _cell(b['ebitda'], 'ttm', end_ttm, ttm_rev.get('currency') or cur, 'provider EBITDA (trailing)')
            if ttm_rev['value'] > 0:
                rows['ebitda_margin']['TTM'] = _cell(b['ebitda'] / ttm_rev['value'], 'ttm', end_ttm, cur, 'EBITDA ÷ revenue')
        if fcf_ttm:
            rows['fcf']['TTM'] = _cell(fcf_ttm.get('fcf'), 'ttm', end_ttm, cur, 'cash flow statement (trailing)')
            rows['fcf_per_share']['TTM'] = _cell(fcf_ttm.get('fcf_per_share'), 'ttm', end_ttm, cur, 'cash flow statement (trailing)')
            rows['fcf_per_share_sbc']['TTM'] = _cell(fcf_ttm.get('fcf_after_sbc_per_share'), 'ttm', end_ttm, cur, 'cash flow statement (trailing)')
            if ttm_rev and ttm_rev['value'] > 0 and num(fcf_ttm.get('fcf')) is not None:
                rows['fcf_margin']['TTM'] = _cell(fcf_ttm['fcf'] / ttm_rev['value'], 'ttm', end_ttm, cur, 'FCF ÷ revenue')

    # --- analyst years ---------------------------------------------------------------------------------------------------
    last_actual = hist[0]['period_end'] if hist else None
    f0 = next_fy_end(data, last_actual, valuation)
    a0 = {r: (rows[r].get('A0') or {}).get('value') for r in ROWS}
    margin_ref = (rows['ebitda_margin'].get('TTM') or rows['ebitda_margin'].get('A0') or {}).get('value')
    # Cash flow has no consensus. The analyst-year values are revenue growth at a constant margin, and the margin is the NEWER of the last
    # reported year and the trailing twelve months (only when both are positive), so a cyclical company whose margin has already moved is
    # not pulled back to last year's. Which one was used is recorded in table['fcf_base'].
    pos = lambda row, k: ((rows[row].get(k) or {}).get('value') or 0) > 0
    fb = 'TTM' if all(pos(r, 'TTM') for r in ('revenue', 'fcf', 'fcf_per_share')) and all(pos(r, 'A0') for r in ('revenue', 'fcf', 'fcf_per_share')) else 'A0'
    fb_val = {r: (rows[r].get(fb) or {}).get('value') for r in ROWS}
    fb_end = (rows['revenue'].get(fb) or {}).get('period_end')
    ratios = {}
    for k, period in (('E0', '0y'), ('E1', '+1y')):
        eps, rev = _est(data, 'eps', period), _est(data, 'revenue', period)
        end = to_date((eps or rev or {}).get('period_end'))
        end = end.isoformat() if end else (add_years(f0, 0 if k == 'E0' else 1).isoformat() if f0 and (eps or rev) else None)
        if not end or not (eps or rev):
            continue
        cols.append(dict(key=k, label=fy_label(end), kind='analyst', period_end=end))
        for row, e in (('eps', eps), ('revenue', rev)):
            if e:
                rows[row][k] = _cell(e['avg'], 'analyst', end, e.get('currency') or cur, 'analyst consensus mean', low=num(e.get('low')),
                                     high=num(e.get('high')), n=num(e.get('numberOfAnalysts')))
        rv = (rows['revenue'].get(k) or {}).get('value')
        if rv and fb_val['revenue'] and fb_val['revenue'] > 0:
            ratios[k] = rv / fb_val['revenue']
            what = 'latest twelve months' if fb == 'TTM' else 'latest reported year'
            for row in ('fcf', 'fcf_per_share', 'fcf_per_share_sbc'):
                if fb_val[row] is not None and fb_val[row] > 0:
                    rows[row][k] = _cell(fb_val[row] * ratios[k], 'derived', end, cur, f'{what} × analyst revenue growth')
            if margin_ref is not None:
                rows['ebitda'][k] = _cell(rv * margin_ref, 'derived', end, cur, 'analyst revenue × latest EBITDA margin')
                rows['ebitda_margin'][k] = _cell(margin_ref, 'derived', end, cur, 'held at the latest margin')
            if fb_val['fcf'] is not None and fb_val['fcf'] > 0:
                rows['fcf_margin'][k] = _cell(fb_val['fcf'] / fb_val['revenue'], 'derived', end, cur, f'held at the {what} margin')

    # --- growth against the previous fiscal year (TTM is skipped: it is not a fiscal year) -------------------------------------
    order = [c['key'] for c in cols if c['kind'] != 'ttm']
    for row in ('revenue', 'ebitda', 'eps', 'fcf', 'fcf_per_share', 'fcf_per_share_sbc', 'shares'):
        for prev, k in zip(order, order[1:]):
            c, p = rows[row].get(k), rows[row].get(prev)
            if c and p:
                c['growth'] = _ratio(c['value'], p['value'])
    for row in ROWS:
        rows[row] = {k: v for k, v in rows[row].items() if v}

    ends = [f0] if f0 else []
    options = []
    if f0:
        for k in range(0, 12):
            d = add_years(f0, k)
            yrs = (d - valuation).days / 365.25
            if MIN_YEARS <= yrs <= MAX_YEARS:
                options.append(dict(fy=fy_label(d.isoformat()), period_end=d.isoformat(), years=round(yrs, 2)))
    analyst_through = max([c['period_end'] for c in cols if c['kind'] == 'analyst'], default=None)
    return dict(currency=cur, valuation_date=valuation.isoformat(), columns=cols, rows=rows, exit_options=options,
                first_future_end=ends[0].isoformat() if ends else None, fcf_base=dict(which=fb, period_end=fb_end,
                margin=(fb_val['fcf'] / fb_val['revenue']) if fb_val.get('fcf') and fb_val.get('revenue') else None), analyst_through=analyst_through, margin_default=margin_ref,
                note='TTM is shown for reference only. Growth is against the previous fiscal year. Cells marked derived are arithmetic on other cells, not provider data.')


def table_of(data):
    """The data record's table; built on the spot when an older record has none."""
    return data.get('period_table') or build_period_table(data)


def series(table, method, basis='fcf'):
    """What a method projects: the analyst years (fixed), the last known point the user's growth starts from, and a reference
    point (TTM, else the last reported year) for today's multiple and the return split. Raises ValueError with a plain reason."""
    row = SERIES_ROW['p_fcf_sbc' if method == 'p_fcf' and basis == 'fcf_sbc' else method]
    cells = table['rows'].get(row) or {}
    known = []
    for c in table['columns']:
        x = cells.get(c['key']) if c['kind'] == 'analyst' else None
        if x and x['value'] > 0:
            known.append(dict(key=c['key'], period_end=x['period_end'], value=x['value'], kind=x['kind'], growth=x.get('growth'), currency=x.get('currency')))
        elif c['kind'] == 'analyst':
            break
    a0 = cells.get('A0')
    last = known[-1] if known else (dict(key='A0', period_end=a0['period_end'], value=a0['value'], kind='actual', currency=a0.get('currency')) if a0 and a0['value'] > 0 else None)
    if not last:
        raise ValueError({'pe': 'No positive earnings per share to project from.', 'p_fcf': 'No positive free cash flow per share to project from.',
                          'ev_ebitda': 'No positive revenue to project from.'}[method])
    ref = cells.get('TTM') if cells.get('TTM') and cells['TTM']['value'] > 0 else (a0 if a0 and a0['value'] > 0 else None)
    return dict(row=row, known=known, last=last, ref=ref, actual=a0)


def exit_choice(table, exit_fy):
    """The exit option matching a fiscal year end (ISO date, or the FYxxxx label)."""
    for o in table.get('exit_options') or []:
        if exit_fy in (o['period_end'], o['fy']):
            return o
    raise ValueError('Choose one of the fiscal year ends offered in the list (%s).' % ', '.join(o['fy'] for o in table.get('exit_options') or []) if table.get('exit_options')
                     else 'No fiscal year end could be worked out for this company, so no exit year can be chosen.')


def nearest_exit(table, target_years):
    opts = table.get('exit_options') or []
    return min(opts, key=lambda o: abs(o['years'] - target_years)) if opts else None


def steps_between(last_end, exit_end):
    """Whole fiscal years from the last known point to the exit year."""
    return max(0, round((to_date(exit_end) - to_date(last_end)).days / 365.25))


def estimates_used(table):
    """The analyst numbers behind an analysis, kept with it so a later import can say what moved."""
    out = dict(last_actual_end=(table['rows'].get('eps', {}).get('A0') or table['rows'].get('revenue', {}).get('A0') or {}).get('period_end'), eps={}, revenue={})
    for row in ('eps', 'revenue'):
        for c in table['columns']:
            x = table['rows'].get(row, {}).get(c['key'])
            if x and c['kind'] == 'analyst':
                out[row][x['period_end']] = x['value']
    return out
