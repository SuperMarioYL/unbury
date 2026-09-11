# Records assets/demo-unbury-card.gif — the README demo.
#
# Runs the real `unbury` binary. demo-env.sh stages the environment:
# the bundled synthetic example sessions by default (renders anywhere,
# including CI), or your own finished sessions via:
#
#     UNBURY_DEMO_PROJECT=~/code/myproject vhs docs/demo.tape

Output assets/demo-unbury-card.gif
Set Shell bash
Set Theme "GitHub Dark"
Set FontSize 15
Set Width 1100
Set Height 900
Set Framerate 25
Set TypingSpeed 40ms

# Stage the demo sessions quietly, then show the flow.
Hide
Type "source docs/demo-env.sh"
Enter
Wait
Show
Sleep 500ms

# The backlog: finished sessions recorded for this directory.
Type "unbury list"
Enter
Wait
Sleep 2s

# The pain: the raw session log the card is extracted from.
Type "wc -lc $UNBURY_TRANSCRIPT"
Enter
Wait
Sleep 1s
Type "head -c 24000 $UNBURY_TRANSCRIPT"
Enter
Wait
Sleep 3s

# The relief: one command, one screen.
Type "unbury --session 82ed5a79"
Enter
Wait
Sleep 5s

# Evidence jump-links: the same card plus the linked transcript view.
Type "unbury --session 82ed5a79 --html"
Enter
Wait
Sleep 3s
