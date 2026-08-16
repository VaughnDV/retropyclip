# Roadmap

RetroPyClip is an alpha. The order below is intentional: correctness and threat
modelling before distribution polish.

1. Finish remaining real-device rows (Ubuntu X11, GNOME Wayland, Raspberry Pi) and
   one-account Drive round-trips with synthetic data.
2. Independent review of cryptography, OAuth handling, and packaging.
3. Signed and notarised macOS `.app`, plus a documented Linux portable bundle.
4. Optional SQLCipher (or equivalent) only if a locked-session requirement appears.
5. Configurable shortcuts and a Linux-wide history hotkey.
6. Remote garbage-collection of tombstoned Drive objects.
7. Windows support only with an adapter, CI job, and hardware matrix row.

Snippets, image capture, and a hosted backend are out of scope.
