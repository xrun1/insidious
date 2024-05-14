let controller = document.getElementById("controller")
let media = document.getElementById("hls")

let seekBack =
    parseInt(controller.getAttribute("keyboardbackwardseekoffset") || 10)

let seekForward =
    parseInt(controller.getAttribute("keyboardforwardseekoffset") || 10)

function seekFrames(count) {
    const fps = media.api.levels[media.api.currentLevel].attrs["FRAME-RATE"]
    media.currentTime += (1 / fps) * count
}

function cycleArray(array, step, currentPredicate) {
    const current = array.findLastIndex(currentPredicate)
    return array[Math.max(0, Math.min(array.length - 1, current + step))]
}

function cycleSpeed(step) {
    const menu = document.querySelector("media-playback-rate-menu")
    const rates = Array.from(menu.rates).map(parseFloat)
    media.playbackRate = cycleArray(rates, step, r => {
        return r <= menu.mediaPlaybackRate
    })
}

function cycleChapter(step) {
    const timeline = document.querySelector("media-time-range")
    const chapters = timeline.mediaChaptersCues
    if (! chapters) return false
    media.currentTime = cycleArray(chapters, step, ch => {
        return ch.startTime <= timeline.mediaCurrentTime
    }).startTime
    return true
}

function playEntry(entrySelector) {
    const entry = document.querySelector(entrySelector + " .title")
    if (entry) entry.click()
}

function playlistPrevious() {
    return playEntry("#playlist .entry:has(+ .entry.highlight)")
}

function playlistNext() {
    return playEntry("#playlist .entry.highlight + .entry")
}

function playFirstSuggestion() {
    return playEntry("#related .entry")
}

bindKeys({
    // YouTube: https://support.google.com/youtube/answer/7631406?hl=en
    j: _ => { media.currentTime -= seekBack },
    l: _ => { media.currentTime += seekBack },
    [","]: _ => { seekFrames(-1) },
    ["."]: _ => { seekFrames(1) },
    ["<"]: _ => { cycleSpeed(-1) },
    [">"]: _ => { cycleSpeed(1) },
    ["P"]: _ => { playlistPrevious() },
    ["N"]: _ => { playlistNext() || playFirstSuggestion() },

    // Additional
    h: () => { media.currentTime -= seekBack },  // vim good
    H: _ => { media.currentTime -= seekBack * 6 },
    J: _ => { media.currentTime -= seekBack * 6 },
    L: _ => { media.currentTime += seekBack * 6 },
    ["-"]: _ => { media.volume -= 0.05 },
    ["+"]: _ => { media.volume += 0.05 },
    ["p"]: _ => { cycleChapter(-1) },
    ["n"]: _ => { cycleChapter(1) },

}, ev => {
    // Already set: https://www.media-chrome.org/docs/en/keyboard-shortcuts
    if (ev.key == " ") ev.preventDefault()
    controller.keyboardShortcutHandler(ev)
})
