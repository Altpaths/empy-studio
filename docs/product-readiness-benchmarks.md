# Product Readiness Benchmarks

Empy Studio has a repeatable provider-free benchmark for three representative
project shapes: Python, web, and generic. It creates temporary fixtures, builds
the Project Brain and bounded context plan, measures elapsed local benchmark
time, and records full versus selected context token estimates.

Run it from a checkout with the project environment installed:

```bash
PYTHONPATH=src python scripts/run_product_benchmarks.py \
  --max-seconds 5 \
  --min-savings-percentage 1 \
  --output benchmark-results.json
```

The benchmark never calls a provider and never writes to the repository. Its
output is evidence about local selection and scheduling overhead, not a claim
about billed provider tokens. Provider-reported usage remains the source of
truth after a real run. CI fails if any fixture exceeds the elapsed-time limit
or falls below the configured context-saving threshold.

The release workflow separately builds a clean package environment and, for a
stable macOS publication, requires Developer ID signing, notarization,
stapling, `codesign` verification, and `spctl` Gatekeeper acceptance. Missing
Apple credentials keep stable publication blocked rather than weakening the
gate.
