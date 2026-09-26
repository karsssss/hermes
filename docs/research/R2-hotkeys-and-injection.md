# R2 — Global hotkeys & text injection on Windows

Research landed 2026-09-24. Crate versions from the crates.io JSON API, repo activity from
the GitHub API. Items marked **unverified** must not be treated as fact.

## Headline findings

1. **`tauri-plugin-global-shortcut` cannot do proper push-to-talk.** It wraps
   `RegisterHotKey` and *fakes* key-release by polling `GetAsyncKeyState` every 50 ms.
2. **Injection success is not verifiable in general.** Design around it rather than
   pretending otherwise.
3. **`uiAccess` is the real answer to elevated windows** — and it dictates our installer,
   signing, and distribution from day one.

## A. Hotkeys

### Mechanism comparison

| Capability | `RegisterHotKey` | `WH_KEYBOARD_LL` | Raw Input |
|---|---|---|---|
| Distinct keydown **and** keyup | **No** | **Yes** | **Yes** |
| Modifier-only chord (RAlt alone, L vs R Ctrl) | **No** | **Yes** (`vkCode` gives `VK_LCONTROL`/`VK_RCONTROL`/`VK_RMENU`) | **Yes** |
| Suppress the key | Implicitly | **Yes** (return non-zero) | **No** |
| Background delivery | Yes | Yes | Yes, with `RIDEV_INPUTSINK` |
| Needs message pump | Yes | **Yes, mandatory** | Yes |
| Robustness risk | Low | **High** (silent removal) | Low |

Push-to-talk needs keyup and modifier-only chords. **Only the low-level hook provides
both.** Microsoft nevertheless recommends Raw Input over LL hooks for monitoring.

### The LL-hook footgun (quoted from Microsoft)

> "The thread that installed the hook must have a message loop."

> "If the hook procedure times out, the system passes the message to the next hook.
> However, **on Windows 7 and later, the hook is silently removed without being called.
> There is no way for the application to know whether the hook is removed.**"

> "Windows 10 version 1709 and later: the maximum timeout value the system allows is
> 1000 milliseconds."

**Correction to a common belief:** the often-cited 300 ms `LowLevelHooksTimeout` default is
**not in Microsoft's documentation** — only the 1000 ms cap is. Treat 300 ms as folklore and
design for a sub-millisecond callback regardless.

**Mandatory design.** Dedicated thread → `SetWindowsHookEx` → `GetMessage` pump. The
callback does *only*: read `KBDLLHOOKSTRUCT`, `try_send` on a bounded non-blocking channel,
`CallNextHookEx`, return. No allocation, no locks, no logging, no IPC to the WebView
thread. Target under 100 microseconds. **Add a watchdog** — because removal is silent, we
must periodically verify liveness and reinstall. Note also that `GetAsyncKeyState` is
unreliable inside the callback (it runs before async key state updates).

### The push-to-talk finding

`global-hotkey` (and therefore `tauri-plugin-global-shortcut`) uses `RegisterHotKey` and
spawns a thread per keypress polling `GetAsyncKeyState` every 50 ms to synthesise
`Released`.

- Up to **~50 ms release latency**; only the main VK is polled, not modifiers.
- **The 50 ms sleep is new in 0.8.0.** In version 0.7.0 and earlier this was a **tight spin
  loop burning a full CPU core for the entire hold duration** — exactly the PTT pathology.
  (PR #178.)
- If we use the plugin at all, **pin `tauri-plugin-global-shortcut` >= 2.3.2**, whose
  changelog reads *"fix cpu usage while pressing the keys on windows"*.
- `MOD_NOREPEAT` is always set, so no auto-repeat spam. Good.

### Crate verdicts

| Crate | Version | Released | Verdict |
|---|---|---|---|
| `uiautomation` | **0.25.1** | 2026-09-04 | **Best-maintained crate in this report.** 0 open issues, Apache-2.0 |
| `global-hotkey` | 0.8.0 | 2026-05-01 | Maintained (Tauri org), but `RegisterHotKey` semantics |
| `tauri-plugin-global-shortcut` | 2.3.2 | 2026-05-28 | Maintained; **pin >= 2.3.2** |
| `clipboard-win` | 5.4.1 | 2025-07-17 | **Use this** — only one with raw format access |
| `clipboard-rs` | 0.3.5 | 2026-06-30 | Newest, most active; worth evaluating |
| `arboard` | 3.6.1 | 2025-08-23 | Maintained but high-level only; no raw formats |
| `windows` | 0.62.2 | 2025-10-06 | Repo very active, **crate release stalled ~11.5 months**; `master` is 0.100.0 with renamed features. Pin 0.62.2, expect a breaking migration |
| `enigo` | 0.6.1 | 2025-08-28 | Repo active, **no release ~13 months**; buys nothing here |
| `win-hotkeys` | 0.5.1 | 2025-05-17 | Hook-based, tracks press *and* release. Quiet but **right shape — read it** |
| `keytap` | 0.4.0 | 2026-04-24 | Unproven, but scope is exactly right. Read it |
| `rdev` | 0.5.3 | **2023-06-26** | **Abandoned** (3+ years, no release) |
| `device_query` | 4.0.1 | 2025-07-21 | **Abandoned — GitHub repo ARCHIVED** |
| `inputbot` | 0.6.0 | 2023-08-17 | **Unmaintained** |
| `livesplit-hotkey` | 0.8.1 | 2026-06-15 | Maintained but **callback is `FnMut()` — no press/release** |
| `win-text-inject` | 0.1.1 | 2026-07-22 | **111 total downloads.** Read for ideas, do not depend |

## B. Text injection

### UI Automation is the wrong tool for our main path

Microsoft, verbatim:

> "**Elements that support TextPattern do not support ValuePattern and TextPattern does not
> support setting the text of multi-line edit or document controls. For this reason, text
> input must be simulated.**"

- Works: single-line Win32 `EDIT`, WinForms/WPF `TextBox`, many search/address bars.
- Fails: multi-line editors, documents, RichEdit, Office bodies, terminals, most
  contenteditable.
- Chrome/Electron: unreliable, can partially apply and leave garbage.
- **Fatal semantic mismatch: `SetValue` replaces the entire control contents.** Dictation
  needs *insertion at the caret*. Read-splice-write is racy, destroys undo history, and
  breaks IME composition.

**Gap:** the `uiautomation` crate does **not** wrap `IUIAutomationTextPattern2::GetCaretRange`
(Win8+), which is the single most useful API for caret-anchored insertion. Drop to raw
`windows-rs` (`Win32::UI::Accessibility`) for it.

**Revised role for UIA: inspection, not insertion.** Use it to identify the focused element,
control type, `IsEnabled`, `IsKeyboardFocusable`, and owning-process integrity level — to
*choose* a strategy and to refuse with a clear message rather than silently drop.

### Clipboard snapshot/restore is not fully solvable

Six reasons, from Microsoft's Clipboard Operations docs:

1. **Delayed rendering.** Owners may `SetClipboardData(fmt, NULL)`. Our `GetClipboardData`
   triggers a **synchronous `WM_RENDERFORMAT` in the owner process** — a hung owner hangs
   *us*, and enumerating to snapshot **forces materialization of every lazy format**,
   turning a 4-byte promise into a 200 MB Photoshop DIB.
2. `CF_OWNERDISPLAY` has no snapshottable payload. Unrecoverable.
3. Private formats have owner-internal semantics; copying bytes may restore a dangling handle.
4. Restoring makes *us* the owner; `EmptyClipboard` sends `WM_DESTROYCLIPBOARD` to the
   original owner, which may free the very resources we are restoring.
5. `OpenClipboard` is a **single global lock**. Another app will beat us to it.
   **Retry with exponential backoff is mandatory** — espanso has none, a known source of
   silent failures.
6. **Clipboard History / Cloud Clipboard will capture our transient dictation text** unless
   we register and set `ExcludeClipboardContentFromMonitorProcessing`,
   `CanIncludeInClipboardHistory` (0), `CanUploadToCloudClipboard` (0). Only reachable via
   `clipboard_win::raw::register_format`. **This is a privacy requirement for a dictation
   app, not an optimization.**

**Practical rule:** snapshot only `CF_UNICODETEXT`, `CF_HDROP`, `CF_DIB`/`CF_DIBV5`, and
registered HTML/RTF. Accept lossiness elsewhere and document it.

**Steal espanso's timing constants:** `pre_paste_delay` 300 ms, `restore_clipboard_delay`
300 ms, `clipboard_threshold` 100 chars (switch from keystrokes to clipboard above this).

### SendInput with KEYEVENTF_UNICODE

- `wVk` must be 0; `wScan` holds the UTF-16 code unit; combinable only with `KEYEVENTF_KEYUP`.
- The system synthesizes `VK_PACKET`; `TranslateMessage` posts `WM_CHAR`.
- **Silent mojibake warning, verbatim:** *"This Unicode character will automatically be
  converted to the appropriate ANSI value if it is posted to an ANSI window."*
- **Surrogate pairs:** no non-BMP path — send two UTF-16 code units, **adjacent within a
  single `SendInput` batch**. espanso batches the whole string into one call.
- **Ignored by anything reading Raw Input/DirectInput** rather than running
  `TranslateMessage` — most games, and anti-cheat filtering on `LLKHF_INJECTED`.
- **Sanitize modifiers first.** If the user is still holding the PTT modifier (e.g. RAlt),
  our injected `V` becomes AltGr+V. Release and restore physical modifier state around
  injection.

Use raw `windows-rs` `SendInput`, not `enigo` — the cross-platform abstraction costs
control over batching and surrogate pairing and buys nothing here.

### Verification: the honest answer is you cannot

| Method | Reliability |
|---|---|
| `ValuePattern.CurrentValue` readback | Only where ValuePattern exists — the minority case, and where failure was least likely anyway |
| `TextPattern` `GetText` | Cross-process COM, 10s-100s of ms, frequently stale in Chromium/Electron. High false-negative rate |
| `WM_GETTEXT` | Win32-only, blocked by UIPI for elevated targets, useless for Chrome/Electron/UWP |
| Clipboard comparison | Proves we set the clipboard, not that the target pasted |
| UIA `TextChanged` event | Best available *signal*, but advisory and not universally raised |

**This contradicts the plan recorded in `ARCHITECTURE.md` section 6.1 and in `CLAUDE.md`,
both of which assume read-back verification.** Both must be corrected.

**Replacement approach — check preconditions, not postconditions:**

1. Before injecting: foreground HWND stable, target integrity level <= ours, focused
   element `IsEnabled && IsKeyboardFocusable`, not a password field.
2. Make every injection **idempotent and undoable** — one utterance = one atomic insert the
   user can Ctrl+Z.
3. Keep recognized text in our own history UI so a silent failure is recoverable.
4. **Never report success we did not observe.** Detecting "target is elevated and I am not"
   *before* injecting, and saying so, beats a silent drop.

### UIPI — what real apps do

| App | Approach |
|---|---|
| **espanso** | **Nothing.** Issues #1576 (open since 2023-03-31) and #2388 (2025-07-18). Users must run as admin. Structural, unfixed for 3.5 years |
| **PowerToys** | Runs elevated on demand, with an explicit security caveat |
| **AutoHotkey** | **uiAccess** — ships `AutoHotkey64_UIA.exe`, requires install under Program Files. The most sophisticated answer in the ecosystem |
| Talon, Dragon | **Unverified** |

**uiAccess requirements (verified):** the policy "Only elevate UIAccess applications that
are installed in secure locations" is **Enabled by default**. Secure locations are exactly
`%ProgramFiles%`, `%ProgramFiles(x86)%`, and `%SystemRoot%\system32\`. And:

> "**Windows enforces a digital signature check on any interactive apps that request to run
> with a UIAccess integrity level regardless of the state of this setting.**"

So uiAccess requires: **Authenticode signing (non-negotiable) + `uiAccess="true"` with
`requestedExecutionLevel level="asInvoker"` + a per-machine installer into Program Files.**
That **kills MSIX and user-local install.**

Nothing fires on the secure desktop (UAC prompts, Ctrl+Alt+Del) — it is a separate desktop
object, and the Secure Attention Sequence is not interceptable by design.

## Recommendations

**Hotkeys — two tiers.** Tier 1: our own `WH_KEYBOARD_LL` on a dedicated thread, with a
silent-unhook watchdog. This is the only option giving true keyup, modifier-only chords, and
suppression. Read `win-hotkeys` 0.5.1 and `keytap` 0.4.0 as reference implementations.
Tier 2: `RegisterHotKey` via `global-hotkey` 0.8.0 as a conventional-chord fallback.

**Injection — three-strategy cascade**, chosen per target:

1. **Clipboard + Ctrl+V** — primary for anything over ~100 chars and for
   terminals/Office/Electron. Use `clipboard-win` 5.4.1 for raw formats and the privacy
   formats. Retry `OpenClipboard` with backoff.
2. **`SendInput` + `KEYEVENTF_UNICODE`** via raw `windows-rs` — short inserts, and where
   clipboard is unacceptable. One batch per utterance. Sanitize held modifiers.
3. **UIA `ValuePattern.SetValue`** — narrow opportunistic path only (single-line,
   ValuePattern-supporting, currently empty). **Not the main path.**

**Elevation — decide early, it shapes the installer.** Given this is genuinely an
accessibility-class application, **plan for `uiAccess`** and ship detect-and-warn in v1.
**Budget for a code-signing certificate and a Program Files MSI from day one** — retrofitting
means rebuilding the entire distribution pipeline.

## Unverified

- Whether `RegisterHotKey` fires when an elevated window has focus. **No authoritative
  Microsoft statement found.** Test empirically — this is cheap and decides Tier 2's value.
- Whether Raw Input with `RIDEV_INPUTSINK` sees keystrokes destined for elevated windows.
  If it does, it is a better Tier 2 than `RegisterHotKey`.
- Talon's and Dragon's actual strategies.
- The 300 ms `LowLevelHooksTimeout` default (not in MS docs; only the 1000 ms cap is).
