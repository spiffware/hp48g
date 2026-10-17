# Application artwork

`hp48gx-icon.png` is the transparent master artwork for the application icon,
created for this project using image generation with the existing HP logo as a
visual reference. Its charcoal case, sage LCD and purple/teal accents match the
calculator skin. It is separate from `hp-logo.png`, the faceplate logo source.

`hp48gx-icon.ico` contains Windows icon sizes from 16 to 256 pixels.
`hp48gx-icon.icns` contains macOS sizes through 1024 pixels.
Regenerate both containers with `python scripts/build_icons.py` (Pillow).

The app uses this artwork for runtime window, Dock/task-switcher and tray icons.
The desktop build embeds the platform container in the app bundle/executable.
