const lang = navigator.language
const numberFormatter = new Intl.NumberFormat(lang , {notation: "compact"})
const yearsAgoFormatter = new Intl.DateTimeFormat(lang, {year: "numeric"})
const thisYearFormatter = new Intl.DateTimeFormat(lang, {
    month: "short", year: "numeric",
})
const thisMonthFormatter = new Intl.DateTimeFormat(lang, {
    day: "numeric", month: "short", year: "numeric",
})
const todayFormatter = new Intl.DateTimeFormat(lang, {
    hour: "numeric", minute: "numeric",
})
const futureFormatter = new Intl.DateTimeFormat(lang, {
    year: "numeric", month: "short", day: "numeric",
    hour: "numeric", minute: "numeric",
})
const relativeFormatter = new Intl.RelativeTimeFormat(lang, {
    numeric: "auto", style: "short",
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

function processText(selector, func) {
    document.querySelectorAll(selector).forEach(e => {
        e.innerText = func(parseInt(e.attributes.raw.value, 10))
    })
}

function processAllText() {
    processText(".compact-number", numberFormatter.format)
    processText(".youtube-date", formatYoutubeDate)
}
