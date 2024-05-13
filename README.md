# ![Logo](./logo.png) Insidious

[Features](#features) ⬥
[pip setup](#local-installation-with-pip) ⬥
[Nix setup](#direct-run-with-nix) ⬥
[NixOS setup](#system-service-on-nixos) ⬥
[Usage](#usage)

Self-hosted alternative YouTube front-end.


## Features

- Responsive sane interface
- Clean search results, no "People also watched" or massive shorts carousel
- Pulls data through [yt-dlp](https://github.com/yt-dlp/yt-dlp) or rotates
  through any working [Invidious instance](https://docs.invidious.io/instances)
- Loads video data directly from Google servers at full speed,
  HLS and DASH supported
- No ads, no tracking, no YouTube scripts and cookies
- Watch age-gated videos without signing in
- Directly accessible player controls with all-time visibility
  outside fullscreen
- Custom suggestions algorithm based on user-generated playlists, delivers
  content related to the current video instead of what was watched before
  and irrelevant popular junk
- Recent comments first
- [Return YouTube Dislike](https://returnyoutubedislike.com/) integrated

Supported YouTube pages:

- Videos: `/watch`, `/v/ID`, `/embed/ID`, (`start`/`t`/`list` parameters OK)
- Shorts: `/shorts/ID` (uses standard interface)
- Clips: `/clip/ID`
- Searches: `/results` (including filtering/sorting)
- Users: `/user/ID`, `/user/ID/TAB`, `/user/ID/search`
- Playlists: `/playlist`
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

Tested with Python 3.11 only. If unavailable on your system, 
consider the [Nix method](#direct-run-with-nix).

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

- Go to the address shown when you start the server, <http://localhost:8000> by
default
- The <https://youtube.com> part of any URL can be replaced by the
  given address 
- For <https://youtu.be/ID> links, change to e.g. <http://localhost:8000/v/ID>.
