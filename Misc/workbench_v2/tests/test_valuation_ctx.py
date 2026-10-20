import unittest
from app.core.valuation_context import consensus_period_end, earnings_quality_flags, status_quo, to_date
from app.core.valuation import Assumptions, EbitdaAssumptions, calculate


def data():
    return dict(retrieved_at='2026-10-11T00:00:00+00:00', quote=dict(value=111.35, currency='USD'),
                anchors=[dict(id='ttm', value=2.9, currency='USD', period_end='2026-09-21'),
                         dict(id='annual:2026-01-31', value=2.73, currency='USD', period_end='2026-01-31')],
                estimates=[dict(metric='eps', period='0y', avg=2.89), dict(metric='eps', period='+1y', avg=3.22)],
                historical=[], current_multiples=dict(forward_pe=34.5, trailing_eps=2.9))


def pe(anchor, **kw):
    base = dict(anchor_id=anchor, years=3, required_return=.1, growth=.114, exit_pe=34.5, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
    return Assumptions(**{**base, **kw})


class Ctx(unittest.TestCase):
    def test_period_end(self):
        self.assertEqual(consensus_period_end({'nextFiscalYearEnd': 1801440000}, '0y'), '2027-02-01')
        self.assertEqual(consensus_period_end({'nextFiscalYearEnd': 1801440000}, '+1y'), '2028-02-01')
        self.assertIsNone(consensus_period_end({}, '0y'))
        self.assertIsNone(to_date('bad'))

    def test_one_off_flag(self):
        rows = [dict(period_end=f'202{y}-12-31', revenue=100, net_income=n) for y, n in ((6, 40), (5, 10), (4, 9), (3, 10))]
        self.assertEqual(len(earnings_quality_flags(rows)), 1)
        rows[0]['net_income'] = 10
        self.assertEqual(earnings_quality_flags(rows), [])

    def test_status_quo(self):
        d = data(); d['historical'] = []
        q = status_quo(d)
        self.assertEqual(q['pe']['growth'], 11.4)
        self.assertEqual(q['pe']['anchor_id'], 'ttm'); self.assertAlmostEqual(q['pe']['exit_pe'], 111.35 / 2.9, 1)   # price ÷ the same starting value

    def test_growth_counted_for_the_holding_period_only(self):
        a = calculate(data(), pe('annual:2026-01-31')); t = calculate(data(), pe('ttm'))
        self.assertEqual(a['growth_years'], 3); self.assertEqual(t['growth_years'], 3)

    def test_same_basis_multiple_adds_nothing(self):
        """Hold today's multiple on the starting value and grow at g: the annual return is g for every starting point."""
        d = data(); d['anchors'].append(dict(id='consensus:+1y', value=3.22, currency='USD', period_end='2028-02-01', category='market_consensus'))
        for anchor, value in (('ttm', 2.9), ('annual:2026-01-31', 2.73), ('consensus:+1y', 3.22)):
            r = calculate(d, pe(anchor, growth=.08, exit_pe=111.35 / value, growth_spread=0.0, pe_spread=0.0))
            base = r['scenarios'][1]
            self.assertAlmostEqual(base['price_cagr'], .08, places=9)
            self.assertAlmostEqual(base['earnings_effect'], .08, places=9); self.assertAlmostEqual(base['multiple_effect'], 0, places=9)

    def test_stale_annual_anchor_warns(self):
        d = data(); d['retrieved_at'] = '2027-10-11T00:00:00+00:00'
        r = calculate(d, pe('annual:2026-01-31', exit_pe=111.35 / 2.73))
        self.assertTrue(any(c['level'] == 'warn' and 'months ago' in c['text'] for c in r['checks']))

    def test_growth_factor_fractional_tail(self):
        from app.core.valuation import growth_factor
        self.assertAlmostEqual(growth_factor(.2, .05, 1.01), 1.2 * 1.05 ** .01)
        self.assertAlmostEqual(growth_factor(.1, .1, 2.5), 1.1 ** 2.5)

    def test_status_quo_prefers_analyst_year(self):
        d = data(); d['anchors'] = [dict(id='ttm', value=3.12, currency='USD'), dict(id='consensus:0y', value=6.72, currency='USD'), dict(id='consensus:+1y', value=7.19, currency='USD')]
        d['quote']['value'] = 86.73
        q = status_quo(d)['pe']
        self.assertEqual(q['anchor_id'], 'consensus:+1y'); self.assertAlmostEqual(q['exit_pe'], 12.1, 1)
        self.assertAlmostEqual(q['multiple_by_anchor']['ttm'], 27.8, 1)

    def test_checks_warn(self):
        r = calculate(data(), pe('ttm', exit_pe=60))
        self.assertTrue(any(c['level'] == 'warn' and 'starting point' in c['text'] for c in r['checks']))
        r = calculate(data(), pe('ttm', growth=.4))
        self.assertTrue(any('analyst' in c['text'] for c in r['checks']))


if __name__ == '__main__':
    unittest.main()
