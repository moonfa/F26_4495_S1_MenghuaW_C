"""Dates, one-off flags, defaults and the extreme-multiple rule (valuation-v4), on offline company fixtures."""
import unittest

from app.core.valuation_context import consensus_period_end, earnings_quality_flags, to_date, meaningful
from app.core.valuation import Assumptions, calculate
from tests.fixtures_val import company


def pe(**kw):
    base = dict(exit_fy='2029-12-31', required_return=.1, growth=.114, exit_pe=20, growth_spread=.03, pe_spread=.1)
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

    def test_defaults_start_from_the_analysts_and_this_years_multiple(self):
        d = company(price=50.0)
        q = d['defaults']['pe']
        self.assertAlmostEqual(q['growth'], (2.5 / 2.2 - 1) * 100, places=1)       # growth the analyst numbers end on
        self.assertEqual(q['growth_source'], 'eps_e1'); self.assertEqual(q['multiple_on'], 'E0')
        self.assertAlmostEqual(q['exit_pe'], 50 / 2.2, places=1)                  # price ÷ this year's analyst EPS
        self.assertEqual(q['fade_to'], 5.0)

    def test_no_analysts_falls_back_to_the_trailing_figure(self):
        d = company(est=None)
        q = d['defaults']['pe']
        self.assertEqual(q['multiple_on'], 'TTM'); self.assertAlmostEqual(q['exit_pe'], 44 / 2.1, places=1)
        self.assertEqual(q['growth_source'], 'eps_last')

    def test_holding_a_same_basis_multiple_adds_nothing_when_the_exit_is_an_analyst_year(self):
        """Hold today's multiple on this year's figure and exit in the next analyst year: the return is the analysts' growth, no more."""
        d = company()
        e0, e1 = 2.2, 2.5
        r = calculate(d, pe(exit_fy='2027-12-31', exit_pe=44 / e0, pe_spread=0.0, growth_spread=0.0))
        base = r['scenarios'][1]
        self.assertEqual(r['user_years'], 0)
        self.assertAlmostEqual(base['future_price'], 44 / e0 * e1)
        self.assertTrue(any('analyst year' in c['text'] for c in r['checks']))

    def test_exit_date_and_fractional_years(self):
        d = company()
        r = calculate(d, pe())
        self.assertEqual(r['exit_date'], '2029-12-31'); self.assertEqual(r['exit_fy'], 'FY2029')
        self.assertAlmostEqual(r['years'], (to_date('2029-12-31') - to_date('2026-10-11')).days / 365.25)
        self.assertNotEqual(r['years'], round(r['years']))

    def test_extreme_today_multiple_is_not_prefilled(self):
        """INTC-type case: a tiny base gives a P/E far above any sensible exit multiple. It must not become the default."""
        d = company(price=40.0, est=(.03, .04, 1100e6, 1210e6), ttm_eps=.03)
        q = d['defaults']['pe']
        self.assertIsNone(q['exit_pe']); self.assertIn('too large', q['multiple_note'])
        self.assertTrue(meaningful('p_fcf', 40) and not meaningful('p_fcf', 1230.89) and not meaningful('ev_ebitda', 0))

    def test_checks_warn(self):
        r = calculate(company(), pe(exit_pe=60))
        self.assertTrue(any(c['level'] == 'warn' and 'multiple expansion' in c['text'] for c in r['checks']))
        r = calculate(company(), pe(growth=.4))
        self.assertTrue(any('analysts' in c['text'] and c['level'] == 'warn' for c in r['checks']))

    def test_old_data_warns(self):
        d = company(valuation='2027-10-11', next_fy='2027-12-31')
        r = calculate(d, pe(exit_fy='2030-12-31'))
        self.assertTrue(any(c['level'] == 'warn' and 'months ago' in c['text'] for c in r['checks']))


if __name__ == '__main__':
    unittest.main()
