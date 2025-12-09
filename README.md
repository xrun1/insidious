# ![Logo](./logo.png) Insidious

[Features](#features) ⬥
[Setup](#setup) ⬥
[Usage](#usage) ⬥
[Shortcuts](#keyboard-shortcuts)

Self-hosted alternative YouTube front-end.


## Features

- Responsive sane interface
- Clean search results, no "People also watched" or massive shorts carousel
- Pulls data through [yt-dlp](https://github.com/yt-dlp/yt-dlp) or rotates
  through any working [Invidious instance](https://docs.invidious.io/instances)
- Loads video data directly from Google servers at full speed,
  HLS and DASH supported
- No ads, no tracking, no YouTube scripts and cookies
- Watch age-restricted videos without signing in
- Directly accessible player controls, always visible outside of the video when
  not playing in fullscreen
- Custom suggestions algorithm based on user-generated playlists, delivers
  content related to the current video rather than what was watched before
  and irrelevant popular junk
- Recent comments first
- [Return YouTube Dislike](https://returnyoutubedislike.com/) integrated

Supported YouTube pages:

- Videos: `/watch`, `/ID`, `/v/ID`, `/live/ID`, `/embed/ID`, (`start`/`t`/`list` parameters OK)
- Shorts: `/shorts/ID` (uses standard interface)
- Clips: `/clip/ID`
- Searches: `/results` (including filtering/sorting)
- Hashtags: `/hashtag/TAG`
- Users: `/user/ID`, `/user/ID/TAB`, `/user/ID/search`
- Playlists: `/playlist`, `/watch_videos?video_ids=eXaMPLE1,examPLE2,...`
- Channels:
    - `/NAME`, `/NAME/TAB`, `/NAME/search`
    - `/channel/ID`, `/channel/ID/TAB`, `/channel/ID/search`
    - `/c/ID`, `/c/ID/TAB`, `/c/ID/search`
- RSS feeds:
    - For channels: `/feeds/videos.xml?channel_id=ID`
    - For playlists: `/feeds/videos.xml?playlist_id=ID`

Missing/planned:

- [SponsorBlock](https://sponsor.ajay.app/) integration
- [DeArrow](https://dearrow.ajay.app/) integration
- Live chats
- "Most replayed" heatmap
- Auto-generated captions


## Setup

From your system's package manager, or by following the instructions from the
following links,
install [uv](https://docs.astral.sh/uv/getting-started/installation/)
and [deno](https://docs.deno.com/runtime/#quick-install). Then:

```sh
git clone https://github.com/xrun1/insidious
cd insidious
```

Start with `uv run insidious`.
Check `uv run insidious --help` for supported options.
To update the program later, do `git pull` in the cloned repository folder
before running.

On Windows, the program can also be started with `.venv\Scripts\insidious.exe`.
Creating a shortcut to that executable in
`%appdata%\Microsoft\Windows\Start Menu\Programs\Startup`
will start Insidious on login automatically.


## Usage

An up-to-date browser (released after December 2023) is required.

- Go to the address shown when you start the server, <http://localhost:3030> by
default
- The <https://youtube.com> or <https://youtu.be> part of any URL can be
  replaced by the given address
- Use an extension like [LibRedirect](https://libredirect.github.io/) to automatically transform YouTube links (in the preferences, enable YouTube redirects, set the frontend to "Invidious", then set Insidious's address as your favorite instance).


### Keyboard shortcuts

Key | Action
--- | ---
`/` | Focus search bar
`Escape` | Leave search bar
`k`, `Space` | Play/pause
`f` | Toggle fullscreen
`c` | Toggle subtitles if available
`m` | Toggle mute
`-` | Reduce volume
`+` | Increase volume
`<` | Reduce playback speed
`>` | Increase playback speed
`h`, `j`, `Left` | Seek back 5s
`l`, `Right` | Seek forward 5s
`H`, `J` | Seek back 30s
`L` | Seek forward 30s
`,` | Seek to previous frame
`.` | Seek to next frame
`p` | Seek to previous chapter
`n` | Seek to next chapter
`P` | Go to previous playlist video
`N` | Go to next playlist video /next suggestion

These shortcuts are always active without needing player focus.
