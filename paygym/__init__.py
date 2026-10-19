"""PayGym: a verifiable payroll gross-to-net gym.

The rule set (``ruleset/``) is the ground truth; ``paygym.reference`` is a faithful,
clause-cited implementation of it; ``paygym.rubric`` is the single scorer shared by
the eval harness, the GRPO trainer and the sandbox.
"""

__version__ = "0.1.0"


def load_environment(**kwargs):
    """verifiers entry point: ``vf.load_environment("paygym", ...)`` imports this package and calls this.

    Imported lazily so the scorer, generator and sandbox work without the verifiers extra installed.
    """
    from paygym.environment import load_environment as _load

    return _load(**kwargs)
