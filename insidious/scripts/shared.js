// Copyright Insidious authors <https://github.com/xrun1/insidious>
// SPDX-License-Identifier: AGPL-3.0-or-later

const lang = navigator.language
const thinNumberFormatter = new Intl.NumberFormat(lang , {notation: "compact"})
const numberFormatter = new Intl.NumberFormat(lang)
const yearsAgoFormatter = new Intl.DateTimeFormat(lang, {year: "numeric"})
const thisYearFormatter = new Intl.DateTimeFormat(lang, {
    month: "short", year: "numeric",
})
const thisMonthFormatter = new Intl.DateTimeFormat(lang, {
    day: "numeric", month: "short",
})
const todayFormatter = new Intl.DateTimeFormat(lang, {
    hour: "numeric", minute: "numeric",
})
const futureFormatter = new Intl.DateTimeFormat(lang, {
    month: "short", day: "numeric", hour: "numeric", minute: "numeric",
})
const relativeFormatter = new Intl.RelativeTimeFormat(lang, {
    numeric: "auto", style: "short",
})
const normalDateFormatter = new Intl.DateTimeFormat(lang, {
    day: "numeric", month: "short", year: "numeric",
})

function formatYoutubeDate(timestamp) {
    const date = new Date(timestamp * 1000)
    const secondsAgo = (new Date() - date) / 1000
    const minutesAgo = Math.floor(secondsAgo / 60)
    const hoursAgo = Math.floor(minutesAgo / 60)
    const daysAgo = Math.floor(hoursAgo / 24)

    if (daysAgo >= 365)
        return yearsAgoFormatter.format(date)
    if (daysAgo >= 31)
        return thisYearFormatter.format(date)
    if (daysAgo >= 3)
        return thisMonthFormatter.format(date)
    if (daysAgo >= 1)
        return relativeFormatter.format(-daysAgo, "day")
    if (hoursAgo >= 1)
        return relativeFormatter.format(-hoursAgo, "hour")
    if (minutesAgo >= 1)
        return relativeFormatter.format(-minutesAgo, "minute")
    if (secondsAgo >= 0)
        return relativeFormatter.format(-secondsAgo, "second")
    if (daysAgo >= -1)
        return todayFormatter.format(date)
    return futureFormatter.format(date)
}

function formatYoutubeDayDate(timestamp) {
    return normalDateFormatter.format(new Date(timestamp * 1000))
}

function processText(selector, func) {
    document.querySelectorAll(selector + ":not(.processed)").forEach(e => {
        e.classList.add("processed")
        e.innerText = (e.attributes.prefix?.value || "") +
            func(parseInt(e.attributes.raw.value, 10)) +
            (e.attributes.suffix?.value || "")
    })
}

function processAllText() {
    processText(".compact-number", thinNumberFormatter.format)
    processText(".number", numberFormatter.format)
    processText(".youtube-date", formatYoutubeDate)
    processText(".youtube-day-date", formatYoutubeDayDate)
}

function parseYoutubeStartTime(time) {
    // Accept strings like "1h03m12s", "4m22.5s" or just second numbers.
    // Unlike YT, this supports milliseconds.
    if (! isNaN(time)) return time
    const [h, m, s] = [0, 0, ...time.split(/[a-z]+/i).filter(x => x)]
        .slice(-3).map(x => parseFloat(x, 10))
    return h * 3600 + m * 60 + s
}

function processHmsTimeLinks(video) {
    document.querySelectorAll("a[hms-time]").forEach(a => {
        const url = new URL(window.location.href)
        const hms = a.getAttribute("hms-time")
        url.searchParams.set("t", hms)
        a.href = url.href
        a.onclick = () => {
            video.pause()
            video.currentTime = parseYoutubeStartTime(hms)
            video.play()
            return false
        }
    })
}

function runHoverSlideshow(entry) {
    const thumbnails = entry.querySelector(".hover-thumbnails")
    if (! thumbnails.children) return
    const current = thumbnails.querySelector(".current")
    const next = thumbnails.querySelector(".current + *") ||
        thumbnails.children[0]
    const nextImg = next.querySelector("img")

    function change() {
        current?.classList.remove("current")
        next.classList.add("current")
        if (! entry.matches(":hover")) {
            stopHoverSlideshow(entry)
            return
        }
        thumbnails.setAttribute("timer-id", 
            setTimeout(() => { runHoverSlideshow(entry) }, 1000) 
        )
    }

    if (nextImg.hasAttribute("to-load")) {
        nextImg.srcset = nextImg.getAttribute("to-load")
        nextImg.removeAttribute("to-load")
    }
    nextImg.complete ? change() : nextImg.addEventListener("load", change)
}

function stopHoverSlideshow(entry) {
    const thumbnails = entry.querySelector(".hover-thumbnails")
    clearTimeout(thumbnails.getAttribute("timer-id"))
    thumbnails.removeAttribute("timer-id")
    thumbnails.querySelector(".current")?.classList.remove("current")
}

function setCookie(name, obj, secondsAlive=0) {  // 0 = die on browser close
    const body = encodeURIComponent(JSON.stringify(obj))
    const age = secondsAlive ? `; max-age=${secondsAlive}` : ""
    document.cookie = `${name}=${body}; path=/; samesite=lax` + age
}

function setToughCookie(name, obj) {
    setCookie(name, obj, 60 * 60 * 24 * 400)  // max age of 400 days
}

function getCookie(name, default_=null) {
    for (const cookie of document.cookie.split("; "))
        if (cookie.split("=")[0] === name)
            return JSON.parse(decodeURIComponent(cookie.split("=")[1]))
    return default_
}

function isShortGroup(el) {
    return el.classList?.contains("short-group")
}

function mergeShortGroups(current) {
    let prev = current.previousElementSibling
    while (prev && (prev.tagName == "SCRIPT" || prev.tagName == "BUTTON"))
        prev = prev.previousElementSibling

    console.log(current, prev, isShortGroup(current), isShortGroup(prev))
    if (isShortGroup(current) && isShortGroup(prev)) {
        prev = prev.querySelector(".shorts")
        for (const child of current.querySelectorAll(".entry")) {
            prev.appendChild(child)
        }
        current.remove()
    }
}

function loadButtonSaveCurrentScroll(button) {
    button.previousScrollX = window.scrollX
    button.previousScrollY = window.scrollY
}

function loadButtonRestoreScroll(button) {
    window.scroll(button.previousScrollX, button.previousScrollY)
}
