"""SYNTHETIC rules only. No actual road permissions."""
import datetime as dt
import unittest
from scripts.stage5.temporal import parse_conditional as parse, evaluate_conditional as evaluate, ZONE

class TemporalResearch(unittest.TestCase):
    def check(self, raw, time, expected):
        self.assertEqual(evaluate(parse(raw), dt.datetime.fromisoformat(time))['active'], expected)
    def test_start_inclusive(self): self.check('no @ (Mo-Fr 08:00-10:00)', '2026-10-12T08:00:00+03:00', True)
    def test_end_exclusive(self): self.check('no @ (Mo-Fr 08:00-10:00)', '2026-10-12T10:00:00+03:00', False)
    def test_second_before_end(self): self.check('no @ (08:00-10:00)', '2026-10-12T09:59:59+03:00', True)
    def test_midnight_start_day(self): self.check('no @ (Fr 22:00-02:00)', '2026-10-17T01:00:00+03:00', True)
    def test_midnight_wrong_day(self): self.check('no @ (Fr 22:00-02:00)', '2026-10-16T01:00:00+03:00', False)
    def test_day_range_wrap(self): self.check('no @ (Fr-Mo 00:00-24:00)', '2026-10-18T11:00:00+03:00', True)
    def test_utc_conversion(self): self.check('no @ (08:00-10:00)', '2026-10-12T05:00:00+00:00', True)
    def test_naive_unknown(self): self.assertIsNone(evaluate(parse('no @ (08:00-10:00)'), dt.datetime(2026,1,1))['active'])
    def test_fallback_unknown(self):
        for offset in ('+03:00','+02:00'): self.check('no @ (00:00-03:00)', '2026-10-25T01:30:00'+offset, None)
    def test_spring_gap_unknown(self):
        d = dt.datetime(2026,3,27,2,30,tzinfo=ZONE)
        self.assertIsNone(evaluate(parse('no @ (00:00-04:00)'), d)['active'])
    def test_holidays_unknown(self): self.assertEqual(parse('no @ (PH 08:00-10:00)')['parse_status'],'UNKNOWN')
    def test_multiple_rules_unknown(self): self.assertEqual(parse('no @ (08:00-10:00); yes @ (12:00-14:00)')['parse_status'],'UNKNOWN')
    def test_invalid_equal_times(self):
        for x in ('24:01-25:00','10:00-10:00','26:00-10:00'):
            self.assertEqual(parse('no @ ('+x+')')['parse_status'],'UNKNOWN')
    def test_provenance_quarantine(self):
        r=parse('no @ (08:00-10:00)', {'synthetic':True})
        self.assertEqual(r['status'],'QUARANTINE'); self.assertFalse(r['navigation_eligible']); self.assertEqual(r['source'],{'synthetic':True})
