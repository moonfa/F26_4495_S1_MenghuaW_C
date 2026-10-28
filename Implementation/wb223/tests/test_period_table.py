"""The period table: one table of fiscal periods that every valuation number is read from."""
import unittest
from datetime import date

from app.core.period_table import (build_period_table, series, exit_choice, nearest_exit, steps_between, estimates_used, fy_label)
from tests.fixtures_val import company


class DecemberYear(unittest.TestCase):
    def setUp(self):
        self.d = company()
        self.t = self.d['period_table']

    def test_columns_in_time_order_with_labels(self):
        self.assertEqual([(c['key'], c['label'], c['kind']) for c in self.t['columns']],
                         [('A-3', 'FY2022', 'actual'), ('A-2', 'FY2023', 'actual'), ('A-1', 'FY2024', 'actual'), ('A0', 'FY2025', 'actual'),
                          ('TTM', 'TTM', 'ttm'), ('E0', 'FY2026', 'analyst'), ('E1', 'FY2027', 'analyst')])
        self.assertEqual(self.t['analyst_through'], '2027-12-31')

    def test_cells_say_what_they_are(self):
        eps = self.t['rows']['eps']
        self.assertEqual(eps['A0']['kind'], 'actual'); self.assertEqual(eps['TTM']['kind'], 'ttm')
        e0 = eps['E0']
        self.assertEqual((e0['kind'], e0['value'], e0['n'], e0['period_end']), ('analyst', 2.2, 10, '2026-12-31'))
        self.assertAlmostEqual(e0['low'], 2.09); self.assertAlmostEqual(e0['high'], 2.31)
        self.assertFalse(e0['derived']); self.assertTrue(self.t['rows']['fcf_per_share']['E0']['derived'])
        self.assertEqual(e0['currency'], 'USD')

    def test_growth_is_against_the_previous_fiscal_year_not_ttm(self):
        eps = self.t['rows']['eps']
        self.assertAlmostEqual(eps['A0']['growth'], 2.0 / 1.8 - 1)
        self.assertAlmostEqual(eps['E0']['growth'], 2.2 / 2.0 - 1)       # TTM 2.1 is skipped
        self.assertAlmostEqual(eps['E1']['growth'], 2.5 / 2.2 - 1)
        self.assertNotIn('growth', eps['TTM']); self.assertNotIn('growth', eps['A-3'])

    def test_free_cash_flow_for_analyst_years_is_derived_from_revenue(self):
        r, f = self.t['rows']['revenue'], self.t['rows']['fcf_per_share']
        self.assertEqual(self.t['fcf_base']['which'], 'TTM')           # both positive: the newer margin is used
        self.assertAlmostEqual(f['E0']['value'], f['TTM']['value'] * r['E0']['value'] / r['TTM']['value'])
        self.assertAlmostEqual(f['E1']['value'], f['TTM']['value'] * r['E1']['value'] / r['TTM']['value'])
        self.assertEqual(f['E1']['kind'], 'derived')
        self.assertIn('twelve months', f['E1']['source'])
        self.assertAlmostEqual(self.t['rows']['ebitda']['E0']['value'], r['E0']['value'] * self.t['margin_default'])

    def test_exit_options_are_fiscal_year_ends_at_least_half_a_year_away(self):
        opts = self.t['exit_options']
        self.assertEqual(opts[0]['fy'], 'FY2027')          # FY2026 ends in 0.2 years: too soon to be an exit
        self.assertEqual(opts[0]['period_end'], '2027-12-31')
        self.assertAlmostEqual(opts[0]['years'], (date(2027, 12, 31) - date(2026, 10, 11)).days / 365.25, places=2)
        self.assertNotEqual(opts[0]['years'], round(opts[0]['years']))      # not a whole number of years
        self.assertTrue(all(o['years'] <= 10.01 for o in opts))
        self.assertEqual(exit_choice(self.t, 'FY2029')['period_end'], '2029-12-31')
        self.assertEqual(exit_choice(self.t, '2029-12-31')['fy'], 'FY2029')
        with self.assertRaises(ValueError): exit_choice(self.t, '2029-06-30')

    def test_nearest_exit_to_three_years(self):
        self.assertEqual(nearest_exit(self.t, 3)['fy'], 'FY2029')
        self.assertEqual(nearest_exit(self.t, 1)['fy'], 'FY2027')
        self.assertEqual(nearest_exit(self.t, 10)['fy'], 'FY2035')

    def test_series_known_years_and_reference(self):
        s = series(self.t, 'pe')
        self.assertEqual([x['key'] for x in s['known']], ['E0', 'E1'])
        self.assertEqual(s['last']['value'], 2.5); self.assertEqual(s['ref']['kind'], 'ttm')
        self.assertEqual(steps_between(s['last']['period_end'], '2030-12-31'), 3)
        self.assertEqual(series(self.t, 'ev_ebitda')['last']['value'], 1210e6)
        self.assertAlmostEqual(series(self.t, 'p_fcf', 'fcf_sbc')['last']['value'], self.t['rows']['fcf_per_share_sbc']['TTM']['value'] * 1210 / 1050)

    def test_estimates_used_keeps_what_the_analysts_said(self):
        u = estimates_used(self.t)
        self.assertEqual(u['eps'], {'2026-12-31': 2.2, '2027-12-31': 2.5}); self.assertEqual(u['revenue']['2026-12-31'], 1100e6)
        self.assertEqual(u['last_actual_end'], '2025-12-31')


class JuneYear(unittest.TestCase):
    def test_non_calendar_fiscal_year(self):
        d = company(valuation='2026-10-11', last_fy='2026-06-30', next_fy='2027-06-30', mrq='2026-09-30', est=(2.2, 2.5, 1100e6, 1210e6))
        t = d['period_table']
        self.assertEqual(t['columns'][3]['label'], 'FY2026'); self.assertEqual(t['first_future_end'], '2027-06-30')
        self.assertEqual([o['fy'] for o in t['exit_options']][:2], ['FY2027', 'FY2028'])
        self.assertAlmostEqual(t['exit_options'][0]['years'], 0.72, places=2)
        self.assertEqual(nearest_exit(t, 3)['period_end'], '2029-06-30')    # a June year end, not an October anniversary


class NoAnalysts(unittest.TestCase):
    def test_years_are_the_users_own_from_the_last_reported_year(self):
        d = company(est=None)
        t = d['period_table']
        self.assertEqual([c['kind'] for c in t['columns']], ['actual'] * 4 + ['ttm'])
        self.assertEqual(t['first_future_end'], '2026-12-31')                # last year end + 1, still ahead of the valuation date
        s = series(t, 'pe')
        self.assertEqual(s['known'], []); self.assertEqual(s['last']['key'], 'A0')
        self.assertEqual(steps_between(s['last']['period_end'], '2029-12-31'), 4)

    def test_stale_data_rolls_the_year_forward(self):
        d = company(est=None, valuation='2027-03-01')
        self.assertEqual(d['period_table']['first_future_end'], '2027-12-31')   # 2026-12-31 has passed without a reported year


class LossMaking(unittest.TestCase):
    def test_negative_eps_cannot_be_projected(self):
        d = company(eps=(-1.0, -0.8, -0.5, -0.2), est=None, ttm_eps=-0.1)
        with self.assertRaises(ValueError) as cm: series(d['period_table'], 'pe')
        self.assertIn('earnings per share', str(cm.exception))
        self.assertIsNone(d['period_table']['rows']['eps']['A0'].get('growth'))     # growth of a negative base is not a number

    def test_positive_estimates_after_losses_are_projected_from_the_analyst_years(self):
        d = company(eps=(-1.0, -0.8, -0.5, -0.2), est=(0.4, 0.9, 1100e6, 1210e6), ttm_eps=-0.1)
        s = series(d['period_table'], 'pe')
        self.assertEqual(s['last']['value'], 0.9)
        self.assertIsNone(s['ref'])                                               # TTM is negative: no trailing multiple


class OtherCurrency(unittest.TestCase):
    def test_converted_figures_carry_the_quote_currency(self):
        fx = dict(applied=True, needed=True, rate=1.1, text='converted', **{'from': 'CNY', 'to': 'HKD'})
        d = company(currency='HKD', fin_currency='CNY', fx=fx)
        t = d['period_table']
        self.assertEqual(t['rows']['eps']['A0']['currency'], 'HKD')
        self.assertAlmostEqual(t['rows']['eps']['A0']['value'], 2.0 * 1.1)
        self.assertAlmostEqual(t['rows']['eps']['E0']['value'], 2.2 * 1.1)
        self.assertEqual(t['currency'], 'HKD')


class Lazy(unittest.TestCase):
    def test_table_is_built_when_a_record_has_none(self):
        d = company(); built = d.pop('period_table')
        from app.core.period_table import table_of
        self.assertEqual(table_of(d)['exit_options'], built['exit_options'])


if __name__ == '__main__':
    unittest.main()
