# WING Feedback Watch — Windows prototype v0.2.0

Capture audio, investigate suspected ringing, and audition recordings. This is a diagnostic prototype, not a feedback classifier or suppression system. It does not change console gain, routing, EQ, faders, mutes or names.

## Updating an existing working installation

1. Close the old application and its command window.
2. Extract the new ZIP. Copy **all contents of its WingFeedbackMonitor folder** into your existing working WingFeedbackMonitor folder, replacing matching files. Keep the existing `.venv` folder. There are new Python modules; copying only app.py is insufficient.
3. Run **Start-Windows.cmd** in the working folder. Requirements are unchanged from v0.1.2, so an already working environment normally needs no reinstall.
4. Existing profiles, WAV recordings and JSON metadata remain under `%LOCALAPPDATA%\WingFeedbackWatch`. Earlier mono clips still open; they do not gain context audio retroactively.

For a fresh folder, install Python **3.13 or 3.12 Windows x86-64**, include the Python launcher, run **Install-Windows.cmd** once and wait for “Installation complete,” then run **Start-Windows.cmd**. Keep Python 3.15 alongside the supported version if desired. Each fresh extraction needs its own environment; reusing the working folder avoids that. If a package file is locked, close other copies and retry; a Windows restart releases lingering processes. The installer requires prebuilt packages and never asks you to install compilers.

This remains Python source plus Windows scripts. A standalone EXE/MSI is deferred. No service, scheduled task or background startup is installed. Closing the main window requests capture/playback shutdown, saves pending clips, waits for active ZIP exports, closes detached panels and exits. A stuck hardware driver or slow disk can delay shutdown; the window displays that it is closing.

## First run and all 48 inputs

Leave Demo enabled to test with generated audio. To capture hardware, stop, disable Demo, choose the installed audio device, set sample rate to match its current clock, and choose 1–48 input slots. ASIO generally exposes the full multichannel device; WDM/MME entries may expose fewer inputs. A selected profile does not install a driver or create routing:

- **WING USB:** manufacturer's Windows USB audio driver; patch the desired sends to USB manually on the console.
- **Dante:** Dante Virtual Soundcard or compatible hardware driver; patch in Dante Controller.
- **Waves SoundGrid:** Waves recording driver and host patching. SuperRack Performer alone does not supply a SoundGrid driver.

**Every configured input is analyzed, regardless of selected graph rows or open tabs.** Select 48 only when the actual driver exposes 48 inputs. Input slots are not automatically equivalent to WING strip numbers: stereo sources use two audio lanes, and patching can differ by event. Other software can hold drivers exclusively. ASIO startup/stop/close remains on the main thread; capture uses an input-only callback and background analysis.

## Earlier detection and multiple peaks

The detector now follows up to **eight candidate spectral peaks per input**, rather than assigning the channel to its loudest peak. It uses a 4096-sample Hann-window FFT with a 1024-sample hop, so windows overlap by 75%. Peaks are ranked by prominence and tracked independently. This is a bounded heuristic and can still miss peaks outside the tracked set.

Starting settings for a fresh profile:

| Local setting | Default |
| --- | --- |
| Minimum tone level | -75 dBFS |
| Peak prominence | 12 dB |
| Early candidate persistence | 0.18 seconds |
| Persistent ringing persistence | 0.45 seconds |
| Brief-gap tolerance | 0.10 seconds |

Old profiles retain their saved thresholds. Stop capture to change analysis settings and click **Save source profile** to retain them. Early persistence must be no longer than persistent persistence. Missing observations within the gap allowance preserve a track without counting the missing time toward persistence. Excessive frequency drift resets persistence. Alert cooldown is tracked per frequency and flag type for eight seconds; a different frequency on the same input can flag immediately. An unchanged continuous track emits each flag type once, rather than repeatedly alerting throughout a sustained tone.

At 48 kHz, FFT spacing is about 11.7 Hz and analyses occur about every 21 ms. The initial FFT needs about 85 ms of audio. Default flags therefore require roughly a quarter second of consistently detectable tone for an early candidate and over half a second for persistent ringing, before driver/GUI delays. Lower levels do not guarantee faster or pre-audible detection.

Growth, frequency spread, observed duration and emergence over a background estimate are stored with flags and displayed in review. Growth is evidence for inspection, not a required condition. The two labels describe persistence, not a calibrated probability of feedback. The “ringing score” is progress toward persistent duration, not confidence.

**Experimental learned-background requirement** is optional and off by default. When enabled, it learns for 1.5 seconds after startup, then requires a peak to be at least 6 dB above its slowly adapting bin baseline. Start with representative background and no ringing. It may hide a tone already present at startup or one that grows very slowly. After an audio gap the baseline and tracks restart; cooldown history is retained.

Speech harmonics, sustained singing, instruments and whistles can trigger either label. Moving tones may also occasionally qualify. Detection cannot prove an acoustic loop or identify the initiating microphone when multiple microphones hear the same ringing. Do not intentionally provoke PA feedback for testing; use recordings and normal rehearsal operation.

## Flag windows and multiple displays

**Connection** has separate “Pop up early candidates” and “Pop up persistent ringing” toggles, plus buttons to open each history window manually. Early popups start off; persistent popups start on. The windows are nonmodal and do not pause analysis. Incoming flags show time, input/name, frequency and tone level before post-roll has finished. Double-click a flag to open its clip after saving. Up to 500 rows are retained per flag window; the flag CSV covers the latest 2000 flags in the current app run. Old flags remain in their saved clip JSON, but do not populate the current-run windows automatically.

In **Live monitor**, Ctrl/Shift-click input rows to overlay up to eight live spectra and RMS histories. All configured inputs, including nonselected rows, continue to be analyzed. All-input level rows remain visible through the scrollable table.

Use **Detach current tab** on the toolbar to move Live monitor, Detection review, Analytics or Names/mapping into a separate window for another screen. Close a detached window to reattach it, or choose **Reattach all tabs**. Connection stays in the main window. Closing a detached window does not stop capture; closing the main window shuts down the application. Window positions/layouts are not persisted yet.

## Recorded clips and hearing the entire context

Default recordings retain five seconds before and after a flag; each is adjustable from 1–10 seconds. The trigger marks the first flag, not necessarily tone onset. Early startup clips may have less pre-roll. Stopping or an audio gap flushes available post-roll and marks partial/gap metadata.

A recording has:

- `ID.wav`: original, unnormalized mono audio for the flagged input.
- `ID.mix.wav`: optional synchronized context audio, the **arithmetic mean of all monitored inputs**, saved when “Record all-input context mix” is enabled.
- `ID.json`: clip metadata plus all flags grouped into that recording.

The context mix is not the WING main mix. It does not reflect console fader positions, bus processing or panning and may be much quieter than an individual mic. It can contain feeds from channels not audible in the PA. Only the mono context mix is retained; it is not a full multitrack recording. At 48 kHz, a 10-second float mono WAV is about 1.9 MB; the input plus context pair is about 3.8 MB per clip. No automatic deletion or upload is performed.

Multiple frequencies and both flag types on the same input share a clip while that input's post-roll is already being collected. Later flags are stored in its frequency selector; they do not extend post-roll. New flags still appear in the flag windows even when the session recording limit is reached. Default allowance is 200 clips per capture session. Recording backlog is bounded; dropped clips/backlog warnings do not intentionally stop analysis. A flag whose clip fails to save may remain marked “collecting”; the main status reports the save error. Starting a new capture resets the clip allowance.

In **Detection review**:

1. Select the saved clip and choose an individual flag/frequency from its selector.
2. Choose **Flagged input only** or **All monitored inputs together**.
3. Choose **Full clip**, **Selected band**, or **Band removed**. Full clip plays the entire unfiltered time window for the selected source. Band controls affect only local replay/export.
4. Choose a separate local headphone output, then click **Play clip**. Playback never starts automatically.

The review graphs always show the flagged input; the source selector changes listening/export only. Playback restarts at the beginning when Play is clicked; there is no continuous A/B switch or scrub transport. Isolated bands are not normalized. Default attenuation is -18 dB. Known console/network/ASIO/virtual output names are excluded, but software cannot prove physical wiring: verify the chosen device goes to headphones. Capture/replay driver sharing and concurrent separate outputs still need checking on the event PC.

## Read-only WING names and local overrides

On **Names / mapping**, enter the console IPv4 address and click **Fetch names (read only)**. The application sends only a fixed allowlist of argument-free OSC name queries over UDP port 2223: `/ch/1..40/$name`, `/aux/1..8/$name`, with `/name` fallbacks when no reply was received. Replies are accepted only from the entered IP/port and known name addresses. There are no generic OSC send functions, setters, subscriptions, wildcard queries, fader requests or routing changes. Name import is optional and not required for audio analysis.

The table provides 48 audio slots mapped to 40 channel strips and eight aux strips. Those initial assignments are suggestions, **not discovered audio routing**. Set each slot's mapped strip according to the real USB/Dante/SoundGrid patch; use Unmapped where appropriate. Check the mapping verification box before imported names are used. Put any preferred name in **Local override**, or edit the Live monitor name while stopped. Overrides take precedence, survive a console-name refresh, and never leave the app as writes. Save the source profile to retain names/mappings. Historical clips keep the names they had when captured.

Imports are manual snapshots rather than continuous console synchronization. Inaccessible/locked OSC, network filtering or firmware differences can prevent replies; partial imports report the received count. Actual console name retrieval remains unverified on physical WING hardware in this release.

## Charts and exports

The **Export…** toolbar menu provides:

- Loaded-clip **CSV** and complete **JSON** metadata (up to 500 loaded clips).
- Current-run **flag CSV**, including both types, per-frequency evidence and clip IDs (latest 2000 flags).
- Selected audio **float WAV** using the chosen input/context source and full/band/band-removed filter, without playback attenuation.
- Background **ZIP export** of loaded input/context WAVs, clip metadata and current-run flag log, with relative audio paths.
- **PNG or SVG** export of an individual graph: live spectrum, levels, waveform, clip spectrum, spectrogram, clips by input, frequency histogram, timeline, flag-type counts or input/frequency heatmap.

Analytics count saved clips, not confirmed feedback incidents or acoustic severity. A shared clip can contain multiple flags; the clip table, histogram and timeline use its first flag's frequency, and the type chart uses its highest flag type. Demo and live clips are included; the timeline colors identify them. The heatmap counts each frequency bin flagged within a clip once for that input, so secondary frequencies are included. The clip frequency selector and JSON/flag CSV expose the other frequencies. CSV text cells are protected against formula interpretation. Exports may contain recorded speech, local device labels and names.

## Validation and remaining checks

The release passes 25 automated tests plus the offscreen Qt demo integration check. Automated tests cover quiet simultaneous peaks under louder changing tones; both flag types; per-frequency cooldown; brief gaps; moving-tone stability; 48-input detection; ring buffering; noise/short-tone rejection; band isolation/reconstruction; main-thread driver lifecycle/restart/failure cleanup; callback overflow; argument-free allowlisted name queries/parser rejection; legacy clips; local override persistence; detached-panel reattachment; incoming clips preserving the current review; mixed-context audition/WAV export; PNG/SVG and ZIP exports.

An offscreen Qt demo integration run covers both real-time flag windows, synchronized input/context WAVs, saved metadata, review during continued analysis, detached live/analytics panels, and main-window close/flush. A synthetic 48-input detector benchmark processed 1.49 seconds of audio in approximately 0.7–1.0 seconds on this machine; this is not a sustained Windows/driver/performance guarantee.

Still unverified: this release's physical WING USB/Dante/SoundGrid operation, console OSC names, actual headphone playback, long-duration 48-channel capture/recording, and real-world false-positive/false-negative rates. Match thresholds to rehearsal recordings.

Run tests from this folder with `.venv\Scripts\python.exe -m unittest discover -v`.

Protocol reference: Behringer-hosted [WING Remote Protocols FW 3.1](https://cdn.mediavalet.com/aunsw/musictribe/XMBvOXMlIUC8kWwelBIOpg/NFeKk1IPIkiPCjtv1L-YVQ/Original/WING%20Remote%20Protocols%20FW%203.1.pdf).
