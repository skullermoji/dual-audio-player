# Dual-Audio Player (mpv + PySide 6)

Simple and slightly crunchy GUI around libmpv that

* plays videos with any number of audio tracks
* lets you mix per-track volumes
* shows a seek bar with live time
* remembers volumes and window size
* click video to pause/play

Get libmpv-2.dll and drop it into the same folder as dual_audio_player.pyw, and you're off to the races (provided you've met prerequisites).

My use case is for playback of videos with multiple audio tracks, such as Instant Replay clips with separate system/microphone audio tracks. Normal video players only play one audio track at a time, so I created this to stop needing to drag videos into a video editor.
