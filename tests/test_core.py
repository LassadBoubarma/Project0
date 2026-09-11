import unittest
from src.score import score
from src.cost import api_cost, percentile, local_scenario
from src.run import load_data, prompt_for, decode_response
from src.report import summarise

class EvaluationTests(unittest.TestCase):
    def test_exact_match_and_no_repair(self):
        words=['blood pressure','body mass index']
        self.assertEqual(score(' blood pressure\n','blood pressure',words)[:2],(1,'correct'))
        self.assertEqual(score('body mass index','blood pressure',words)[:2],(0,'wrong_answer'))
        for text in ['', 'Blood pressure','blood pressure.','"blood pressure"','Answer: blood pressure','blood\npressure']:
            self.assertEqual(score(text,'blood pressure',words)[:2],(0,'parse_error'))
    def test_disjoint_fifty_and_hidden_mapping(self):
        test,words=load_data('test');dev,_=load_data('dev')
        self.assertEqual(len(test),50)
        self.assertFalse({r['abbreviation'] for r in test}&{r['abbreviation'] for r in dev})
        self.assertEqual(prompt_for(test[0],words),prompt_for({**test[0],'expected':'hidden'},words))
    def test_cost_thinking_and_cache(self):
        m={'input_per_million':2,'cached_input_per_million':.2,'output_per_million':12}
        self.assertAlmostEqual(api_cost({'promptTokenCount':100,'cachedContentTokenCount':20,'candidatesTokenCount':10,'thoughtsTokenCount':5},m),.000344)
        self.assertIsNone(api_cost({},m))
    def test_percentiles_break_even(self):
        self.assertAlmostEqual(percentile(list(range(1,51)),.5),25.5)
        self.assertAlmostEqual(percentile(list(range(1,51)),.95),47.55)
        s={'hardware_usd_per_hour':1,'labour_hours_per_month':2,'labour_usd_per_hour':10,'requests_per_month':1000,'available_hours_per_month':160}
        c=local_scenario(3.6,s,.002)
        self.assertEqual(c['today_usd'],21)
        self.assertEqual(c['100x_usd'],120)
        self.assertEqual(c['break_even_requests_per_month'],20000)
        self.assertIsNone(local_scenario(3.6,s,.0005)['break_even_requests_per_month'])
    def test_refusal_truncation(self):
        m={'provider':'gemini','model':'example','input_per_million':2,'cached_input_per_million':.2,'output_per_million':12}
        self.assertEqual(decode_response({'promptFeedback':{'blockReason':'SAFETY'}},m)[1],'refusal')
        self.assertEqual(decode_response({'candidates':[{'finishReason':'MAX_TOKENS'}]},m)[1],'truncated')
    def test_failure_denominator_unknown_cost(self):
        rows=[{'role':'top_api','latency_ms':'100','correct':'1','status':'correct','api_cost_usd':'.001'},{'role':'top_api','latency_ms':'1000','correct':'0','status':'timeout','api_cost_usd':''}]
        s=summarise(rows,{'models':[{'role':'top_api','model':'example','provider':'gemini'}]})[0]
        self.assertEqual(s['accuracy'],.5)
        self.assertEqual(s['timeouts'],1)
        self.assertEqual(s['cost_per_1k_usd'],'')
        self.assertEqual(s['p50_ms'],550)

if __name__=='__main__':unittest.main()
