# coverage

Read an ODD's own decisions back against the ODD source: which models fired,
which can never fire, and which elements produced no output at all. See the
[ODD coverage guide](../guide/coverage.md) for what each finding means; the CLI
wraps [`analyze`][opm.coverage.analyze] and renders `CoverageReport.to_dict()`.

::: opm.coverage
