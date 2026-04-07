# VHS tape for Gauntlet TUI demo GIF
Output assets/tui-demo.gif

Set Shell bash
Set FontSize 14
Set Width 1100
Set Height 620
Set Theme "Catppuccin Mocha"
Set Padding 16
Set TypingSpeed 40ms
Set CursorBlink false

# Ensure gauntlet is on PATH
Env PATH "/Users/therig/Documents/arbiter-spec/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

Sleep 0.5s

# Launch the TUI
Type "gauntlet"
Enter

# Wait for TUI to load and discover models
Sleep 4s

# Select model 1
Type "1"
Sleep 1s

# Select model 2
Type "2"
Sleep 1.5s

# Type a prompt
Type "Explain recursion in one sentence"
Sleep 2s

# Show the full TUI state
Sleep 3s

# Quit
Type "q"
Sleep 1s
