"""An independent second implementation of MarketingIQ's numbers, for checking the first.

The oracle reads a synthetic dataset's CSV files directly: no database, no staging, and no
imports from `marketingiq`. It was written from the documents (attribution.md,
lifecycle_and_classification.md, metrics.md, core-model.md), not from the application's
code. The only thing the two implementations share is the rule book (`rules.toml`), which
is configuration: the mappings themselves, not the code that applies them.

It favours being obviously right over being fast: one pass per lead, plain loops, exact
fractions for attribution credit. When the oracle and the application disagree, one of them
has a bug or a document is ambiguous, and either way someone has to look.
"""

from oracle.facts import Facts, load

__all__ = ["Facts", "load"]
