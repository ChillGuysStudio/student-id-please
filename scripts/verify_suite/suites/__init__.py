"""Suite registry. Each module exposes SUITE."""
import re
from importlib import import_module

MODULES = ("status", "registry", "scaling", "gameplay", "round_robin", "race", "breaker")


def all_suites():
    suites = [import_module(f"{__name__}.{name}").SUITE for name in MODULES]
    return sorted(suites, key=lambda s: (int(re.match(r'\d+', s.grade)[0]), s.id))
