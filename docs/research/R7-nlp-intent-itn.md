# R7 — NLP layer: ITN, intent detection, embeddings, NER, project vocabulary, bias limits

Research landed 2026-09-26. Every claim is tagged **VERIFIED** (primary source fetched and
quoted/cited), **PLAUSIBLE/SECONDARY** (credible secondary source, not confirmed primary),
or **UNVERIFIED** (plausible / widely repeated, not confirmed). No subagents were spawned;
all research below was done sequentially in this session.

## Headline

1. **Pynini/OpenFst on Windows is a dead end for a signed installer — settle open question
   #10 as "no."** Pynini's own documentation site links out to a Stack Overflow post titled
   *"Installing Pynini on Windows 10"* rather than documenting it directly (**VERIFIED** —
   fetched `openfst.org/twiki/bin/view/GRM/Pynini`), and community reports converge on WSL
   as the real path (**PLAUSIBLE/SECONDARY**). conda-forge does publish `win-64` builds
   (`pynini-2.1.6.post1-py311h3257749_1.conda` exists, **VERIFIED** via search of the
   conda-forge feedstock file listing), and unofficial win_amd64 wheels exist on PyPI-adjacet
   sources (HuggingFace-hosted `.whl`, a `sunxfancy` Windows port repo) — but "an unofficial
   third party rebuilds this for you" is not something to base a signed commercial installer
   on. **Do not bundle pynini/OpenFst in the shipping product.**
2. **A Rust-native alternative to the whole NeMo-text-processing stack already exists and
   is a much better fit for D-0006's Rust-port seam:** `rustfst` (MIT/Apache-2.0, v1.3.1,
   pushed 2026-04-21, 190 stars — **VERIFIED** via crates.io API and GitHub API) plus
   `RustedBytes/ukrainian-itn`, a from-scratch Ukrainian ITN grammar built on rustfst that
   explicitly does **not** require Pynini, OpenFst, or a C++ toolchain at runtime, with
   Python bindings behind a feature flag via maturin (**PLAUSIBLE/SECONDARY** — read via
   fetch, not independently verified by inspecting source). It is very new (created
   2026-09-20, 14 commits, 0 stars) — a signal, not yet a dependency to adopt.
3. **Contextual bias-list degradation has real published numbers, and they support the
   project's dynamic-vocabulary instinct over a static giant list.** BR-ASR (arXiv
   2505.19179) reports expanding a bias list to 200K entries costs only "0.3 / 2.9% absolute
   WER / B-WER degradation with a 99.99% pruning rate and only 20ms latency per query on
   test-other" (**VERIFIED**, quoted from the abstract) — but that result is conditioned on
   **pruning 99.99% of the list before decoding**, i.e. the win comes from *not* biasing on
   most of the list per utterance, which is exactly the "dynamic active subset" strategy
   this project should adopt, not a license to hand the decoder a flat 200K list.
4. **spaCy's transformer/NER stack is not the right tool here, on cost-benefit alone, not
   just latency** — see Section D. NER over dictated speech in a dictation-only product
   (no actions shipping until Checkpoint 1, D-0005) has no consumer yet; the identifier
   surfacing job for W3 is better served by lighter, deterministic tooling (tree-sitter +
   ctags + git metadata) than by a general-purpose NER model.

## A. Inverse Text Normalization

### Pynini / OpenFst on Windows — settled

- **Pynini's own wiki page** ("Third-party information about the library") lists exactly
  one Windows resource: a link to
  [a Stack Overflow question](https://stackoverflow.com/questions/57898360/how-can-i-install-and-use-pynini-on-windows-10)
  (**VERIFIED**, fetched `openfst.org/twiki/bin/view/GRM/Pynini` directly). The project does
  not maintain or document Windows support itself.
- Multiple 2026-era GitHub issues (`SpenserCai/ComfyUI-FunAudioLLM#7`, `xorbitsai/inference#2057`)
  report pynini failing to build from source on Windows (**PLAUSIBLE/SECONDARY** — issue
  titles/summaries, not read in full).
- **conda-forge does carry `win-64` pynini builds** (feedstock lists
  `win-64/pynini-2.1.6.post1-py311h3257749_1.conda`) — this is the one channel where "does a
  real, officially-published Windows binary exist" is answered yes. But conda-forge implies
  shipping a **conda environment inside the installer**, which is a materially heavier and
  less standard packaging story for a Tauri + PyInstaller-style sidecar than a plain venv +
  pip wheels (R5's sidecar model assumes a self-contained Python executable, not a conda
  runtime).
- Unofficial pip-installable win_amd64 wheels exist (a HuggingFace-hosted `.whl` file, the
  `kimdwkimdw/unofficial-pynini-wheels` and `sunxfancy/pynini-2.1.6.post1` "Windows port"
  repos) — **third-party, unsigned provenance, no guarantee of update cadence.** Shipping a
  commercial signed installer on top of an individual's unofficial wheel rebuild is a supply
  chain risk, not just an inconvenience.
- **OpenFst itself** has Windows/MSVC ports, but they are community forks, not upstream:
  `kkm000/openfst` and `jtrmal/openfst` ("Port of the OpenFST library to Windows") plus an
  older `2php/openfst` prebuilt-for-1.6.3 repo. Kaldi's own Windows install docs route
  through one of these forks. **VERIFIED at the level of "these repos exist and are what
  Kaldi-on-Windows uses"**; build success on a clean modern MSVC toolchain was not
  independently reproduced in this research session.

**Conclusion: settle open question #10 as "buildable only through non-primary channels
(conda-forge win-64, or WSL, or third-party wheels/forks); no first-party PyPI win_amd64
wheel, no first-party MSVC build story."** This does disqualify it for the primary shipping
path, per the brief's own criterion. It remains usable for **offline grammar development**
on a Linux/WSL dev box, compiling the resulting WFST to a portable binary artifact that ships
without pynini/OpenFst present at runtime — NeMo-text-processing's own model is "compile the
grammar once, ship the compiled FST," which decouples the *build-time* Linux/pynini
dependency from the *runtime* dependency. That pattern, not pynini itself, is what's worth
carrying into Phase 1 tooling notes (not a frozen decision — flag as a build-pipeline choice
for the lead).

### Deterministic alternatives — the real Phase 1 candidates

| Approach | Windows/Rust fit | Maturity | Verdict |
|---|---|---|---|
| **Hand-written rule/regex cascade in Python** (numbers, dates, units, URLs) | Trivial on Windows; ports to Rust as a rewrite, not a binding problem | You write and own it | **Recommended for Phase 1.** Full control over the developer-CLI aggressiveness question (see below); no packaging risk |
| **`rustfst`** (crates.io, MIT/Apache-2.0, v1.3.1, 2026-04-21) | Pure Rust, no C++ toolchain, first-class Windows | 190 GitHub stars, 38 open issues, actively pushed | The right WFST *engine* for a later Rust-native ITN grammar, if a WFST approach is wanted at all |
| **`RustedBytes/ukrainian-itn`** | Ships as Rust + optional Python bindings via maturin; author states no Pynini/OpenFst/C++ toolchain needed for end users | Extremely new (created 2026-09-20), 0 stars, 14 commits | **Watch, do not adopt yet.** Directly relevant to the Russian/Ukrainian code-switching scenario if it matures |
| **sherpa-onnx `rule_fsts` / `rule_fars`** | Already in the pipeline if sherpa-onnx is adopted for ASR (R1/R4) | Documented as a hotword/homophone-replacement feature (Aho-Corasick-based per the hotwords doc); **could not confirm from primary docs in this session that `rule_fsts`/`rule_fars`/`HomophoneReplacerConfig` are the same subsystem as biasing** | **UNVERIFIED in this session** — the k2-fsa hotwords page fetched did not surface `rule_fsts`/`HomophoneReplacerConfig` details; needs a direct source-tree read of sherpa-onnx's config structs, which is out of this memo's fetch budget. Do not build on this without re-checking |
| **NeMo-text-processing (WFST, pynini-based)** | Not Windows-runtime-viable per above | Actively documented (24.09–25.09 doc versions found) | Use only as an offline reference grammar to port rules from, or compile-once-ship-FST if a build pipeline is set up on Linux/WSL |

### Neural/hybrid ITN

Not independently researched to primary sources this session beyond what NeMo's docs state
in passing (NeMo also ships "Neural-based TN/ITN models" alongside the WFST path,
**PLAUSIBLE/SECONDARY**, not fetched in detail). A neural ITN model adds a forward pass to
the 20 ms p50 / 50 ms p95 NLP budget for what is fundamentally a deterministic rewriting
task (numbers, dates, units follow closed grammars) — **not recommended** as the primary
path; the latency budget is tight enough that a table-driven rule cascade is the safer
default, with a neural pass considered only if rule coverage evidence shows a real gap.

### Coverage and the CLI-dictation conflict — this is the one to get right

**Aggressive ITN actively fights this product's core user.** Turning "dash dash interactive"
into "--interactive" is correct for a shell command and wrong if the user is writing prose
about a flag named `--interactive`; turning "kubectl get pods dash n kube dash system" into
literal dashes vs. "kubectl get pods -n kube-system" is exactly the win when in a terminal
and exactly the failure when dictating a Slack message describing the same command in
words. **A per-application ITN aggressiveness dial is not attested anywhere in the sources
surveyed this session** — it did not surface in Talon's documentation, in the vendor docs
(AssemblyAI/Deepgram/Speechmatics, per R3), or in general ITN literature. Talon Voice comes
closest with a *different* mechanism: a global command/dictation-mode switch plus an
explicit escape hatch (see Section B) — but that is user-driven mode switching, not an
automatic per-focused-window aggressiveness policy. **Treat "ITN aggressiveness varies by
focused application" as this project's own invention, not prior art**, and flag it as an
explicit product bet in `PRODUCT.md`/`DECISIONS.md` territory (for the lead, not this memo)
rather than something to cite as validated.

Practical implication for the rule cascade: gate the numeral/dash/symbol rules that are
*helpful in code contexts and harmful in prose contexts* behind the same focused-window
context signal that already drives contextual biasing (D-0002's context harvester), not
behind a single global setting.

### Multilingual (English/Russian/Ukrainian)

- ITN grammars are per-language by construction in every system surveyed (NeMo-text-processing
  ships separate language grammars; the WFST approach is explicitly grammar-per-language,
  **VERIFIED** by NeMo's own docs structure referencing language-specific taggers/verbalizers).
- Slavic ITN is a much smaller ecosystem: the only concrete Windows/Rust-relevant artifact
  found is the brand-new `RustedBytes/ukrainian-itn` (see above). No equivalent Russian ITN
  crate/library was found in this session's searches — **this is a gap**, and given R3's
  finding that Parakeet-TDT-v3 is the code-switching ASR candidate with native Ukrainian/
  Russian support, the ITN layer for those languages currently has no ready-made deterministic
  grammar to plug in. Phase 1 should scope Russian/Ukrainian ITN as "numbers and dates only,
  hand-written," not attempt full-coverage grammars.

## B. Intent / command detection

| Tier | Where it sits | Cost on our CPU | False-positive risk | Verdict |
|---|---|---|---|---|
| **Deterministic rules/grammar** (fixed trigger phrases, "literally X" escape) | First, always-on | Sub-millisecond string/regex match | Lowest — only fires on an exact, chosen phrase | **Recommended tier 0 for Phase 1**, and it is the *only* tier needed while D-0005 holds ("always resolves to literal dictation") |
| **Classical classifier** (logistic regression/SVM over TF-IDF or small embeddings) | Tier 1, only relevant once actions ship | Low single-digit ms | Real but boundable — needs an explicit confidence threshold and a reject-to-literal default | Reasonable next tier post-Checkpoint-1; no latency evidence gathered this session because it wasn't prioritized against the harder Windows/Rust questions above |
| **Small local transformer classifier** (BERT-class / small local LLM used as a classifier, not a generator) | Tier 2, escalation only | Tens of ms class, hardware-dependent; specific CPU numbers for our exact chip not found | Lower false-positive rate than tier 0/1 in principle, but adds real latency against the 50 ms p95 NLP budget | Only justified as an **escalation path for ambiguous cases**, never as the default path, given the budget |
| **Small local LLM (generative)** | Escalation-only, expensive tier | On CPU, reported edge-device decode throughput is single-digit-to-tens of tokens/sec for 1–4B models on non-server hardware (**PLAUSIBLE/SECONDARY**, general 2026 SLM surveys, not measured on our exact i5-12450H) | Highest capability, but generation-based "did the user mean a command" is the wrong shape for a system where a false positive executes something | **Do not use a generative LLM as the primary intent gate.** If used at all, restrict to classification-style constrained decoding, and only as a last-resort escalation |

**The asymmetry the brief calls out is the actual design constraint:** a false positive here
means an unintended action executes, not just a wrong transcript. That argues for a
**reject-to-literal default** at every tier — an intent detector should require to be
confident it's a command, not merely more-likely-than-not; when confidence is below
threshold, fall through to literal dictation. This is a direct analogue of D-0005's own
framing (intent layer always resolves to "literal dictation" until quality clears
Checkpoint 1) and of the architecture's correction-pass discipline in §5.5 (validate before
accepting, fall back silently on rejection) — the intent layer should use the identical
shape: propose, validate against a strict acceptance bar, silently fall back to literal.

**"Literal escape" mechanism — real, well-established prior art, from Talon Voice.**
Talon's community documentation (**VERIFIED**, fetched via search of `talon.wiki` and
`talonvoice.com` reference pages) describes exactly this pattern: saying **"escape"**
followed by words that would otherwise be interpreted as commands forces literal dictation
of those words (example given: *"escape press air"* dictates the literal text "press air"
rather than executing a "press" command), and separately, in command mode, "type", "literal",
or "say" are dictation-mode entry commands. **This directly validates the brief's proposed
"literal new paragraph" style escape hatch as an established, user-tested pattern**, not a
novel invention — Talon is the single strongest piece of prior art in this entire memo for
developer-facing voice command design, precisely because it targets the same user (a
developer dictating into code/terminal contexts) that Hermes targets. Recommend reading
Talon's command grammar and community package (`talonhub/community` on GitHub) directly
before designing Hermes's own grammar — it is the closest thing to prior art this space has.

**When to escalate:** no citable threshold was found for "escalate from cheap to expensive
tier at confidence X" specific to voice command detection; the general pattern in NLU
systems (reject/escalate below a confidence threshold, accept above it) is **UNVERIFIED**
as a specific number for this domain and would need to be tuned against Hermes's own
command set once one exists.

## C. Embeddings / semantic routing

| Model | Params | License | ONNX | MTEB retrieval (NDCG@10) | Notes |
|---|---|---|---|---|---|
| **`snowflake-arctic-embed-xs`** | 22M | **Apache-2.0** (**VERIFIED**, HF model card: "Arctic is licensed under the Apache-2," "available for commercial use at no cost") | **Yes** — ONNX weights present in the HF repo (**VERIFIED**, tag listing) | 50.15, beating `gte-tiny` (44.92) and `all-MiniLM-L6-v2` (41.95) per the model card (**VERIFIED**) | 384-dim. Best-evidenced small commercial-friendly candidate found this session |
| **`all-MiniLM-L6-v2`** | ~22M | Apache-2.0 (well known; not re-verified this session) | Widely available pre-exported | 41.95 (per Arctic's own card, above) | The long-standing default; strictly dominated by Arctic-XS per that same comparison table |
| **Model2Vec / `potion-base-*`** (MinishLab) | 2M/4M/8M/32M static | **MIT** (**VERIFIED** via GitHub README search) | N/A — not a transformer; there's a **`model2vec-rs`** native Rust crate (**PLAUSIBLE/SECONDARY**, repo exists: `MinishLab/model2vec-rs`) | `potion-base-32M` reaches "94.66% of the performance of all-MiniLM-L6-v2" (**PLAUSIBLE/SECONDARY**, project's own README claim) | **The most interesting option for the Rust-port seam**: a native Rust implementation means no ONNX/`ort` dependency at all for the routing embedding, if quality suffices. Claimed up to ~500x CPU speedup over a full transformer for the same job (**UNVERIFIED specific multiplier**, but static-embedding-vs-transformer speed advantage is architecturally sound) |

No per-query CPU latency number specific to our i5-12450H was found or measured for any of
these models this session — **flag as needing an actual local benchmark**, not a literature
number, before committing to one.

**Routing library: `aurelio-labs/semantic-router`.** MIT license, 365 stars, "past year of
commit activity," last update found 2026-08-24 (**PLAUSIBLE/SECONDARY**, from repo listing
metadata, not a direct commit-log fetch), so **actively maintained**, contrary to the
default assumption that these wrapper libraries rot fast. One security advisory
(CVE-2026-42208, a compromised transitive `litellm` pin) was patched — a sign of a
maintainer who responds, not a dealbreaker, but worth pinning dependencies carefully if
adopted. It is a Python library with LLM-provider integrations baked in; for Hermes's
narrower need (route an utterance against a small fixed set of command intents), a
hand-rolled cosine-similarity-against-precomputed-vectors routine is simpler, has zero
extra dependency surface, and is trivially portable to Rust later — **recommend not
adopting semantic-router itself**, but treating it as a reference implementation for the
routing logic shape (threshold + fallback + per-route score).

## D. NER / structured extraction

**Provisional conclusion: not worth adopting in Phase 1.** Reasoning, not just vibes:

- Under D-0005, no actions ship pre-Checkpoint-1, so there is currently no consumer for NER
  output at all — nothing downstream reads "this span is a PERSON/ORG/DATE."
- **GLiNER**: Apache-2.0 (**VERIFIED**, PyPI classifier), latest PyPI release `0.2.29`
  uploaded 2026-09-08 (**VERIFIED**, PyPI JSON API) — actively maintained, ONNX conversion
  path exists (`gliner2-rs`, `gliner2-onnx` on PyPI, community-maintained Rust/ONNX runners).
  A reported end-to-end latency of "~20 ms including tokenization on Apple-Silicon CPU with
  8 threads" surfaced in search results (**PLAUSIBLE/SECONDARY**, not independently
  benchmarked, wrong hardware class for our target anyway). Even if that number holds
  roughly on the i5-12450H, spending a meaningful fraction of the 50 ms p95 NLP budget on
  zero-shot entity typing that nothing consumes yet is not justified.
- **spaCy**: MIT license, Windows-supported, has a mature transformer pipeline
  (`spacy-transformers`) — but the PyPI JSON API shows the latest release as **`3.8.16`**
  (**VERIFIED** via direct PyPI JSON fetch; the fetch reported an upload timestamp in
  December 2024, which — if accurate — means spaCy has had **no headline release in over a
  year** as of 2026-09-26). That is a real maintenance-cadence flag for a project this deep
  into 2026; treat spaCy as **plausible but stale-by-the-numbers**, and re-check this exact
  number before relying on it, since a single JSON fetch parsing error can't be ruled out.
- What NER-shaped work this product actually needs — "is this span a project identifier,
  a file path, a command flag" — is better served by the deterministic vocabulary work in
  Section E (a known, closed, per-project list from tree-sitter/ctags/git) than by a general
  zero-shot entity model with no fixed label set. **Rules/hybrid wins here on evidence, not
  by default.**

**Revisit condition:** if/when actions ship post-Checkpoint-1 and need slot-filling from
free-form dictated text (e.g., "create a ticket for [X] assigned to [Y]"), GLiNER's
zero-shot label flexibility becomes actually relevant — re-evaluate then, not now.

## E. Project vocabulary extraction (W3)

| Tool | License | Windows | Speed/cost | Fit |
|---|---|---|---|---|
| **tree-sitter** | MIT (**VERIFIED** via search) | First-class, pure C core + Rust bindings, ships as a Rust crate | Incremental re-parse in sub-millisecond territory after an edit is the tool's entire design premise (**PLAUSIBLE/SECONDARY** — widely stated, not independently re-benchmarked this session); a **cold parse of a large repo is still a full first pass over every file**, which is the real cost to budget, not incremental updates | **Best fit for the Rust-native path** — grammars for essentially every mainstream language exist as separate crates (`tree-sitter-rust`, `tree-sitter-python`, etc.), each needs its own dependency pin |
| **universal-ctags** | GPL-2.0-or-later (**VERIFIED** via search) | Official CI-built Windows binaries: `universal-ctags/ctags-win32` publishes near-daily builds, latest found **`p6.2.20260920.0`, 2026-09-23** (**VERIFIED**, fetched release list) | Fast, single-pass, broad language coverage via regex-based parsers (less precise than tree-sitter, more languages "for free") | Good **fast bootstrap** tool for a cold index across many languages without writing/vendoring a tree-sitter grammar per language. **GPL license needs a legal read before bundling the binary in a commercial installer** — invoking an external GPL binary as a subprocess is a materially different exposure than statically linking a GPL library, but this project's own architecture-constraints section is explicit that licensing questions get a `DECISIONS.md` entry, and this is one |
| **LSP / existing editor indexes** | N/A | `workspace/symbol` is a real, standard LSP method that rust-analyzer (and presumably clangd, tsserver) implement and that returns name/kind/location from the server's own index rather than re-scanning files (**VERIFIED**, from rust-analyzer's own docs/source references) | Zero extra parsing cost **if** a language server is already running for the user's project | **Realistic only when a server is already up for other reasons (the user's editor), fragile otherwise**: Hermes would need to be a full LSP client, discover the right server binary and its socket/pipe, handle per-project server lifecycle, and per-language server differences (`workspace/symbol` search coverage limitations are documented even for rust-analyzer — e.g., it does not search dependency crates by default). **Not a Phase 1 dependency; a plausible Phase 2+ enrichment when an editor integration exists anyway** |
| **Filenames / path components / git metadata** | N/A | Trivial, `git log`/`git branch`/filesystem walk | Cheapest source of vocabulary; branch names and commit messages are exactly the kind of project-specific jargon (ticket prefixes, feature names) that generic models will never have | **Do this first** — it requires no parser at all and directly captures the "kube_system" / ticket-ID style vocabulary the brief calls out |

**Incremental refresh:** `notify` (crates.io, CC0-1.0, v9.0.0-rc.5, updated 2026-08-30,
**VERIFIED** via crates.io API — "Cross-platform filesystem notification library," 159M+
total downloads) wraps `ReadDirectoryChangesW` on Windows and is the standard choice; nothing
in this session's research surfaced a reason to hand-roll the Win32 call directly. Debounce
window, branch-switch cache invalidation, and cold-index cost on a large monorepo were **not
independently researched to primary sources this session** — flagged as unresolved below.

**Identifier splitting and expansion — there is real literature, not just intuition.**
Academic work on splitting/expanding source-code identifiers for exactly this kind of
downstream matching goes back over a decade: *"Recognizing Words from Source Code
Identifiers Using Speech Recognition Techniques"* applies speech-recognition-style dynamic
time warping to the identifier-splitting problem itself (**PLAUSIBLE/SECONDARY**, found via
search, abstract-level only, not fetched); *"Can Identifier Splitting Improve Open-Vocabulary
Language Model of Code?"* (arXiv 2201.01988) and *"Big Code != Big Vocabulary"* (arXiv
2003.07914) treat splitting camelCase/snake_case/abbreviations as a first-class open-
vocabulary modeling problem in the "big code" ML literature (**PLAUSIBLE/SECONDARY**,
titles/abstracts only — not read in full this session, budget did not allow). The practical
takeaway that's directly actionable without deeper reading: splitting is well-studied enough
that a rule-based splitter (camelCase/PascalCase/snake_case/SCREAMING_SNAKE_CASE/path and
namespace separators like `::`, `.`, `/`) covering the mechanical cases, plus a small
dictionary of common abbreviation expansions (`ctx`→"context", `cfg`→"config"), is a
reasonable, cheap, and precedented Phase 1 approach — a from-scratch open-vocabulary neural
splitter is academic-literature-grade effort disproportionate to what this product needs at
this stage.

## F. Contextual bias list limits

Building on R1 (TurboBias: 20K phrases at 2–5% RTFx cost; sherpa-onnx hotwords require
`modified_beam_search` + BPE modeling unit) — new evidence this session:

- **TurboBias's own abstract** states the framework holds up "even with a vast number of
  key phrases (up to 20K items)" (**VERIFIED**, quoted from the arXiv abstract page) —
  consistent with, not contradicting, R1.
- **BR-ASR** (arXiv 2505.19179, "Efficient and Scalable Bias Retrieval Framework"):
  *"when expanding the bias list to 200k where traditional methods generally fail, it
  induces only 0.3 / 2.9% absolute WER / B-WER degradation with a 99.99% pruning rate and
  only 20ms latency per query on test-other"* (**VERIFIED**, quoted directly from the
  abstract). Two things matter about this number: (1) it is measured on LibriSpeech
  test-other, a general-domain benchmark, not a code/CLI-identifier domain — treat the exact
  percentages as **illustrative of scaling behavior, not a number that transfers to our
  domain**; (2) the good result is explicitly *contingent on* a **99.99% pruning rate** —
  i.e., the system does not actually bias against all 200K entries per utterance, it
  retrieves a tiny relevant subset first. **This is the load-bearing fact for our design**:
  a large master vocabulary is fine, biasing the decoder against most of it per utterance is
  what causes degradation. The architecture should be "large static corpus, small dynamically
  retrieved active bias list," not "one flat growing hotword list."
- A second paper, "Lightweight Prompt Biasing for Contextualized End-to-End ASR Systems"
  (arXiv 2506.06252), reports relative EWER reductions of **30.7% with small entity lists**
  vs **18.0% with large entity lists** against a shallow-fusion baseline (**PLAUSIBLE/
  SECONDARY** — this number came from a search-engine synthesis of the paper, not a clean
  primary-source quote; a direct PDF-text fetch attempt failed to extract readable text in
  this session). Directionally it agrees with BR-ASR: **relative benefit shrinks as the list
  grows**, i.e. bigger unfiltered lists are worse, not better, per entity. Do not cite the
  exact 30.7%/18.0% figures without re-verifying against the actual paper text.
- **Documented over-biasing failure mode:** TurboBias itself reduces its boosting weight
  from 1 to 0.7 specifically "to avoid a large number of false accepts during decoding when
  testing with expanded context lists" (**PLAUSIBLE/SECONDARY**, from search synthesis of the
  paper, not a direct quote this session — but this is the same paper R1 already relied on,
  so treat as consistent with R1's existing citation). This is a direct, named instance of
  the "over-biasing inserts a boosted term that wasn't said" failure the brief asked about.
- **Dynamic/per-utterance active-subset selection is exactly what BR-ASR's pruning step and
  TurboBias's phrase tree are architecturally for** — this is not this project's invention,
  it is the standard shape of scalable contextual biasing in the current literature. What
  Hermes adds on top (per R1/R3/context) is *which signal selects the active subset*: the
  focused application, the open git repo, and recent dictation history, rather than a
  generic retrieval score. **No published system doing exactly per-application/per-project
  active-subset selection for a desktop dictation tool was found** — this remains this
  project's own contribution, not prior art we can cite.

## Recommended Phase 1 approach

Minimal, buildable inside the Python sidecar, with a clean seam to a later Rust port:

1. **ITN: hand-written rule/regex cascade in Python**, organized as ordered tagger→verbalizer
   passes mirroring NeMo-text-processing's *shape* (not its dependency) — numbers, dates,
   times, units, currencies, URLs/emails/paths as separate, independently testable rule
   modules. Gate the code/CLI-hostile rules (dash-flags, punctuation-as-symbols) behind the
   same per-application context signal the biasing system already reads. No pynini, no
   OpenFst, no conda. Port to Rust later as literal rule-for-rule translation — this is
   mechanical, unlike an FST toolchain migration would be.
2. **Intent detection: deterministic trigger-phrase matching only**, consistent with D-0005 —
   an explicit small grammar of exact command phrases plus a Talon-style "escape"/"literal"
   prefix that unconditionally forces literal dictation. No classifier, no embedding router,
   no LLM in Phase 1; there is nothing for them to gate yet.
3. **Embeddings: defer.** Nothing to route to yet under D-0005. When routing is needed,
   `snowflake-arctic-embed-xs` (Apache-2.0, ONNX-available, small) is the leading evaluated
   candidate; benchmark actual per-query latency on the i5-12450H before committing.
4. **NER: skip.** No consumer exists pre-Checkpoint-1; revisit if/when slot-filling for
   actions is designed.
5. **Project vocabulary: git metadata + filenames first (cheapest, zero-dependency), then
   ctags for fast multi-language bootstrap indexing** (flag the GPL licensing question to
   `DECISIONS.md` before shipping the binary), **tree-sitter per-language as a later
   precision upgrade** for the languages the user actually uses. Rule-based identifier
   splitter (case conventions + separator characters + a small abbreviation dictionary) to
   expand identifiers into spoken-form-matchable tokens.
6. **Bias list: large static per-project vocabulary, small per-utterance active subset**
   selected by focused-application + recent-context signals, consistent with both R1's
   TurboBias numbers and this session's BR-ASR/pruning finding. Do not feed the full project
   vocabulary to the decoder's hotword mechanism unfiltered.

## Deferred alternatives

- **Neural ITN models** (NeMo's non-WFST path) — revisit if the rule cascade shows a
  measurable coverage gap in eval data, weighed against the 50 ms p95 NLP budget.
- **`rustfst`-based ITN grammars** (own or via `ukrainian-itn` if it matures) — revisit at
  the Rust-port phase (Phase 3), and specifically re-check `ukrainian-itn`'s maturity before
  the Russian/Ukrainian code-switching work is scheduled.
- **GLiNER for slot extraction** — revisit once/if any action ships post-Checkpoint-1 and
  needs free-form field extraction from dictated text.
- **LSP-based vocabulary enrichment** — revisit once/if Hermes has an editor-integration
  surface where a language server is already guaranteed running.
- **`semantic-router` or similar routing libraries** — revisit only if the hand-rolled
  cosine-threshold router proves insufficient; keep the dependency footprint minimal until
  then.
- **Classifier/transformer/LLM intent tiers** — revisit only after D-0005's Checkpoint 1 is
  cleared and actions are actually being designed to ship.

## Unresolved questions

- **sherpa-onnx `rule_fsts`/`rule_fars`/`HomophoneReplacerConfig`** — could not confirm from
  primary docs in this session whether/how these relate to ITN-style rewriting; the fetched
  hotwords page did not surface them. Needs a direct source-tree read of sherpa-onnx's C++
  config structs.
- **Exact numbers in "Lightweight Prompt Biasing" (arXiv 2506.06252)** — PDF text extraction
  failed in this session; the 30.7%/18.0% EWER figures reported above are secondhand and
  should be re-verified before use in any decision document.
- **Russian ITN grammar/library** — no concrete Windows/Rust-relevant artifact found. Likely
  requires hand-written rules from scratch, scoped narrowly (numbers/dates only) for Phase 1.
- **spaCy's exact latest-release date** — the PyPI JSON fetch reported `3.8.16` uploaded
  December 2024, which would mean no release in ~21 months as of this writing; this is
  surprising enough (spaCy has historically been actively maintained) that it should be
  re-verified with a fresh, direct check rather than trusted from a single tool call.
- **Actual CPU latency, on our exact i5-12450H, for any embedding model, GLiNER, or a small
  local classifier/LLM** — every latency figure in Sections B–D above is from other hardware
  or general claims, not measured on our target machine. This needs local benchmarking, not
  more literature search, before any latency-budget decision is made.
- **Filesystem-watch debounce window, branch-switch invalidation strategy, and cold-index
  cost on a large monorepo** — not researched to primary sources this session; flagged in
  the brief as needed, not yet answered.
- **Per-app ITN aggressiveness dial** — confirmed as *not* attested prior art anywhere
  searched; this project would be originating it, which the lead should treat as a real
  product/UX design task, not a "known good pattern to implement."

## Decisions that should NOT yet be frozen

- **Do not freeze "no WFST/pynini anywhere in the toolchain, including build-time."** The
  runtime conclusion (no pynini/OpenFst in the shipped installer) is solid; whether an
  offline Linux/WSL build step compiling a WFST grammar to a portable artifact is worth the
  tooling complexity versus a hand-written rule cascade is a real trade-off the lead should
  make once the rule cascade's coverage is measured against F-WER, not decided from this
  memo alone.
- **Do not freeze the identifier-splitting approach as "rules only, forever."** The academic
  open-vocabulary-splitting literature (Section E) was only surveyed at the abstract level
  this session; if rule-based splitting shows real E-WER misses in eval, that literature
  deserves a deeper read before building a heavier solution.
- **Do not freeze a specific embedding model choice.** Arctic-embed-xs is the best-evidenced
  candidate on paper, but zero on-hardware latency numbers exist yet, and there is currently
  no consumer for routing under D-0005 — freezing now would be premature and not measured.
- **Do not freeze universal-ctags as a bundled dependency** without a `DECISIONS.md` entry
  addressing the GPL-2.0-or-later exposure of shipping its binary inside a commercial signed
  installer — this needs the same kind of direct legal read R5 flagged for the CUDA/cuDNN
  EULA question, not an assumption either way.
- **Do not freeze "per-application ITN aggressiveness dial" as a validated pattern** — it is
  this project's own hypothesis, not confirmed prior art, and should be tracked as a product
  bet with its own eval plan (F-WER by app-profile), not treated as settled design.

## Sources

- [Pynini < GRM < TWiki](https://www.openfst.org/twiki/bin/view/GRM/Pynini)
- [pynini conda-forge feedstock](https://github.com/conda-forge/pynini-feedstock)
- [OpenFstWin < Contrib < TWiki](https://www.openfst.org/twiki/bin/view/Contrib/OpenFstWin)
- [kkm000/openfst](https://github.com/kkm000/openfst), [jtrmal/openfst](https://github.com/jtrmal/openfst)
- [NVIDIA/NeMo-text-processing](https://github.com/NVIDIA/NeMo-text-processing)
- [NeMo WFST ITN docs (25.09)](https://docs.nvidia.com/nemo-framework/user-guide/25.09/nemotoolkit/nlp/text_normalization/wfst/intro.html)
- [rustfst on crates.io](https://crates.io/crates/rustfst) / [Garvys/rustfst on GitHub](https://github.com/Garvys/rustfst)
- [RustedBytes/ukrainian-itn](https://github.com/RustedBytes/ukrainian-itn)
- [notify crate](https://crates.io/crates/notify)
- [Talon community wiki — tips and tricks](https://talon.wiki/Customization/misc-tips/)
- [Talon default commands / voice-control reference](https://talonvoice.com/docs/reference/voice-control.html)
- [talonhub/community](https://github.com/talonhub/community)
- [Snowflake Arctic-Embed-XS model card](https://huggingface.co/Snowflake/snowflake-arctic-embed-xs)
- [MinishLab/model2vec](https://github.com/MinishLab/model2vec) / [model2vec-rs](https://github.com/MinishLab/model2vec-rs)
- [aurelio-labs/semantic-router](https://github.com/aurelio-labs/semantic-router)
- [GLiNER on PyPI](https://pypi.org/project/gliner/)
- [spaCy on PyPI (JSON API)](https://pypi.org/pypi/spacy/json)
- [tree-sitter](https://github.com/tree-sitter/tree-sitter) / [tree-sitter-rust](https://crates.io/crates/tree-sitter-rust)
- [universal-ctags/ctags-win32 releases](https://github.com/universal-ctags/ctags-win32/releases)
- [universal-ctags/ctags](https://github.com/universal-ctags/ctags)
- [rust-analyzer symbol_index.rs](https://github.com/rust-lang/rust-analyzer/blob/master/crates/ide-db/src/symbol_index.rs)
- [TurboBias abstract, arXiv 2508.07014](https://arxiv.org/abs/2508.07014)
- [BR-ASR abstract, arXiv 2505.19179](https://arxiv.org/abs/2505.19179)
- [Lightweight Prompt Biasing, arXiv 2506.06252](https://arxiv.org/abs/2506.06252) *(numbers unverified — extraction failed this session)*
- [Recognizing Words from Source Code Identifiers Using Speech Recognition Techniques (ResearchGate)](https://www.researchgate.net/publication/221569878_Recognizing_Words_from_Source_Code_Identifiers_Using_Speech_Recognition_Techniques)
- [Can Identifier Splitting Improve Open-Vocabulary Language Model of Code?, arXiv 2201.01988](https://arxiv.org/pdf/2201.01988)
- [Big Code != Big Vocabulary, arXiv 2003.07914](https://arxiv.org/pdf/2003.07914)
- [k2-fsa sherpa-onnx hotwords docs](https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html) *(rule_fsts/rule_fars/HomophoneReplacerConfig not confirmed here — unresolved)*
