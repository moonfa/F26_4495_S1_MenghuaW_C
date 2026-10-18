"""Valuation summary for the company page: pure logic, built from the same offline DEO fixture."""
import unittest
from datetime import datetime, timezone
from app.core.valuation import Assumptions, calculate
from app.core.valuation_link import summarize, at_price, stale_reasons, DRIVERS
from tests.test_valuation_turnaround import raw

NOW = datetime(2026, 10, 13, tzinfo=timezone.utc)


def analysis(d, saved='2026-10-11T00:00:00+00:00', **kw):
    base = dict(method='pe', anchor_id='consensus:+1y', years=3, required_return=.10, growth=.07, fade_to=.05, exit_pe=12.06, growth_spread=.03, pe_spread=.1, acknowledge_basis=True)
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
        self.assertAlmostEqual(x['base'], (fp / 70.0) ** (1 / 3) - 1)
        self.assertAlmostEqual(x['max_entry'], fp / 1.1 ** 3)
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
        later = datetime(2027, 3, 1, tzinfo=timezone.utc)
        row = summarize(self.rec, [self.a], 86.73, [], [], {}, None, later)['analyses'][0]
        self.assertEqual([s['kind'] for s in row['stale']], ['data'])

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


if __name__ == '__main__':
    unittest.main()
