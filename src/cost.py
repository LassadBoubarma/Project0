"""Percentiles and a stated self-hosted cost scenario for local models."""

import math


def percentile(values, q):
    xs = sorted(values)
    position = (len(xs) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    return xs[lo] + (xs[hi] - xs[lo]) * (position - lo)


def local_scenario(mean_seconds, settings):
    required = (
        "hardware_usd_per_hour",
        "labour_hours_per_month",
        "labour_usd_per_hour",
    )
    if any(settings.get(k) is None for k in required) or mean_seconds <= 0:
        return {"status": "pending hardware and labour assumptions"}
    throughput = 3600 / mean_seconds
    variable = settings["hardware_usd_per_hour"] / throughput
    fixed = settings["labour_hours_per_month"] * settings["labour_usd_per_hour"]
    volume = settings["requests_per_month"]
    capacity = throughput * settings["available_hours_per_month"]
    return {
        "status": "estimated from measured throughput",
        "requests_per_hour": throughput,
        "variable_per_request_usd": variable,
        "fixed_monthly_labour_usd": fixed,
        "cost_per_1k_usd": 1000 * (variable + fixed / volume),
        "today_usd": fixed + volume * variable,
        "100x_usd": fixed + 100 * volume * variable,
        "capacity_per_month": capacity,
        "100x_fits_one_machine": 100 * volume <= capacity,
    }
