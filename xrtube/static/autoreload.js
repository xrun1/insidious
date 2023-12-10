function wait(endpoint, callback) {
    const req = new XMLHttpRequest()
    req.onreadystatechange = () => { callback(req.responseText) }
    req.open("GET", endpoint, true)
    req.send()
}

wait("/wait_reload", text => {
    if (! text) return
    if (text === "direct") {
        location.reload()
        return
    }
    const interval = setInterval(() => {
        wait("/instance_id", newText => {
            if (! newText || text === newText) return
            clearInterval(interval)
            location.reload()
        })
    }, 100)
})

function reloadCss() {
    wait("/wait_reload_scss", text => {
        if (! text) return
        document.querySelectorAll("link[rel=stylesheet]").forEach(link =>
            link.href = link.href.replace(/\?.*|$/, "?" + Date.now())
        )
        reloadCss()
    })
}
reloadCss()
