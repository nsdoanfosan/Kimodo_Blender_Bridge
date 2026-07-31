# Kimodo Motion Receiver for iClone

Restricted loopback OpenPlugin used by Kimodo Blender Bridge. It receives
bounded FK tracks from Blender and applies them to the currently selected
iClone avatar. Incoming keys are only a construction layer: the receiver
immediately flattens them into one Motion Clip so Motion Layer stays available
for later corrections. It does not expose arbitrary Python or filesystem
operations.

The installed folder is junctioned into:

`C:\Program Files\Reallusion\iClone 8\Bin64\OpenPlugin\Kimodo Motion Receiver`

On systems where the existing generic RLPy bridge is the installed OpenPlugin
host, it can import this package through a source junction instead. Runtime
token and log files stay outside Git under
`%LOCALAPPDATA%\Kimodo Blender Bridge`.

iClone must be restarted after the plugin is first installed or updated.
