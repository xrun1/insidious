# Changelog


## v0.1.7 (2024-08-03)

### Fixed

- Upcoming video pages
- Update yt-dlp required version for failing videos


## v0.1.6 (2024-07-25)

### Fixed

- Update yt-dlp required version to fix failing videos


## v0.1.5 (2024-07-24)

### Fixed

- "Internal server error" page for videos missing a release date 


## v0.1.4 (2024-07-15)

### Added

- Button on embedded players to open the video's full page
- Popularity sorting option on channel video lists
- Support for `/watch_videos?video_ids=eXaMPLE1,examPLE2`
  (generates YouTube playlists from comma-separated combination of video IDs)

### Changed

- Make reduced video progress bar more visible in fullscreen
- On video pages, load the comments/suggestions/playlist only when the tab is
  focused, to avoid Google server timeouts and broken thumbnails when many
  results are opened as background tabs in quick succession

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
