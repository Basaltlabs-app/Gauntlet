# VHS demo tape for Gauntlet README GIF
Output assets/demo.gif

Set Shell zsh
Set FontSize 14
Set Width 900
Set Height 500
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 40ms

# Set PATH so gauntlet is found
Type "export PATH=$HOME/Library/Python/3.9/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
Enter
Sleep 0.5s

# Show the tool
Type "gauntlet --help"
Enter
Sleep 3s

# Discover models
Type "gauntlet discover"
Enter
Sleep 3s

# Run behavioral tests
Type "gauntlet run --model ollama/qwen3.5:4b --profile assistant --quick"
Enter
Sleep 5s

# Show leaderboard
Type "gauntlet leaderboard"
Enter
Sleep 2s
