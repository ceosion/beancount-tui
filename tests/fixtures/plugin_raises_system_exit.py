"""Fixture plugin module that calls ``sys.exit()`` instead of returning a
normal error, for exercising LANG-13's ``SystemExit``-hardening in
``Ledger.load``/``Ledger.reload`` (see ``tests/test_ledger.py``).

A real beancount plugin module must expose ``__plugins__`` naming its
transform function(s) (see ``beancount.loader.run_transformations``); this
one's sole "transform" misbehaves by exiting the process instead of
returning ``(entries, errors)``.
"""

__plugins__ = ("misbehave",)


def misbehave(entries, options_map):
    raise SystemExit("simulated fatal plugin failure")
