# 01 — Strategy

Status: draft, 2026-09-24. Revisit after Phase 1 ships.

## 1. The honest starting position

In August 2026 Wispr raised **$280M at a $2B valuation** (total raised $361M), on an
estimated $15–35M ARR growing >150% QoQ, claiming millions of consumers and 100k
businesses. Menlo led.

Read that as two facts, not one:

- **Good:** the market is real and validated. People pay for dictation. Two years ago
  that was an open question.
- **Bad:** a general-purpose, cross-platform, cloud-first dictation app is now a funded
  land grab. You cannot win that race on marketing spend, model budget, or headcount.
  Anyone who tells you to "build a better Wispr Flow" is describing a way to lose slowly.

The only viable posture is a **wedge**: a segment the incumbent structurally will not
serve well, where being small is an advantage, and where a beachhead can compound into
something larger.

## 2. Competitive map

| Product | Platform | Inference | Price | Positioning |
|---|---|---|---|---|
| **Wispr Flow** | Mac, Win, iOS, Android | Cloud | ~$12–15/mo | Category leader, expanding into meetings/notes |
| **Superwhisper** | macOS, iOS | On-device + optional cloud | one-time + sub | The privacy/local choice; strongest local UX |
| **MacWhisper** | macOS | On-device | one-time | Prosumer, file transcription heavy |
| **VoiceInk** | macOS | On-device | open source | OSS local dictation |
| **Handy** | Cross-platform | On-device | open source | OSS, minimal, developer-adjacent |
| **Spokenly** | Mac, Win | Local Whisper + BYO-key cloud | freemium | Free local tier on Windows |
| **Aqua Voice** | Mac, Win | Cloud | sub | Speed-focused, "voice-first editing" |
| **Willow, Typeless, Amical, Voicy, VoiceDash** | mixed | mostly cloud | sub | Fast-follower cluster |
| **Windows Voice Access / Dictation** | Windows | On-device | free, bundled | The baseline everyone ignores because it's mediocre |
| **macOS Dictation** | macOS | On-device | free, bundled | Good enough that Mac users need a *reason* to pay |

**Pattern:** the good local-first products are macOS-only. The cross-platform products are
cloud-first. Nearly all are English-first and optimized for writers, not for people whose
day is spent in a terminal, an IDE, and a design tool.

## 3. The wedge

Four candidate differentiators. **Pick two to be world-class at; be merely competent at the rest.**

### W1. Windows, done properly — including the places everyone else fails
Windows has the weakest native dictation and the weakest third-party local options. The
hardest technical problem on Windows is **text delivery**: `SendInput` silently no-ops in
many Electron apps, UI Automation is inconsistent in Chromium, and **UIPI blocks injection
into elevated processes entirely** — so dictating into an admin PowerShell or an elevated
terminal simply doesn't work in competing products. Solving that cascade reliably is
unglamorous, hard, and exactly the kind of thing a funded consumer company deprioritizes.
See `02-architecture.md` §6.

### W2. Accent and code-switching robustness, measured and published
This is the largest underserved population in the category and the one you personally
represent: **non-native English speakers writing English**, often mixing in words from
their L1 mid-sentence. Every incumbent is tuned on American English and degrades on
accented speech; none of them publish accent-stratified numbers.

The move is not "we're good at accents" as a claim. It's: build a public, reproducible
**accent-stratified benchmark** (EdAcc, Common Voice by L1, FLEURS, plus a proprietary
code-switching set), publish your numbers *and your competitors'*, and let the benchmark
be the marketing. Benchmarks that a community adopts become a moat that funding can't buy.

### W3. Project-aware vocabulary for technical users
Generic dictation cannot spell `useMemo`, `kubectl`, `tokio::sync::mpsc`, or your
colleague's surname. Hermes can, because it reads context the cloud never sees: the active
window, the focused field's existing text, the clipboard, and **the identifiers in the git
repo you currently have open**. This is contextual biasing (§`02-architecture.md` §5.4) and
it is only possible *because* we run locally. Privacy isn't just a compliance story here —
it's what unlocks the accuracy feature.

### W4. Genuinely offline
Sells into legal, medical, defense, finance, and the EU public sector, where cloud
dictation is a non-starter. Low volume, high ACV, slow sales cycle. Not the beachhead, but
the reason the beachhead is valuable later.

**Recommendation:** lead with **W1 + W3** (Windows developers/technical professionals),
because that audience can be reached without a marketing budget and will tolerate a rough
v0.1 in exchange for capability. Build **W2** in parallel as the public benchmark — it is
your credibility and your PR. **W4** is the enterprise motion in year two.

## 4. Positioning statement (draft)

> For developers and technical professionals on Windows who think faster than they type,
> Hermes is a local-first dictation service that understands your code, your terminal, and
> your accent. Unlike cloud dictation tools, it works offline, in elevated terminals, and
> on the vocabulary of the project you actually have open.

Test this against real users before believing it. `The Mom Test` rules apply: never ask
"would you use this?"

## 5. Business model

Open core. This is the correct answer when competing with a company that has 100x your
capital: give away the thing they sell, monetize what they can't be bothered to.

| Tier | Price | Contents |
|---|---|---|
| **Core (OSS, free)** | $0 | Local engine, all models, hotkey, injection, per-app profiles. Apache-2.0 or AGPL — see below. |
| **Pro** | ~$10–12/mo | Cloud accuracy tier for hard audio, cross-device sync of dictionary + profiles, translation, correction-learning history, priority models |
| **Team** | ~$20/user/mo | Shared team vocabulary (product names, people, repos), admin policy, SSO |
| **Enterprise / On-prem** | annual contract | Air-gapped deployment, audit logging, compliance attestations, support SLA |
| **SDK / API** | usage | The engine embedded in other people's apps (IDEs, CAD tools, medical software) |

**Licensing note:** AGPL for the core deters a well-funded competitor from absorbing your
work while still allowing individual use and inspection; Apache-2.0 maximizes adoption and
contribution. Given W2's benchmark-as-marketing strategy depends on adoption, lean
**Apache-2.0 for the benchmark and evaluation harness, AGPL for the engine**, with a CLA
so you retain relicensing freedom.

**Do not** build billing, accounts, or sync before Phase 3. They are a distraction from the
only question that matters early: *is the transcription good enough that you personally
stop typing?*

## 6. Sequencing of the go-to-market

1. **You are user zero.** The product is done when you dictate this document. If you don't
   use it daily, nobody will.
2. **Publish the benchmark before the product.** An accent-stratified ASR benchmark with
   honest numbers for every competitor is a linkable, citable artifact that costs no
   marketing spend and establishes authority. It also forces you to build the evaluation
   harness, which you need anyway (`05-evaluation.md`).
3. **Ship the OSS core to r/LocalLLaMA, HN, and the Windows dev community.** This audience
   is small, vocal, allergic to cloud, and generates the bug reports that make injection
   reliable.
4. **Only then** add Pro. Monetize once retention is proven, not before.

## 7. Risks, honestly stated

| Risk | Severity | Mitigation |
|---|---|---|
| OS vendors bundle this for free (Apple, Microsoft, Google all shipping better native dictation) | **Existential** | Be where the OS won't go: cross-app context, project vocabulary, offline enterprise, accents. Bundled features are always generic. |
| Wispr or a fast-follower ships good Windows local support | High | Speed on the wedge; the benchmark as a defensible brand; OSS community as a cost structure they can't match |
| Frontier ASR becomes so good and so cheap that accuracy stops being a differentiator | High | Then the product is *injection, context, and UX*, not the model. Architect so the model is swappable (§`02-architecture.md` §5.1) and the value lives in the layers around it. |
| Local models can't match cloud on hard audio | Medium | Hybrid escalation path, opt-in. Be honest in the UI about which tier ran. |
| Solo-founder bandwidth vs. a 100-person competitor | High | Scope brutally. Two differentiators, one platform, one audience. |
| Name collision — "Hermes" is used by Nous Research's LLM series, Meta's JS engine, and a luxury brand | Low but real | Fine as an internal codename. Do a trademark search before any public launch. |

## 8. What would make this *not* worth building

Be willing to reach this conclusion:

- If, after Phase 1, your own measured WER on your own voice in your own apps isn't
  materially better than Windows' built-in dictation *and* your latency isn't under ~500ms,
  the technical wedge isn't there.
- If you build it and don't use it daily for a month, the product thesis is wrong.
- If accent-stratified benchmarking shows the gap between local and cloud models on
  accented speech is small, W2 collapses and you need a different second differentiator.

Set these as explicit checkpoints in `03-roadmap.md`, not as vibes.

## Sources

- [Wispr raises $280M at $2B valuation — TechCrunch](https://techcrunch.com/2026/08/17/wispr-raises-280m-at-2b-valuation-as-it-looks-beyond-dictation/)
- [Wispr's $2B valuation — Fortune](https://fortune.com/2026/08/17/wispr-2-billion-valuation-dictations-only-the-beginning/)
- [Wispr Flow revenue estimates — Latka](https://getlatka.com/companies/wisprflow.ai)
- [Best dictation apps for Windows 2026 — VoiceInk](https://tryvoiceink.com/best-dictation-apps-windows)
- [Wispr Flow alternatives 2026 — Voicy](https://usevoicy.com/blog/wispr-flow-alternatives)
- [Wispr Flow vs Superwhisper vs MacWhisper — Spokenly](https://spokenly.app/blog/wispr-flow-vs-superwhisper-vs-macwhisper)
