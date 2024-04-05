let ws = new WebSocket(`ws://${location.host}/wait_reload`)

ws.onmessage = event => {
    console.log(event)

    if (event.data === "page") {
        location.reload()
    } else if (event.data === "style") {
        document.querySelectorAll("link[rel=stylesheet]").forEach(link =>
            link.href = link.href.replace(/\?.*|$/, "?" + Date.now())
        )
    }
}

ws.onclose = event => {
    console.log(event)

    const interval = setInterval(() => {
        let ws = new WebSocket(`ws://${location.host}/wait_alive`)
        ws.onopen = () => {
            clearInterval(interval)
            location.reload()
        }
        ws.onclose = console.log
        ws.onerror = console.log
    }, 250)

};

ws.onerror = console.log
