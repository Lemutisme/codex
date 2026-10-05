You are improving how an autonomous agent works. The agent's method is the policy bundle in ./policy:

- executor.md: standing instructions the agent follows on every task;
- drafter.md, prober.md, reviewer.md: how its work is turned into a contract, probed and reviewed;
- research.md: this method, which the next research step will follow.

Work like a careful experimenter.

1. Start from evidence, not from ideas. Read ./archive. Each run there names its task and version, the outcome measured from beyond the agent's reach (a hidden pass rate, where one exists), what the agent's own checks concluded, its cost, and excerpts of its failures. Find the deficiency that costs the most and recurs on more than one task. Point to the evidence.
2. State one hypothesis about the mechanism: what the agent does, why that produces the failure, and what change in behavior would remove it.
3. Make the smallest change to the bundle that tests the hypothesis. Prefer sharpening or deleting instructions to adding new ones, and change one mechanism at a time. Everything in executor.md is read on every task, so every sentence must earn its place.
4. Remember what evidence can show. The agent's own checks measure diligence: how well it used what it could read and ask. Only information from beyond its reach certifies. So prefer changes that make the agent use the information available to it better (observe and test against what it can query, early and broadly; stop repeating fixes that no longer yield new information) or that make it ask for what it lacks.
5. Write ./EXPERIMENT.md with the sections Deficiency (with pointers into the archive), Hypothesis, Change (what you edited and why), Prediction (an observable effect on future runs), Falsifier (the result that would show the hypothesis wrong) and Risks.

A careful negative result is a valid outcome. If the deficiency is real but no small change is likely to fix it, or the evidence is too thin, leave the bundle unchanged and say why in EXPERIMENT.md.
