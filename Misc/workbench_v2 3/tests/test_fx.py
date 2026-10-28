"""Quote in one currency, accounts in another (HKD price, CNY accounts), run offline through the real enrichment."""
import unittest
from datetime import datetime, timezone
from app.core import fx as F
from app.adapters.valuation_references import enrich
from app.core.valuation import Assumptions, calculate


def ts(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


RATE = 1.0868


def lookup(a, b):
    return dict(rate=RATE, observed='2026-10-16', pair=f'{a}{b}=X') if (a, b) == ('CNY', 'HKD') else None


def company(fx, trailing_eps=3.23):
    price = 23.96
    hist = [('2025-12-31', 2.9), ('2024-12-31', 3.2)]            # CNY per share
    d = dict(ticker='0883.HK', retrieved_at='2026-10-16T00:00:00+00:00', quote=dict(value=price, currency='HKD'), warnings=[], raw={}, methods={},
             anchors=[dict(id=f'annual:{e}', value=v, category='historical_reported', currency='CNY', period_end=e, basis='x') for e, v in hist],
             historical=[dict(period_end=e, diluted_eps=v, currency='CNY', revenue=4e11, net_income=v * 4.7e10, ebitda=2e11, ebitda_margin=.5, source='x') for e, v in hist],
             estimates=[dict(metric='eps', period='0y', avg=2.7, currency='CNY', source='x'), dict(metric='eps', period='+1y', avg=2.45, currency='CNY', source='x'),
                        dict(metric='revenue', period='0y', avg=4.0e11, currency='CNY', source='x'), dict(metric='revenue', period='+1y', avg=3.9e11, currency='CNY', source='x')],
             cashflow=[], cashflow_ttm=dict(period_end='2026-06-30', ocf=2.2e11, capex=-9e10, fcf=1.28e11, sbc=None), fx=fx)
    info = dict(trailingPE=price / trailing_eps, forwardPE=6.66, trailingEps=trailing_eps, forwardEps=3.6, enterpriseToEbitda=3.3, financialCurrency='CNY', currency='HKD',
                nextFiscalYearEnd=ts(2026, 12, 31), mostRecentQuarter=ts(2026, 6, 30), marketCap=price * 4.75e10, sharesOutstanding=4.75e10,
                totalDebt=1.0e11, totalCash=1.5e11, ebitda=2e11, enterpriseValue=price * 4.75e10 - 5e10 * RATE, totalRevenue=3.9e11, sector='Energy', industry='Oil & Gas E&P')
    return enrich(d, None, info, ())


class Plan(unittest.TestCase):
    def test_same_currency_needs_nothing(self):
        self.assertFalse(F.plan('USD', 'USD', lookup)['needed'])

    def test_rate_is_applied(self):
        p = F.plan('CNY', 'HKD', lookup)
        self.assertTrue(p['applied']); self.assertAlmostEqual(p['rate'], RATE); self.assertIn('1 CNY = 1.0868 HKD', p['text'])

    def test_missing_rate_is_reported_not_guessed(self):
        p = F.plan('CNY', 'EUR', lookup)
        self.assertFalse(p['applied']); self.assertTrue(p['needed']); self.assertIn('CNY→EUR', p['reason'])

    def test_pence_is_a_fixed_factor(self):
        p = F.plan('GBP', 'GBp', lambda a, b: None)
        self.assertTrue(p['applied']); self.assertEqual(p['rate'], 100)
        p = F.plan('USD', 'GBp', lambda a, b: dict(rate=.8, observed='x', pair='USDGBP=X'))
        self.assertAlmostEqual(p['rate'], 80)


class Converted(unittest.TestCase):
    def setUp(self):
        self.d = company(F.plan('CNY', 'HKD', lookup))

    def test_everything_is_in_the_quote_currency(self):
        for a in self.d['anchors'] + self.d['fcf_anchors'] + self.d['revenue_anchors']:
            self.assertEqual(a['currency'], 'HKD', a['id'])
        self.assertAlmostEqual(next(a for a in self.d['anchors'] if a['id'] == 'annual:2025-12-31')['value'], 2.9 * RATE)
        self.assertAlmostEqual(next(a for a in self.d['anchors'] if a['id'] == 'consensus:0y')['value'], 2.7 * RATE)
        self.assertEqual(self.d['market_baseline']['currency'], 'HKD')

    def test_provider_eps_that_already_matches_its_pe_is_not_converted_twice(self):
        self.assertAlmostEqual(next(a for a in self.d['anchors'] if a['id'] == 'ttm')['value'], 3.23)
        d2 = company(F.plan('CNY', 'HKD', lookup), trailing_eps=3.23)
        self.assertAlmostEqual(d2['current_multiples']['trailing_eps'], 3.23)

    def test_fcf_multiple_uses_matching_currencies(self):
        per_share = 1.28e11 / 4.75e10 * RATE
        self.assertAlmostEqual(self.d['current_multiples']['price_to_fcf'], 23.96 / per_share, places=2)

    def test_calculation_runs_and_says_so(self):
        a = Assumptions(anchor_id='consensus:0y', years=3, required_return=.1, growth=-.05, fade_to=.0, exit_pe=7.0, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
        r = calculate(self.d, a)
        self.assertEqual(r['currency'], 'HKD')
        self.assertTrue(any('exchange rate' in x for x in r['limitations']))

    def test_without_a_rate_the_error_says_what_to_do(self):
        d = company(F.plan('CNY', 'EUR', lookup))
        a = Assumptions(anchor_id='consensus:0y', years=3, required_return=.1, growth=0, exit_pe=7.0, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
        with self.assertRaises(ValueError) as e:
            calculate(d, a)
        self.assertIn('Import the data again', str(e.exception))


if __name__ == '__main__':
    unittest.main()
