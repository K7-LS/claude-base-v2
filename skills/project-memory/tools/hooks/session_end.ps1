# session_end.ps1 - deprecated project-memory Stop hook.
#
# Kept as a silent compatibility target for existing settings. Portable
# STATUS/journal updates now follow material project-state changes and model
# judgement; a generic Stop hook cannot determine that safely and must not
# block a session.

exit 0
