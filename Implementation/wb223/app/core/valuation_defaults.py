"""The one place that decides the status-quo inputs, read from the period table. The company form, the Compare page and the company-page
link all use this, so the same company never gets two different defaults.

Rules (a neutral start, not a view; the user edits them):
- exit year: the fiscal year end nearest to three years from the valuation date;
- growth for the user's first year: the analysts' last-year growth (next year over this year), the rate the analyst numbers end on;
  P/FCF and EV/EBITDA use revenue growth (no cash-flow or EBITDA consensus exists); fading to a long-run 5% by the exit year;
- exit multiple: what the market pays today on this fiscal year's figure, trailing basis (price ÷ the first analyst year), else on
  the trailing twelve months. A multiple above a sensible limit is shown but never pre-filled (a tiny base, not a rich market)."""
from .period_table import table_of, series, nearest_exit, fy_label
from .valuation_context import num, meaningful, withheld_note, pct_or_none

DEFAULT_FADE = 5.0          # percent a year; a long-run nominal growth assumption, shown and editable
DEFAULT_YEARS = 3.0
r1 = lambda v: None if v is None else round(v, 1)


def _g(a, b):
    return a / b - 1 if a is not None and b is not None and a > 0 and b > 0 else None


def growth_refs(data):
    """Growth rates the table offers, in percent, each with its basis. No market forecast exists for free cash flow or EBITDA."""
    t = table_of(data)
    rows, cols = t['rows'], {c['key']: c for c in t['columns']}
    lab = lambda k: fy_label(cols[k]['period_end']) if k in cols else k
    cell = lambda row, k: (rows.get(row) or {}).get(k)
    val = lambda row, k: (cell(row, k) or {}).get('value')
    out = []

    def add(i, label, v, basis, methods):
        out.append(dict(id=i, label=label, value=None if v is None else round(v * 100, 1), basis=basis, methods=methods))
    for row, tag, noun, methods in (('eps', 'eps', 'EPS', ['pe']), ('revenue', 'rev', 'revenue', ['ev_ebitda', 'p_fcf'])):
        add(f'{tag}_e1', f'Analyst {noun} growth, {lab("E1")} over {lab("E0")}', _g(val(row, 'E1'), val(row, 'E0')),
            f'Consensus mean {noun}. The rate the analyst numbers end on: the natural start for your own years.', methods)
        add(f'{tag}_e0', f'Analyst {noun} growth, {lab("E0")} over {lab("A0")}', _g(val(row, 'E0'), val(row, 'A0')),
            f'Consensus mean {noun} for the year in progress over the last reported year.', methods)
        add(f'{tag}_last', f'Reported {noun} growth, {lab("A0")} over {lab("A-1")}', _g(val(row, 'A0'), val(row, 'A-1')),
            'Last fiscal year over the one before; backward-looking' + (' and noisy.' if tag == 'eps' else '.'), methods)
    add('fcf_last', f'Reported FCF per share growth, {lab("A0")} over {lab("A-1")}', _g(val('fcf_per_share', 'A0'), val('fcf_per_share', 'A-1')),
        'Last fiscal year over the one before; swings widely when the base is small.', ['p_fcf'])
    return out


def _pick(refs, ids):
    by = {r['id']: r for r in refs}
    return next(((by[i]['value'], i) for i in ids if i in by and by[i]['value'] is not None), (None, None))


def _on_e0(price, ser):
    """(multiple, which figure it is on) — this fiscal year's analyst figure if there is one, else the trailing one."""
    if ser['known'] and ser['known'][0]['value'] > 0:
        return price / ser['known'][0]['value'], 'E0'
    if ser['ref'] and ser['ref']['value'] > 0:
        return price / ser['ref']['value'], 'TTM'
    return None, None


CAP_FACTOR = 1.5      # a default exit multiple more than this many times the top of the reference range is pulled back to the top
GROWTH_CAP = 25.0     # percent; the growth of an analyst rebound year is not carried into the user's years above this
LABEL = {'pe': 'P/E', 'p_fcf': 'P/FCF', 'ev_ebitda': 'EV/EBITDA'}


def ceiling(data, method):
    """The top of what the data and the rule-of-thumb bands call a normal multiple: the higher of the sector/industry band top and the
    company's own historical high (P/E). None when neither exists."""
    from .multiples import sector_band
    band, _ = sector_band(data, method)
    tops = [band[1]] if band else []
    if method == 'pe':
        from .multiples import history_stats
        hp = history_stats(data)
        if hp:
            tops.append(hp['high'])
    return max(tops) if tops else None


def _set(method, mult, on, data=None):
    ok = meaningful(method, mult)
    cap = ceiling(data, method) if (data is not None and ok) else None
    if ok and cap and mult > CAP_FACTOR * cap:
        return r1(cap), on, (f"Today's {LABEL[method]} on {'this year\'s figure' if on == 'E0' else 'the trailing figure'} is {mult:,.1f}x, more than 1.5x the top of the reference "
                             f"range ({cap:,.0f}x), because the growth the market expects is not expected to last. The default exit multiple is the top of the range ({cap:,.0f}x); "
                             "today's multiple stays in the reference table and you can type it.")
    return (r1(mult) if ok else None), on, (None if mult is None or ok else withheld_note(method, mult))


def _cap_growth(g):
    """(growth, note): a rate above GROWTH_CAP is cut back for the first user year, with the reason."""
    if g is not None and g > GROWTH_CAP:
        return GROWTH_CAP, f'The analysts\' last-year growth is {g:.1f}%. A rate that high usually follows a rebound or a low base, so the default for your first year is {GROWTH_CAP:.0f}%.'
    return g, None


def build_defaults(data, method_fit=None):
    t = table_of(data)
    price = (data.get('quote') or {}).get('value')
    refs = growth_refs(data)
    fade = lambda g: DEFAULT_FADE if g is not None and g > DEFAULT_FADE else None
    near = nearest_exit(t, DEFAULT_YEARS)
    out = {'unit': 'percent / multiples', 'exit_fy': near['period_end'] if near else None, 'exit_label': near['fy'] if near else None,
           'note': ('Status quo starting points: sell at the fiscal year end nearest three years out; the analysts\' years are used as given; your growth starts at '
                    f'the rate they end on and fades to a long-run {DEFAULT_FADE:.0f}% by the exit year; the exit multiple is what the market pays today on this '
                    "year's figure. A neutral start, not a view; change one input at a time.")}
    # --- P/E -------------------------------------------------------------------------------------------------------------
    g, src = _pick(refs, ('eps_e1', 'eps_e0', 'eps_last'))
    g, gnote = _cap_growth(g)
    try:
        mult, on = _on_e0(price, series(t, 'pe')) if price else (None, None)
    except ValueError:
        mult, on = None, None
    em, on, note = _set('pe', mult, on, data)
    out['pe'] = dict(growth=g, growth_note=gnote, growth_source=src, fade_to=fade(g), exit_pe=em, multiple_on=on, multiple_note=note, growth_spread=3.0, pe_spread=10.0)
    # --- P/FCF -----------------------------------------------------------------------------------------------------------
    after = bool(((method_fit or data.get('method_fit') or {}).get('p_fcf') or {}).get('use_after_sbc'))
    gf, srcf = _pick(refs, ('rev_e1', 'rev_e0', 'rev_last', 'fcf_last'))
    gf, gfnote = _cap_growth(gf)
    by = {}
    for basis in ('fcf', 'fcf_sbc'):
        try:
            m, o = _on_e0(price, series(t, 'p_fcf', basis)) if price else (None, None)
        except ValueError:
            m, o = None, None
        e, o, n = _set('p_fcf', m, o, data)
        by[basis] = dict(exit_multiple=e, multiple_on=o, multiple_note=n, available=m is not None)
    basis = 'fcf_sbc' if after and by['fcf_sbc']['available'] else ('fcf' if by['fcf']['available'] else ('fcf_sbc' if by['fcf_sbc']['available'] else 'fcf'))
    out['p_fcf'] = dict(basis=basis, by_basis=by, growth=gf, growth_note=gfnote, growth_source=srcf, fade_to=fade(gf), share_change=0.0, growth_spread=3.0, multiple_spread=10.0, **by[basis])
    # --- EV/EBITDA -------------------------------------------------------------------------------------------------------
    ge, srce = _pick(refs, ('rev_e1', 'rev_e0', 'rev_last'))
    ge, genote = _cap_growth(ge)
    margin, msrc = t.get('margin_default'), None
    if margin is not None:
        msrc = 'ttm' if (t['rows'].get('ebitda_margin') or {}).get('TTM') else 'last_annual'
    b = data.get('market_baseline') or {}
    cm = data.get('current_multiples') or {}
    rev0 = (t['rows'].get('revenue') or {}).get('E0')
    ev_now = num(b.get('enterprise_value'))
    if ev_now and ev_now > 0 and rev0 and margin and margin > 0:
        m, o = ev_now / (rev0['value'] * margin), 'E0'
    else:
        m, o = num(cm.get('enterprise_to_ebitda')), 'TTM'
    em2, o, n = _set('ev_ebitda', m, o, data)
    out['ev_ebitda'] = dict(growth=ge, growth_note=genote, growth_source=srce, fade_to=fade(ge), margin=r1(pct_or_none(margin)), margin_source=msrc, exit_multiple=em2, multiple_on=o,
                            multiple_note=n, growth_spread=2.0, margin_spread=1.0, multiple_spread=10.0)
    return out
