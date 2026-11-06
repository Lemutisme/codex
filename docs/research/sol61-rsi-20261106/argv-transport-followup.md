# Case-generation schema and operating-system arguments

The ongoing grex retry exposed a concrete interface failure before Contract
creation. Its drafted `unicode-spaces` case contained only two arguments, but
argument1 contained NUL. The retained worker line is bound in
`grex-draft-interface-failure.json`. The runtime correctly refused an argument
that the operating system cannot represent. The root executor continued working;
its eventual artifact score and this initialization outcome remain separate facts.

The model-facing schema previously described arbitrary strings and arrays while
the runtime required at most64 arguments with no NUL. The shared drafter/prober
schema now declares those same constraints. The capability description explains
that NUL remains representable in stdin and fixture content. Runtime diagnostics
identify the exact argument rather than combining count and representation errors.
No invalid argument is rewritten, and no task workflow or kernel rule is added.

Validation:

-13 case-format controls pass. The schema's regular expression is checked against
  the operating-system CString boundary and runtime validation for empty strings,
  whitespace, Unicode and embedded NUL. Argument-count boundaries are checked.
-NUL remains accepted and retained in stdin and file contents.
-All90 worker tests pass after formatting, covering the shared schema consumers.
-One standalone Sol6.1/max Responses call accepted the constrained schema and
  returned actual U+00A0/U+2003/U+2028 characters in argv, and NUL in stdin.
  `argv-schema-provider-control.json` retains the observed result and wire hashes.

The first diagnostic decoder used Unicode `splitlines()`, incorrectly splitting
a literal U+2028 inside an SSE JSON value. Re-decoding the same retained response
on byte LF boundaries recovered all events and the correct text without another
model request. The benchmark gateway already uses byte-LF framing; this was a
diagnostic-parser error, not evidence of provider or gateway corruption.

Official schema support was checked against
<https://developers.openai.com/api/docs/guides/structured-outputs>.
The live provider probe qualifies the relevant schema constraints, not a new
ProgramBench solver attempt or a complete native task run. Its request is retained
separately from benchmark accounting.

The development change is not installed into the running frozen37-task cohort.
Keep the original grex attempt and any useful artifact result. At cohort closeout,
report initialization coverage independently of scored artifact quality and use
the observed failure to qualify a future deployment.
