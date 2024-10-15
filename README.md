# ![Logo](./logo.png) Insidious

[Features](#features) ⬥
[pip setup](#local-installation-with-pip) ⬥
[Nix setup](#direct-run-with-nix) ⬥
[NixOS setup](#system-service-on-nixos) ⬥
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

- Videos: `/watch`, `/v/ID`, `/live/ID`, `/embed/ID`, (`start`/`t`/`list` parameters OK)
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

### Local installation with pip

Python 3.11 must be installed on your system.
On Linux without 3.11, consider the [Nix method](#direct-run-with-nix).
For setting up on Windows instead of Linux/OSX,
see [these notes](#windowspowershell-notes).

Local installation:

```sh
git clone https://github.com/xrun1/insidious
cd insidious
python -m venv venv
source venv/bin/activate
pip install -e .
```

To start the server, assuming the current folder is the cloned repository:
```sh
./venv/bin/insidious
```

Add ` --help` to the above command for info on supported options.

To update Insidious later, from the cloned repository folder:
```sh
git pull
source venv/bin/activate
pip install -e .
```

#### Windows/PowerShell notes

- Run `.\venv\Scripts\Activate.ps1` instead of `source venv/bin/activate`
- Run `.\venv\Scripts\insidious.exe` instead of `./venv/bin/insidious`
- Said executable can be double clicked directly in explorer to start
- In `%appdata%\Microsoft\Windows\Start Menu\Programs\Startup`, a
  shortcut to the exe can be created to automatically start Insidious on login.


### Direct run with Nix

[Install the Nix package manager](https://github.com/DeterminateSystems/nix-installer)
if needed, then:
```sh
nix run github:xrun1/insidious
```

Add ` -- --help` to the above command for info on supported options.

### System service on NixOS

With flakes: add this repository to your inputs, import the module, and enable
the service.  
Minimal example:

```nix
# flake.nix
{
    inputs = {
        nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
        insidious.url = "github:xrun1/insidious";
    };
    outputs = inputs @ { self, nixpkgs, ... }: {
        nixosConfigurations.example = nixpkgs.lib.nixosSystem {
            system = "x86_64-linux";
            specialArgs = { inherit inputs; };
            modules = [./configuration.nix ./insidious.nix];
        };
    };
}

# insidious.nix
{ inputs, ... }: {
    imports = [inputs.insidious.nixosModules.default];
    services.insidious.enable = true;
}
```

See [os.nix](./os.nix) for options beyond `enable`.


## Usage

An up-to-date browser (released after December 2023) is required.

- Go to the address shown when you start the server, <http://localhost:3030> by
default
- The <https://youtube.com> or <https://youtu.be> part of any URL can be
  replaced by the given address 
- Use an extension like Privacy Redirect ([Chrome](https://chromewebstore.google.com/detail/privacy-redirect/pmcmeagblkinmogikoikkdjiligflglb), [Firefox](https://addons.mozilla.org/en-US/firefox/addon/privacy-redirect/))
  to automatically transform YouTube links (enable "Invidious redirects" in the options and set Insidious's address for the instance).


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
