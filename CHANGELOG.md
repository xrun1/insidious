# Changelog

## v0.1.11 (2025-08-09)

### Fixed

- Channels with a "Posts" section in their home pages not loading
- Shorts with no view counts causing no search results or related videos


## v0.1.10 (2025-06-25)

### Fixed

- Use Piped instances as alternate comment source while Invidious is dead
- Playback failing due to outdated yt-dlp and bad client selection
- Thumbnails and descriptions missing for some RSS clients
- Loading channels missing a featured tab
- Broken video streams infinitely retrying with no delay
- "Copied YouTube link" tooltip background color in light mode


## v0.1.9 (2024-10-15)

### Added

- Header button to copy the original YouTube page URL
- Support for directly using `/VIDEO_ID` URLs, useful when extensions like
  Privacy Redirect automatically convert youtu.be links

### Fixed

- Rare occurrence of videos channel links failing to parse
- Usage of the `--reload` flag on Windows


## v0.1.8 (2024-08-08)

### Fixed

- Update yt-dlp required version for failing videos


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
