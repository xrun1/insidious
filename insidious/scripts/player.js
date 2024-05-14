function controller() {
    return document.getElementById("controller")
}

function media() {
    return document.getElementById("hls")
}

function seek(step) {
    const attr = controller().getAttribute("keyboardbackwardseekoffset")
    return media().currentTime += parseInt(attr || 10) * step
}

function seekFrames(count) {
    const media = media()
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
    media().playbackRate = cycleArray(rates, step, r => {
        return r <= menu.mediaPlaybackRate
    })
}

function cycleChapter(step) {
    const timeline = document.querySelector("media-time-range")
    const chapters = timeline.mediaChaptersCues
    if (! chapters) return false
    media().currentTime = cycleArray(chapters, step, ch => {
        return ch.startTime <= timeline.mediaCurrentTime
    }).startTime
    return true
}

function click(selector) {
    document.querySelector(selector)?.click()
}


function playEntry(entrySelector) {
    click(entrySelector + " .title")
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

export function setupPlayer() {
    controller().hotkeys.add(
        "nospace", "nok", "nom", "nof", "noc", "noarrowleft", "noarrowright",
    )
}

bindKeys({
    // YouTube: https://support.google.com/youtube/answer/7631406?hl=en
    [" "]: _ => { click("media-play-button") },
    k: _ => { click("media-play-button") },
    m: _ => { click("media-mute-button") },
    f: _ => { click("media-fullscreen-button") },
    c: _ => { click("media-captions-button") },
    j: _ => { seek(-1) },
    l: _ => { seek(1) },
    ArrowLeft: _ => { seek(-1) },
    ArrowRight: _ => { seek(1) },
    [","]: _ => { seekFrames(-1) },
    ["."]: _ => { seekFrames(1) },
    ["<"]: _ => { cycleSpeed(-1) },
    [">"]: _ => { cycleSpeed(1) },
    ["P"]: _ => { playlistPrevious() },
    ["N"]: _ => { playlistNext() || playFirstSuggestion() },

    // Additional
    h: () => { seek(-1) },  // vim good
    H: _ => { seek(-6) },
    J: _ => { seek(-6) },
    L: _ => { seek(6) },
    ["-"]: _ => { media().volume -= 0.05 },
    ["+"]: _ => { media().volume += 0.05 },
    ["p"]: _ => { cycleChapter(-1) },
    ["n"]: _ => { cycleChapter(1) },
})
