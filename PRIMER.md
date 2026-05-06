# Building a Cognitive Simulacrum — A Primer for AI Agents

This document is a recipe for building a simulacrum of a specific person — an agent that thinks like them, not just writes like them. It's the distilled output of an 8-architecture iteration cycle building one for Jeremy McEntire. The Jeremy-specific details are illustrative; the recipe is the load-bearing thing.

## 1. What a Simulacrum Is (and Isn't)

A simulacrum is **a model of someone's cognitive moves** — the specific patterns of thought they apply to novel situations. It is NOT a style-transfer of their writing voice. The two get conflated; they are not the same problem.

Style transfer reproduces vocabulary, sentence rhythm, register. Easy. Fine-tunable on a corpus. Largely useless for the actual task.

Cognitive simulacrum reproduces the moves: what frame they refuse, what assumption they interrogate, what counter-example they reach for, what hedge they explicitly avoid. Hard. Requires teaching WHY not just WHAT.

**Test of success:** the simulacrum should engage with novel situations the user has never written about and produce the move the user would have produced if asked. If it can only echo their existing writing on familiar topics, you've built a parrot, not a simulacrum.

## 2. The Cognitive Moves Are the Load-Bearing Thing

Before any architecture work, identify the user's cognitive move taxonomy. These are the *operations* they apply to any input. For Jeremy, the taxonomy includes:

- Refuse epistemic authority unless earned
- Demand operational criterion when one is missing
- Refuse malformed premises (false binaries, undefined buzzwords, false consensus)
- Derive from first principles / invariants rather than consensus advice
- Interrogate the load-bearing assumption underneath any standard recommendation
- For architecture review: identify the constraint envelope first, then evaluate the choice against it
- Use indirect interventions (shape environment so desired behavior derives) over direct mandates
- Treat ideas as derivations, not beliefs
- Constraint-driven derivation over values-narrative
- Forced-binary refusal: "I reject your reality"
- XY-problem awareness: ask what the user is actually trying to do

Each user has their own taxonomy. Yours starts by reading their corpus — articles, transcripts, conversations — and listing the moves you observe them making *repeatedly*. The repetition is the signal. One-off examples are insufficient.

## 3. What Architecture Works, What Doesn't

We tested 8 architectures. Most didn't pay. Document the failure modes so future builders don't re-walk them.

**Doesn't work:**
- **Park-style flat memory + cosine retrieval** (Stanford genagents). Reproduces stylistic surface but plateaus around 6/10 on any disposition probe. The retrieval mechanism doesn't preserve the cognitive moves; it preserves the words.
- **Graph-walk retrieval / cross-source repetition edges**. More complex retrieval, no measurable gain. The signal isn't in finer retrieval — it's in teaching the moves.
- **Multi-substrate ensembles with judge selection**. Three-substrate (Anthropic + OpenAI + Gemini) with a judge picking the best response. Cost goes 3x; quality unchanged or worse. The judge can't reliably pick.
- **Conversational fine-tuning at scale** (large training data, generic Q/A pairs). Washes out the distinctive moves. The fine-tune learns "how to chat" not "how to think like X."
- **Behavior dispatchers / 5-mode classifiers**. Adding mode-A through mode-E with mode-specific augments hurts more than helps. Each augment introduces drift; collectively they erode the user's voice.

**Works:**
- **Annotated few-shot pairs in the system prompt** (Anthropic, claude-sonnet-4-5). The breakthrough. Each pair includes: the input that needed the move, the *flaw* in that input, the *cognitive move* the user applied, the *general pattern* the move belongs to, and the user's actual response. The model generalizes the pattern, not the surface.
- **Targeted fine-tune for autobiographical recall**. Small fine-tune (~$2.50, ~60K trained tokens) on autobiographical Q/A pairs gives clean recall without the parroting failure mode of larger fine-tunes. Use as a generalist branch when factual recall matters.
- **Two-phase classifier dispatcher**. Anthropic classifier routes each turn to either the recall branch (fine-tune) or the cognitive-moves branch (annotated few-shot specialist). Default to the specialist; only route to recall on pure autobiographical/factual probes.
- **Targeted single-mode classifier** for one specific failure. Adding ONE explicit mode for one observed failure pattern (in our case "operationalized-criterion + invitation to debate") works. Adding five modes doesn't.

## 4. The Annotated Few-Shot Recipe

This is the load-bearing technique. Get it right.

### 4a. Source the corpus

Use anything that captures the user's cognitive moves *in dialog*:
- 1:1 conversation transcripts (Slack DMs, email exchanges, Claude/ChatGPT chats they had)
- Articles where they push back on a position
- Interviews where they refute the interviewer
- Code review comments
- Public debates / podcast appearances

Skip: their fiction, their casual social posts, anything where they're being polite. You want the moments where they refused, demolished, or derived.

### 4b. Identify canonical pairs

A canonical pair is an exchange where:
- The interlocutor made a flawed move (false binary, hedged claim, authority cite, malformed premise, sycophantic over-extension, consensus-advice misapplication)
- The user responded with a *cognitive move* that addressed the flaw (refused, demanded criterion, deployed counter-example, etc.)

5-10 canonical pairs is enough. Pick the highest-teaching-density ones — the moves that exemplify the user's distinctive thinking.

### 4c. Annotate each pair

For each pair, write:

```json
{
  "context": "where this exchange came from",
  "claude_turn": "what the interlocutor said",
  "annotation": "WHY this needed pushback — name the specific flaw, the specific cognitive move the user applied, and the general pattern (so the model can generalize)",
  "jeremy_turn": "the user's actual response, verbatim"
}
```

The annotation is the load-bearing field. Without it, you're back to style transfer. With it, the model learns the move-pattern.

Example annotation: "Interlocutor proposed a false binary between trust and oversight, asking which the user prefers. The user refused the binary entirely, naming that the binary itself encodes a wrong axis — the question isn't 'which to favor' but 'what mechanism is doing the work.' This is the wrong-axis refusal pattern: when the question's axis is itself the failure, don't pick a side; rotate the axis."

### 4d. Extract additional pairs

Beyond canonicals, mine the corpus for 20-40 more pairs with similar structure. Less teaching-dense individually, but cumulative coverage of the user's move taxonomy.

### 4e. System prompt structure

```
You are <Name>. Cognitive characteristic: <one paragraph naming the
core posture — for Jeremy it was "refuses to grant interlocutors epistemic
authority unless they earn it">.

Selectiveness: <when this posture applies vs when direct engagement is
correct>. The contrarian/skeptical mode is selective, not default.

Register: <tight, derivational, no padding, direct without being mean>.
Profanity / sharp dismissal is an *escalation* move, not the default tone.
Reserve it for sustained bad-faith engagement.

ASSUMPTION-INTERROGATION (load-bearing — runs BEFORE any conventional advice):
<the rule from §7 below>

ARCHITECTURE-REVIEW POSTURE (when reviewing existing system design):
<the rule from §7 below>

EXAMPLES:
<8 annotated pairs — 5 canonical + 3 extracted, weighted toward
diversity of cognitive moves>

When responding:
1. Identify whether the framing has a flaw worth calling out
2. If yes: name the flaw, deploy the move
3. If no: answer directly — not contrarian by default
4. Register: tight and direct without mean. Escalation moves only on
   sustained bad-faith engagement.
5. Be concrete — specific counter-examples and worked derivations beat
   abstract principles every time.
```

Token budget: ~5-6K tokens with 8 annotated examples. claude-sonnet-4-5 handles this fine.

## 5. The Two-Phase Dispatcher (Optional)

If you need both autobiographical recall AND cognitive-move fidelity, build a dispatcher:

**Phase 1 (classifier):** Anthropic claude-sonnet-4-5 classifies the latest turn:
- GENERALIST: pure autobiographical / factual recall about the user (project descriptions, biographical facts, prior roles, dates)
- SPECIALIST: everything else — opinion, suggestion, draft, critique, multi-turn continuation, adversarial framing

Default to SPECIALIST. The classifier's GENERALIST scope must be narrow; if you broaden it, content-generation and continuation requests will route to the recall branch and produce parroted or hedge-y output.

**Phase 2 (dispatch):**
- GENERALIST → small fine-tune (gpt-4o-mini works) with a thin system prompt + project glossary (one-line ground truth for each named entity)
- SPECIALIST → annotated few-shot specialist on Anthropic

Glossary is critical. Without it, the fine-tune fabricates plausible-sounding descriptions of named projects/concepts.

## 6. Evaluation Methodology

You need three eval sets, each measuring different dimensions:

**a. Held-out interview (highest fidelity).** ~25 questions across recall / position / disposition / adversarial framings. The user answers them themselves. The user's answers are gold standard. Score predictions against actuals via LLM judge (gpt-4o-mini or stronger). This is the ceiling test — if the simulacrum can't match here, nothing else matters.

**b. Adversarial failure corpus.** ~10 probes specifically designed to trip the system: mixed-mode (part direct, part adversarial), subtle hidden presupposition, pushback-trap (looks adversarial but is well-formed), compound questions, sycophantic bait, false-humility hedge, authority cite, question-disguised-as-claim, well-formed-direct, operationalized-criterion-with-debate-invite. Each probe has expected_moves describing the right cognitive moves. Score against expected_moves.

**c. Architectural-judgment probes (or whatever the user's domain is).** ~10 probes in the user's actual professional domain. For Jeremy: simple-over-fashionable, Unix-greybeard, theoretical-vs-practical optimization, fundamentals (CAP theorem, normal forms, bitmasks), XY-problem. The user's actual *expertise* probes. This eval most reflects what the deployment use case will surface.

**Don't:** rely on a single eval. Different evals reward different architectures. Smattering questions favor recall; adversarial corpus favors the specialist; architectural probes favor cognitive-moves training. The system has to score acceptably on all three.

**Do:** generate fresh probe sets between iterations. Once a probe set has shaped your architecture decisions, scores on it are no longer independent.

## 7. The Two Meta-Rules That Catch Systemic Failures

Both rules sit at the top of the system prompt, before the numbered "When responding" rules.

### 7a. Assumption-Interrogation Rule

```
Most conventional wisdom is correct under specific conditions and
inverts outside them. Before applying any standard advice, identify
the load-bearing assumption it depends on, then check whether that
assumption holds in this context.

Pattern:
1. Standard advice X is being applied
2. X is correct because assumption Y is typically true
3. Is Y true here?
   - Yes → X applies
   - No → derive from invariants instead; consensus advice is misapplied
   - Unknown → Y becomes the question; refuse to apply X until determined

Examples (replace with your user's domain):
- "Validate customer demand first" depends on: founder belief is unverified
  market speculation. When the belief is invariant-derived, demand-validation
  hedges a failure mode that doesn't exist.
- "Prefer simpler frameworks" depends on: humans read and write the code.
  When AI does most contributions, structural verbosity becomes an asset.
- "Industry best practices" depend on: the cost model the practice was
  developed under. When the cost model shifts, the practice may invert.
```

This rule fixes the most common failure mode: defaulting to consensus advice without checking what assumption makes it valid.

### 7b. Architecture-Review Posture

```
When reviewing existing architecture, the default move is NOT to propose
alternatives. The default move is to identify the load-bearing constraints
that drove the choice (scale, latency, read/write ratio, sharding,
concurrency, failure-mode cost, who reads/writes the code, deployment
topology), then evaluate the choice against those constraints.

If the load-bearing constraints aren't in the prompt, DEMAND them before
critiquing. An architecture exists in a constraint envelope; without the
envelope, "general-purpose tool wins" reasoning leads you astray.

Worked example: a bitmask schema for availability looks "limited"
without context. Given scale of millions of records × tens of thousands
of concurrent queries × real-time latency × clean sharding requirements,
the bitmask is load-bearing-elegant. Recommending tstzrange + GiST under
those constraints would be a catastrophic regression.
```

This rule fixes the second-most-common failure mode: critiquing existing systems by alternative-shopping rather than constraint-checking.

## 8. Common Failure Modes and Their Fixes

| Failure mode | Symptom | Fix |
|---|---|---|
| Style without structure | Sounds like the user; doesn't think like them | Annotated few-shot with WHY annotations, not just example pairs |
| Over-meanness | Defaults to maximally-pugnacious register from canonical pairs | Explicit register rule: profanity is escalation only, not default |
| Multi-turn parroting | Fine-tune re-emits prior turn verbatim when asked to continue | (a) Multi-turn rule in fine-tune system prompt; (b) route continuation requests to specialist, not generalist |
| Project fabrication | Fine-tune invents plausible-sounding project descriptions | Project glossary in system prompt + "I don't have that to recall" rule for unknown items |
| Consensus-advice default | Applies standard recommendations without checking assumptions | Assumption-interrogation rule (see §7a) |
| Alternative-shopping on review | Critiques existing systems by suggesting "more general" alternatives | Architecture-review posture (see §7b) |
| Classifier mis-routing | Sends content-generation to recall branch, producing hedges | Narrow GENERALIST scope to autobiographical-only; default to SPECIALIST |
| RLHF safety bias | Defaults to safe-consensus on politically loaded topics | Assumption-interrogation rule with worked example in the politically-charged domain |

## 9. A Concrete Buildup Plan

For another AI building a simulacrum of a different user:

1. **Source corpus (1-3 hours of human time).** User dumps their conversation history, articles, transcripts. Skip fiction and social-pleasantry content.

2. **Identify cognitive move taxonomy (1-2 hours).** Read through corpus; list the moves you observe repeatedly. The user can confirm/correct your list.

3. **Generate held-out interview (30 min).** ~25 questions across recall/position/disposition/adversarial dimensions. User answers them themselves. These are gold standard.

4. **Annotate canonical pairs (2-4 hours).** 5-10 high-density exchanges with the structured WHY annotation. Plus ~30 extracted pairs.

5. **Build minimal v1.** Anthropic claude-sonnet-4-5 + system prompt with assumption-interrogation rule + 8 annotated examples + register guidance. ~5-6K token system prompt.

6. **Score against held-out interview.** LLM-judge for first signal; user rates a sample for ground truth.

7. **Identify failure modes from worst probes.** Write rules or add few-shot examples that fix them. Iterate.

8. **(Optional) Add fine-tune generalist.** If the prompt-only version regresses on autobiographical recall, train a small (~$5) fine-tune on autobiographical Q/A pairs. Wrap in a thin system prompt with project glossary.

9. **(Optional) Add classifier dispatcher.** Only if you have two architectures with complementary strengths. Default to specialist; narrow GENERALIST scope.

10. **(Optional) Add targeted single-mode classifier.** For one specific failure mode the system reliably mishandles. Don't do five modes.

## 10. What NOT to Do

- Don't start with fine-tuning. Annotated few-shot is cheaper, more interpretable, and converges faster.
- Don't optimize for one eval. Smattering / failure corpus / domain probes test different things.
- Don't trust gpt-4o-mini scores past ~7. Above that ceiling, get human ratings or a stronger judge.
- Don't add complexity (graph retrieval, multi-substrate ensembles, behavior dispatchers) without a measured failure that demands it.
- Don't broaden the classifier's GENERALIST scope to be helpful. Default to SPECIALIST. The cost of mis-routing recall to specialist is small; the cost of mis-routing content-generation to fine-tune is large (parroting, fabrication).
- Don't over-extend the few-shot examples toward the user's most pugnacious moments. The model will treat that as the default register. Mix in calmer rigorous examples.
- Don't skip the WHY annotations. Examples without WHY teach style; examples with WHY teach moves.

## 11. Closing Note

The simulacrum's quality is bottlenecked on the *annotation quality* of the few-shot pairs and the *coverage* of the user's cognitive moves. Architecture beyond that is rounding error. Spend the time on the corpus and the annotations. Everything else converges in 1-2 days.

The goal is not "answers questions like the user." The goal is "applies the user's cognitive moves to situations the user has never encountered, and produces the move the user would have produced." The held-out interview is the test of that. If it scores ~7 on LLM judge and the user agrees with the user-rating sample, you have a working simulacrum.
