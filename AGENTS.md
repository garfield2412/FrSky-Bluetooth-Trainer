# Repository instructions

## Working in this repository

- Read [README.md](README.md) for setup and [docs/TECHNICAL.md](docs/TECHNICAL.md) for the data path and verification steps.
- The target is Windows x64 with Python 3.14, Tkinter, Bleak, Pillow and pystray. vJoy is a separately installed Windows driver.
- Keep repository documentation in English. Keep user-facing GUI text available in German, English and French through `languages.json`. Use CH numbers and neutral axis names in shared UI.
- Inspect Git status before editing. Keep existing user edits and use small changes that preserve each entry point. The GUI and console both use the decoder in `test_frsky_ble.py`.
- Keep `config.xml`, legacy local settings, device addresses, simulator paths, local dependency folders and generated artifacts out of commits. The FrSky logo is a tracked project asset.
- Publishing, changes to the user's autostart setting and edits to simulator profiles should follow the current user request.

## Behavior to preserve

- Keep support for both tested frame formats and verify checksum, delimiter and escaping behavior. Use captured evidence before adding another protocol format.
- Keep Tkinter calls on the main thread and communicate with the BLE worker via its queue. Preserve manual disconnect, automatic reconnect and single-instance behavior.
- Keep vJoy writes independent of graphical refresh. Preserve axis centering and release assigned buttons when the device is reset or relinquished.
- Preserve existing sender profiles when adding settings. Handle old profiles that omit new fields. Validate a fresh configuration as well as an existing one.
- Keep the live view compact and test changes in all supported languages with 8 and 16 input channels if the layout is affected.

## Documentation maintenance

- For every project change, read the relevant parts of [docs/TECHNICAL.md](docs/TECHNICAL.md) before editing and compare them with the final implementation before completing the work.
- Update the technical documentation in the same change whenever the implementation makes it inaccurate or incomplete. Check affected behavior, architecture, protocols, configuration, dependencies, entry points, and verification steps.
- Update [README.md](README.md) and the localized in-app help when a change affects setup, supported features, or user workflows described there.
- In the handoff, name the documentation sections updated or briefly state why the documentation still matches the change.

## Verification

Run the checks in the technical documentation for the code paths you changed. Use simulated packets and mocked driver calls for repeatable tests. State separately which checks used the physical radio, vJoy or the simulator. For timing claims, document the measured endpoints and distinguish software benchmarks from end-to-end measurements.
