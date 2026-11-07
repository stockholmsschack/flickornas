# Flickornas 2026 compatibility baseline

The 2026 baseline freezes the partial season inputs in
`2026-intermediate-inputs.zip`. The accepted generated Typst source is the
automated compatibility contract. Its PDF is used only for human review.

## Verify the baseline

Run the offline regeneration contract:

```console
uv run pytest tests/test_generation_core.py::GoldenCoreTests
```

The test regenerates Typst from the archived inputs through the generation core
and compares it with the accepted source.

## Re-accept after an approved behavior change

Keep the existing baseline while reviewing the proposed output. Generate a new
Typst candidate from the same archived inputs through the generation core,
render it with Typst, and inspect the full PDF. Replace the golden Typst source
and update its hashes and review details in `2026-golden-acceptance.json` only
after a named reviewer approves the document.

Never overwrite the golden source as part of generation or silently re-capture
the input ZIP. A new input capture is a separate baseline decision and requires
its own manifest and review.
