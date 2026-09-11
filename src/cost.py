"""USD list-price accounting and an explicitly stated local cost scenario."""
import math


def api_cost(usage, model):
    if not usage or 'promptTokenCount' not in usage:
        return None
    prompt = usage['promptTokenCount']
    cached = usage.get('cachedContentTokenCount', 0)
    output = usage.get('candidatesTokenCount', 0) + usage.get('thoughtsTokenCount', 0)
    return ((prompt-cached)*model['input_per_million'] +
            cached*model['cached_input_per_million'] +
            output*model['output_per_million']) / 1_000_000


def percentile(values, q):
    """Linear interpolation at (n-1)*q, including every attempted request."""
    xs = sorted(values)
    position = (len(xs)-1)*q
    lo, hi = math.floor(position), math.ceil(position)
    return xs[lo] + (xs[hi]-xs[lo])*(position-lo)


def local_scenario(mean_seconds, settings, api_per_request=None):
    """On-demand hardware time + fixed monthly operator time, one worker."""
    required = ('hardware_usd_per_hour','labour_hours_per_month','labour_usd_per_hour')
    if any(settings.get(k) is None for k in required) or mean_seconds <= 0:
        return {'status':'pending hardware and labour assumptions'}
    throughput = 3600/mean_seconds
    variable = settings['hardware_usd_per_hour']/throughput
    fixed = settings['labour_hours_per_month']*settings['labour_usd_per_hour']
    volume = settings['requests_per_month']
    capacity = throughput*settings['available_hours_per_month']
    result = {'status':'estimated from measured throughput','requests_per_hour':throughput,
              'variable_per_request_usd':variable,'fixed_monthly_labour_usd':fixed,
              'cost_per_1k_usd':1000*(variable+fixed/volume),
              'today_usd':fixed+volume*variable,'100x_usd':fixed+100*volume*variable,
              'capacity_per_month':capacity,'100x_fits_one_machine':100*volume<=capacity}
    if api_per_request is not None:
        difference = api_per_request-variable
        result['break_even_requests_per_month'] = fixed/difference if difference>0 else None
        result['break_even_note'] = ('Local cheaper above break-even, within capacity.' if difference>0
                                     else 'No positive break-even: local variable cost is at least API cost.')
        result['break_even_fits_one_machine'] = difference>0 and fixed/difference<=capacity
    return result
