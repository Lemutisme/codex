# Test-time improvement of the updater, through its descendants

Earlier guarded mode deferred pure research-method changes. That left a real missing
path: changing M could not earn adoption unless bundled with a task/harness change.
This increment closes that path. It does not claim that a real model has improved.

## What is evaluated

Let P/H be the task policy/runtime and M the analyst/challenger/researcher policies.
The serving updater proposes M1 from its own observed work. For a pure M change:

```text
freeze M1 while P0/H0 remain unchanged
  -> assign and run a fresh stream observation with P0/H0
  -> freeze common observation O, initial knowledge K0 and full target bundle
  -> control: M0 analyst -> M0 challenger -> M0 researcher -> descendant D0
  -> treatment: M1 analyst -> M1 challenger -> M1 researcher -> descendant D1
  -> freeze BOTH descendants
  -> score D0 and D1 on the same independently reserved tasks T
  -> fixed downstream gate -> ProContract adoption of M1, NOT D1
  -> next production task uses P0/H0 with M1
  -> next research uses M1 and receives its attributed method-trial outcome
```

Both arms start with byte-identical target/O/K0. They have separate workspaces,
post-analysis knowledge and outputs; the candidate method, sibling results and held-out
plans are not inserted into the common archive. Methods may form different posterior
knowledge—that is part of the treatment, not a confound to erase. A control run cannot
supply the treatment's analysis or vice versa.

The editable target remains the same complete incumbent bundle in both arms. The active
producer selects the standing method instructions separately. A descendant may change
only the already authorized task-shaping files and bounded `harness.json`; the target's
three method files must stay unchanged. A valid null update returns the common target.
The descendants do not become serving producers as a side effect of this experiment.

## Fixed criterion and custody

New guarded campaigns default to `--method-confirmation paired-descendants`. Explicit
`defer`, and older terms without the field, retain the former behavior; running old
campaigns is not permission to change their frozen experimental protocol.

The current protocol is **one paired updater episode**. It uses the predeclared
`confirm_tasks`, `confirm_min_wins` and a finite nonnegative `confirm_min_delta`, with a
strict `mean(score(D1)-score(D0)) > confirm_min_delta` gate. Task-control identities
that are equal cannot win via two stochastic executions. No best-of-N descendant
selection or post-score replacement is permitted. Each method gets one attempt for each
of its three roles at the same declared role deadlines.

The durable plan binds the method pair, incumbent sequence, fresh observation, common
input capture, deadlines, task allowance and held-out source reservation. Both output
captures precede every held-out label. Role receipts bind the actual producer policy,
prepared input, prompt, launch and output; a separately registered sibling cannot be
substituted as the generated descendant. Source/evaluator/score custody is rechecked
before first adoption. Unknown launches remain unknown and are never bought again.
Invalid downstream evaluations halt the frozen experiment without becoming zero scores.
A completed malformed learning delivery does not qualify or buy a retry.

The ordinary task-confirmation path cannot consume this method plan. Its support is
about the updater that generated a descendant, not the inherited task score of M1.
The existing Rust ProContract adoption transaction still publishes a single incumbent;
no second authority pointer or mutable grader was added.

Later research receives a bounded `archive/method-trials/<method>.json` summary mapping
the method/comparator to their descendants and downstream outcome. It includes no future
holdout plan. This matters: making the right adoption decision while hiding its cause
from the next researcher would leave the learning loop incomplete.

## Cost and interpretation

For a batch of one observation and n held-out tasks, a method trial needs one observation
runner, six learning-role runners, and 2n descendant task runners. The observation is the
assigned stream task, not an additional duplicate. Task runs retain their one five-hour
allocation; learning deadlines and the study-wide launch/allocated-second cap remain
explicit. For three phases with four confirmation tasks, the worst ordinary-role retry
allowance plus this method trial can require 11 task and 16 learning launches, not the
14-learning-launch arithmetic for an ordinary task-policy probe. This is an allocation
calculation, not authorization or a promise to spend it.

A strict win in one episode supports the campaign's empirical-winner convention. It is
not statistical significance or proof that M1 is generally better: multiple test cases
are not independent method-generation replicates. It also does not show D1 beats P0;
that requires a separate P0 evaluation arm. General updater and recursive-benefit claims
need new starts/families, repeated independent method trials, complete costs and suitable
controls. Weight-updating TTRL has not been implemented or claimed.

## Evidence in this delivery

The integration fixture uses the real Host, Rust store, immutable captures, confirmation
and atomic adoption, with explicitly synthetic task and research peers. Its toy grader
rewards an executor change, not a method marker. The new method can be adopted while
its own task phenotype stays identical to the incumbent, and then produces the next
method proposal. Identical downstream task identities are rejected rather than promoted
merely because the method version changed.

No new authenticated Luna or Docker execution is claimed. The source and runnable
runtime are concrete deliverables, but live M/H generation, native execution, independent
ProgramBench confirmation and actual RSI gains still require an authorized execution
environment and real fresh resources. The prior three-task pilot is not that evidence.
