# Changelog


## v0.1.4 (WIP)

### Added

- Button on embedded players to open the video's full page
- Popularity sorting option on channel video lists
- Support for `/watch_videos?video_ids=eXaMPLE1,examPLE2`
  (generates YouTube playlists from comma-separated combination of video IDs)

### Fixed

- Channel "Popular videos" being the same as normal latest "Videos" section


## v0.1.3 (2024-07-10)

### Added

- Support for `/live/ID` YouTube URLs 

### Fixed

- Milliseconds appearing on the dates of comments made less than one minute ago
- Age-restricted video playback by updating the yt-dlp required version


## v0.1.2 (2024-05-13)

### Added

- [Keyboard shortcuts](./README.md#keyboard-shortcuts)
- RSS feed buttons for channels and playlists

### Fixed

- Empty responses from a single Invidious instance breaking comments retrieval
- Loading of videos with no like counts


## v0.1.1 (2024-05-13)

### Changed

- Default port from 8000 to 3030
