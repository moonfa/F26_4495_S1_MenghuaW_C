"""Valuation summary for the company page: pure logic, built from the same offline DEO fixture."""
import unittest
from datetime import datetime, timezone
from app.core.valuation import Assumptions, calculate
from app.core.valuation_link import summarize, at_price, stale_reasons, estimate_changes, estimate_text, DRIVERS
from tests.fixtures_val import company
from tests.test_valuation_turnaround import raw

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def analysis(d, saved='2026-10-11T00:00:00+00:00', **kw):
    base = dict(method='pe', exit_fy='2029-06-30', required_return=.10, growth=.07, fade_to=.05, exit_pe=12.06, growth_spread=.03, pe_spread=.1)
    res = calculate(d, Assumptions(**{**base, **kw}))
    return dict(id='an1', created_at=saved, payload=dict(data_id='d1', result=res), data_price=d['quote']['value'], data_fetched=d['retrieved_at'])


class Link(unittest.TestCase):
    def setUp(self):
        self.d = raw()
        self.rec = dict(id='d1', payload=self.d)
        self.a = analysis(self.d)

    def test_no_data_means_not_available(self):
        out = summarize(None, [], 86.73, [], [], {}, None, NOW)
        self.assertFalse(out['available'])

    def test_entry_price_arithmetic(self):
        res = self.a['payload']['result']
        fp = next(s for s in res['scenarios'] if s['scenario'] == 'Base')['future_price']
        x = at_price(res, 70.0)
        y = res['years']
        self.assertAlmostEqual(x['base'], (fp / 70.0) ** (1 / y) - 1)
        self.assertAlmostEqual(x['max_entry'], fp / 1.1 ** y)
        self.assertGreater(x['base'], at_price(res, 86.73)['base'])            # paying less returns more

    def test_plan_buy_below_and_target(self):
        out = summarize(self.rec, [self.a], 86.73, [], [], {}, dict(buy_below=75.0, target_price=120.0), NOW)
        row = out['analyses'][0]
        self.assertIn('at_buy_below', row); self.assertGreater(row['at_buy_below']['base'], row['now']['base'])
        self.assertIsNotNone(row['target_vs_base'])
        self.assertEqual(out['plan']['buy_below'], 75.0)

    def test_latest_analysis_per_method_only(self):
        older = analysis(self.d, saved='2026-10-01T00:00:00+00:00', growth=.02)
        out = summarize(self.rec, [self.a, older], 86.73, [], [], {}, None, NOW)
        self.assertEqual(len(out['analyses']), 1); self.assertEqual(out['analyses'][0]['analysis_id'], 'an1')

    def test_status_quo_and_dislocation_come_along(self):
        out = summarize(self.rec, [], 86.73, [], [], {}, None, NOW)
        self.assertEqual(out['dislocation']['kind'], 'recovery')
        self.assertTrue(out['status_quo']['methods'])
        self.assertIn('recovers', out['question'])

    def test_stale_when_thesis_materially_changed_after_save(self):
        reviews = [dict(created_at='2026-10-12T00:00:00+00:00', kind='update', level='material'), dict(created_at='2026-10-12T05:00:00+00:00', kind='check', level='material')]
        row = summarize(self.rec, [self.a], 86.73, reviews, [], {}, None, NOW)['analyses'][0]
        self.assertEqual([s['kind'] for s in row['stale']], ['thesis'])
        quiet = summarize(self.rec, [self.a], 86.73, [dict(created_at='2026-10-12T00:00:00+00:00', kind='update', level='minor')], [], {}, None, NOW)
        self.assertEqual(quiet['analyses'][0]['stale'], [])
        before = [dict(created_at='2026-10-01T00:00:00+00:00', kind='update', level='material')]
        self.assertEqual(summarize(self.rec, [self.a], 86.73, before, [], {}, None, NOW)['analyses'][0]['stale'], [])

    def test_stale_on_price_move_and_old_data(self):
        row = summarize(self.rec, [self.a], 60.0, [], [], {}, None, NOW)['analyses'][0]
        self.assertEqual([s['kind'] for s in row['stale']], ['price'])
        later = datetime(2027, 3, 1, tzinfo=timezone.utc)   # more than 100 days after the import
        row = summarize(self.rec, [self.a], 86.73, [], [], {}, None, later)['analyses'][0]
        self.assertIn('data', [s['kind'] for s in row['stale']])

    def test_weak_assumption_tied_to_a_driver_flags_the_method(self):
        ass = [dict(id='a1', statement='Volumes recover', status='weakened'), dict(id='a2', statement='Pricing holds', status='holding')]
        out = summarize(self.rec, [self.a], 86.73, [], ass, dict(a1='eps_growth', a2='multiple'), None, NOW)
        st = out['analyses'][0]['stale']
        self.assertEqual([s['kind'] for s in st], ['assumption']); self.assertIn('a1', st[0]['text'])
        eps = next(x for x in out['drivers'] if x['key'] == 'eps_growth')
        self.assertEqual(eps['assumptions'][0]['id'], 'a1')
        # a link to a driver the method does not use does not flag it
        out = summarize(self.rec, [self.a], 86.73, [], ass, dict(a1='balance'), None, NOW)
        self.assertEqual(out['analyses'][0]['stale'], [])

    def test_driver_keys_are_the_ones_methods_use(self):
        from app.core.valuation_link import METHOD_DRIVERS
        for ds in METHOD_DRIVERS.values():
            for k in ds:
                self.assertIn(k, DRIVERS)


class EstimateRevisions(unittest.TestCase):
    """Analysts change their forecasts. A saved analysis keeps the numbers it used; a later import only adds a notice."""
    def setUp(self):
        self.old = company()
        res = calculate(self.old, Assumptions(exit_fy='2029-12-31', required_return=.1, growth=.1, exit_pe=20, growth_spread=.03, pe_spread=.1))
        self.res = res
        self.rec = dict(id='an1', created_at='2026-10-11T00:00:00+00:00', payload=dict(data_id='d1', result=res), data_price=44.0, data_fetched=self.old['retrieved_at'])
        self.now = datetime(2026, 10, 20, tzinfo=timezone.utc)

    def test_the_estimates_used_are_stored_with_the_analysis(self):
        u = self.res['estimates_used']
        self.assertAlmostEqual(u['eps']['2026-12-31'], 2.2); self.assertAlmostEqual(u['eps']['2027-12-31'], 2.5)
        self.assertAlmostEqual(u['revenue']['2027-12-31'], 1210e6); self.assertEqual(u['last_actual_end'], '2025-12-31')

    def _summary(self, new):
        return summarize(dict(id='d2', payload=new), [self.rec], 44.0, [], [], {}, None, self.now)['analyses'][0]['stale']

    def test_unchanged_estimates_add_nothing(self):
        self.assertEqual([s for s in self._summary(company(valuation='2026-10-19')) if s['kind'] in ('estimates', 'fy')], [])

    def test_a_small_move_is_below_the_threshold(self):
        small = company(valuation='2026-10-19', est=(2.2 * 1.02, 2.5 * 1.02, 1100e6 * 1.01, 1210e6 * 1.01))
        self.assertEqual([s for s in self._summary(small) if s['kind'] == 'estimates'], [])

    def test_a_larger_move_gives_one_factual_line_and_leaves_the_saved_result_alone(self):
        cut = company(valuation='2026-10-19', est=(2.2 * .9, 2.5 * .9, 1100e6, 1210e6))
        before = self.res['scenarios'][1]['future_price']
        st = [s for s in self._summary(cut) if s['kind'] == 'estimates']
        self.assertEqual(len(st), 1)
        self.assertIn('analyst EPS for FY2027 moved from 2.50 to 2.25', st[0]['text']); self.assertIn('-10.0%', st[0]['text']); self.assertIn('was not changed', st[0]['text'])
        self.assertNotIn('revenue', st[0]['text'])
        self.assertEqual(self.res['scenarios'][1]['future_price'], before)

    def test_revenue_has_its_own_threshold(self):
        cut = company(valuation='2026-10-19', est=(2.2, 2.5, 1100e6 * .95, 1210e6 * .95))
        txt = [s['text'] for s in self._summary(cut) if s['kind'] == 'estimates'][0]
        self.assertIn('analyst revenue for FY2026', txt); self.assertNotIn('EPS', txt)

    def test_a_year_that_has_since_been_reported_is_called_out(self):
        later = company(valuation='2027-02-20', last_fy='2026-12-31', next_fy='2027-12-31', mrq='2026-12-31', eps=(1.6, 1.8, 2.0, 2.3),
                        revenue=(810e6, 900e6, 1000e6, 1090e6), ebitda=(200e6, 225e6, 250e6, 270e6), net_income=(80e6, 90e6, 100e6, 110e6),
                        ocf=(120e6, 135e6, 150e6, 160e6), est=(2.5, 2.8, 1210e6, 1330e6))
        kinds = [s['kind'] for s in self._summary(later)]
        self.assertIn('fy', kinds)
        changes = estimate_changes(self.res['estimates_used'], later['period_table'])
        fy26 = next(c for c in changes if c['metric'] == 'eps' and c['fy'] == 'FY2026')
        self.assertTrue(fy26['reported']); self.assertIn('now reported', estimate_text(changes))


if __name__ == '__main__':
    unittest.main()
