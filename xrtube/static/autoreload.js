function wait(endpoint, callback) {
    const req = new XMLHttpRequest()
    req.onreadystatechange = () => { callback(req.responseText) }
    req.open("GET", endpoint, true)
    req.send()
}

wait("/wait_reload", instanceId => {
    if (! instanceId) return
    const interval = setInterval(() => {
        wait("/instance_id", newId => {
            if (! newId || instanceId === newId) return
            clearInterval(interval)
            location.reload()
        })
    }, 100)
})
