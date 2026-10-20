"""Currency conversion for companies that quote in one currency and report in another (0883.HK: HKD price, CNY accounts).

The valuation arithmetic needs the price and the starting value in the same currency. Rather than refuse such companies,
the reported figures are converted to the quote currency at one spot rate, and that rate is held constant to the exit date.
That is an assumption, and every converted figure says so. Pure functions; the rate itself is fetched in the adapter.
"""
MINOR = {'GBp': ('GBP', 100), 'GBX': ('GBP', 100), 'ZAc': ('ZAR', 100), 'ZAC': ('ZAR', 100), 'ILA': ('ILS', 100)}
EPS_KEYS = ('avg', 'low', 'high', 'yearAgoEps', 'yearAgoRevenue')


def split(code):
    """'GBp' -> ('GBP', 100): the major currency and how many quote units make one of it."""
    return MINOR.get(code, (code, 1))


def plan(fin, quote, lookup):
    """How to turn `fin`-currency figures into `quote`-currency ones.
    lookup(from_major, to_major) -> dict(rate, observed, pair) or None. Returns a dict:
      applied False + reason   (nothing to do, or no rate available)
      applied True + rate, from, to, observed, pair, text."""
    if not fin or not quote:
        return dict(applied=False, needed=False, reason='currency unknown')
    if fin == quote:
        return dict(applied=False, needed=False)
    f_major, f_div = split(fin)
    q_major, q_div = split(quote)
    if f_major == q_major:                      # pence vs pounds: a fixed factor, no market rate needed
        rate, observed, pair = q_div / f_div, None, None
    else:
        got = lookup(f_major, q_major)
        if not got or not got.get('rate') or got['rate'] <= 0:
            return dict(applied=False, needed=True, reason=f'no exchange rate {f_major}→{q_major} could be fetched')
        rate = got['rate'] * q_div / f_div
        observed, pair = got.get('observed'), got.get('pair')
    when = f' (spot, {observed})' if observed else ''
    return dict(applied=True, needed=True, rate=rate, **{'from': fin, 'to': quote}, observed=observed, pair=pair,
                text=f'Reported in {fin}, converted at 1 {fin} = {rate:.4f} {quote}{when}; the rate is held constant to the exit date.')


def conv_rows(rows, rate, keys):
    for r in rows or []:
        for k in keys:
            if isinstance(r.get(k), (int, float)) and not isinstance(r.get(k), bool):
                r[k] = r[k] * rate


def conv_estimates(estimates, p):
    """Consensus rows reported in the financial currency -> quote currency, in place. Keeps the original average."""
    for x in estimates or []:
        if x.get('currency') != p['from']:
            continue
        x['avg_original'] = x.get('avg')
        conv_rows([x], p['rate'], EPS_KEYS)
        x['currency'] = p['to']
        x['fx_from'] = p['from']
