# Marketing media runtime

Pinned HyperFrames 0.8.119, GSAP 3.14.2 and ffprobe 5.2.0 support local draft rendering. Install with `npm ci` in `/home/agency/tools/marketing-media`, copy the wrapper to its `bin/hyperframes`, and verify configured Chromium, FFmpeg and shared library paths before enabling generation. The wrapper uses existing host binaries and does not install system packages.

`config/media-runtime.json` points to the wrapper and the vendored GSAP bundle. GSAP source is the unmodified npm distribution `gsap@3.14.2/dist/gsap.min.js`, under the GSAP standard license referenced by that package at https://gsap.com/standard-license. Keep package-lock.json and source provenance with upgrades. Optional audio and narration are not configured.

Validate a synthetic render with HyperFrames check and ffprobe before accepting runtime changes. Rendering never publishes or sends marketing.
