from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from apps.compass.backend_model import Budget, Config, DeepSeek, ModelError, strict_json

SCHEMA = {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['unknown']}},
          'required': ['status'], 'additionalProperties': False}


def envelope(content='{"status":"unknown"}', **overrides):
    obj = {'model': 'test-version', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}],
           'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}}
    obj.update(overrides)
    return json.dumps(obj).encode()


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'budget.sqlite3'
        self.budget = Budget(self.path)
        self.env = patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'secret-for-test'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def adapter(self, raw=None, status=200, **config):
        return DeepSeek(Config(model='test-model', **config), self.budget,
                        transport=lambda *args: (status, envelope() if raw is None else raw))

    def call(self, adapter, **kwargs):
        return adapter.generate({'fictional': True}, SCHEMA, synthetic=True, **kwargs)

    def error(self, code, adapter, **kwargs):
        with self.assertRaises(ModelError) as ctx:
            self.call(adapter, **kwargs)
        self.assertEqual(ctx.exception.code, code)
        self.assertNotIn('secret-for-test', str(ctx.exception))

    def test_success_and_provenance(self):
        result = self.call(self.adapter())
        self.assertEqual(result['value'], {'status': 'unknown'})
        self.assertTrue(result['metadata']['test_double'])
        self.assertEqual(result['metadata']['cost_ceiling_micro_usd'], 35)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('select micro_usd,state from calls').fetchone(), (35, 'measured_ceiling'))
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_real_data_boundary(self):
        with self.assertRaisesRegex(ModelError, 'synthetic_only'):
            self.adapter().generate({}, SCHEMA)

    def test_missing_key(self):
        with patch.dict(os.environ, {}, clear=True):
            self.error('missing_credentials', self.adapter())

    def test_context_limit(self):
        self.error('context_limit', self.adapter(max_input_bytes=10))

    def test_call_cost(self):
        self.error('call_cost_limit', self.adapter(per_call_micro_usd=1))

    def test_budget_persists_across_instances(self):
        cfg = Config(model='test', total_micro_usd=3000)
        failing = DeepSeek(cfg, self.budget, transport=lambda *a: (503, b'private text'))
        self.error('unavailable', failing)
        again = DeepSeek(cfg, Budget(self.path), transport=lambda *a: (200, envelope()))
        self.error('budget_exceeded', again)

    def test_budget_atomic(self):
        results = []
        def run():
            try:
                results.append(self.budget.reserve(10, 10))
            except ModelError:
                results.append('denied')
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(results.count('denied'), 1)

    def test_http_failures_sanitized(self):
        for status, code in [(401, 'authentication_failed'), (402, 'provider_balance'),
                             (429, 'rate_limited'), (500, 'unavailable'), (302, 'unavailable')]:
            with self.subTest(status=status):
                self.error(code, self.adapter(status=status, raw=b'secret-for-test private clinical text'))

    def test_malformed_json(self):
        for raw in [b'{', b'{"x":1,"x":2}', b'NaN', b'\xff', b'[]', b'null']:
            with self.subTest(raw=raw):
                self.error('invalid_json' if raw not in (b'[]', b'null') else 'invalid_response', self.adapter(raw))

    def test_bad_structured_output(self):
        for value in ['{"status":"ready"}', '{}', '[]', '{"status":"unknown","x":1}']:
            self.error('invalid_response', self.adapter(envelope(value)))

    def test_refusal_truncation_tools(self):
        for choice in [{'finish_reason': 'length', 'message': {'content': '{}'}},
                       {'finish_reason': 'stop', 'message': {'content': '{}', 'refusal': 'no'}},
                       {'finish_reason': 'stop', 'message': {'content': '{}', 'tool_calls': [{}]}}]:
            self.error('incomplete_or_refused', self.adapter(envelope(choices=[choice])))

    def test_usage_validation(self):
        for usage in [{}, {'prompt_tokens': True, 'completion_tokens': 1, 'total_tokens': 2},
                      {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 1}]:
            self.error('invalid_response', self.adapter(envelope(usage=usage)))
        self.error('usage_limit', self.adapter(envelope(usage={
            'prompt_tokens': 10, 'completion_tokens': 2000, 'total_tokens': 2010})))

    def test_timeout_is_bounded(self):
        def slow(*args):
            time.sleep(.15)
            return 200, envelope()
        model = DeepSeek(Config(model='test', timeout=.02), self.budget, transport=slow)
        start = time.monotonic()
        self.error('timeout', model)
        self.assertLess(time.monotonic() - start, .12)

    def test_cancel_before_and_during(self):
        event = threading.Event()
        event.set()
        self.error('cancelled', self.adapter(), cancel=event)
        event.clear()
        def slow(*args):
            event.set()
            time.sleep(.1)
            return 200, envelope()
        self.error('cancelled', DeepSeek(Config(model='test'), self.budget, transport=slow), cancel=event)

    def test_response_bound(self):
        self.error('response_too_large', self.adapter(b'x' * 20, max_response_bytes=10))

    def test_transport_exception_sanitized(self):
        def broken(*args):
            raise RuntimeError('secret-for-test private clinical text')
        self.error('unavailable', DeepSeek(Config(model='test'), self.budget, transport=broken))

    def test_request_has_no_tools_or_real_record_access(self):
        observed = []
        def capture(body, key, timeout, limit):
            observed.append(json.loads(body))
            return 200, envelope()
        self.call(DeepSeek(Config(model='test'), self.budget, transport=capture))
        self.assertNotIn('tools', observed[0])
        self.assertFalse(observed[0]['stream'])
        self.assertEqual(observed[0]['response_format'], {'type': 'json_object'})

    def test_non_json_input(self):
        with self.assertRaisesRegex(ModelError, 'invalid_input'):
            self.adapter().generate({'bad': float('nan')}, SCHEMA, synthetic=True)

    def test_production_model_allowlist(self):
        self.error('unsupported_model', DeepSeek(Config(model='deepseek-v4-pro'), self.budget))

    def test_cache_usage(self):
        raw = envelope(usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                              'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 6})
        result = self.call(self.adapter(raw))
        self.assertEqual(result['metadata']['estimated_peak_cost_nano_usd'], 7824)
        raw = envelope(usage={'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
                              'prompt_cache_hit_tokens': 11})
        self.error('invalid_usage', self.adapter(raw))

    def test_timeout_reservation_retained(self):
        def timeout(*args):
            raise TimeoutError()
        self.error('timeout', DeepSeek(Config(model='test'), self.budget, transport=timeout))
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('select state from calls').fetchone()[0], 'reserved')

    def test_authorized_connection_cap_keeps_existing_ledger_and_fails_above_limit(self):
        cfg = Config(model='test')
        self.assertEqual(1000000, cfg.total_micro_usd)
        self.assertEqual(20000, cfg.per_call_micro_usd)
        self.budget.reserve(45150, cfg.total_micro_usd)
        self.budget.reserve(950000, cfg.total_micro_usd)
        with self.assertRaisesRegex(ModelError, 'budget_exceeded'):
            self.budget.reserve(4851, cfg.total_micro_usd)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual((2, 995150), db.execute('SELECT count(*),sum(micro_usd) FROM calls').fetchone())

    def test_invalid_configuration(self):
        for kwargs in [{'timeout': 0}, {'timeout': 61}, {'max_output_tokens': 1537},
                       {'total_micro_usd': 1000001}, {'input_ceiling': 0}]:
            with self.assertRaises(ModelError):
                Config(model='test', **kwargs)

class RequestSizingTests(unittest.TestCase):
    def test_preflight_requires_no_credentials_no_ledger_and_matches_actual_http_bytes(self):
        from apps.compass.backend_model import preflight,request_metrics
        cfg=Config(model='test-model',max_output_tokens=1536)
        data={'fictional':True,'text':'Все значения и пробелы в тексте сохраняются.'}
        with patch.dict(os.environ,{},clear=True):planned=preflight(data,SCHEMA,cfg)
        self.assertEqual(planned,request_metrics(data,SCHEMA,cfg))
        captured=[]
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'DEEPSEEK_API_KEY':'local-test-key'}):
            adapter=DeepSeek(cfg,Budget(Path(tmp)/'ledger.sqlite3'),transport=lambda body,*args:(captured.append(body) or 200,envelope()))
            adapter.generate(data,SCHEMA,synthetic=True)
        self.assertEqual(planned['body'],captured[0])
        decoded=json.loads(json.loads(captured[0])['messages'][1]['content'])
        self.assertEqual(data,decoded['data'])

    def test_metrics_reports_oversize_without_raising_money_limits(self):
        from apps.compass.backend_model import preflight,request_metrics
        cfg=Config(model='test',per_call_micro_usd=1)
        metrics=request_metrics({'fictional':True},SCHEMA,cfg)
        self.assertGreater(metrics['reservation_micro_usd'],cfg.per_call_micro_usd)
        with self.assertRaisesRegex(ModelError,'call_cost_limit'):preflight({'fictional':True},SCHEMA,cfg)
        with self.assertRaisesRegex(ModelError,'invalid_config'):Config(model='test',total_micro_usd=1000001)

    def test_invalid_model_schema_retains_only_safe_usage_for_accounting(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DEEPSEEK_API_KEY':'secret-for-test'}):
            budget=Budget(Path(tmp)/'ledger.sqlite3')
            adapter=DeepSeek(Config(model='test'),budget,transport=lambda *args:(200,envelope('{"status":"private provider text"}')))
            with self.assertRaises(ModelError) as caught:adapter.generate({},SCHEMA,synthetic=True)
            self.assertEqual('invalid_response',caught.exception.code)
            self.assertEqual({'prompt_tokens':10,'completion_tokens':5,'total_tokens':15,'cost_ceiling_micro_usd':35},caught.exception.usage)
            self.assertNotIn('private',str(caught.exception));self.assertNotIn('secret-for-test',str(caught.exception))
