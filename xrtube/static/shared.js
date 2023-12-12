const numberFormatter = new Intl.NumberFormat(
    navigator.language, {notation: "compact"},
)

function processText(selector, func) {
    document.querySelectorAll(selector).forEach(e => {
        e.innerText = func(parseInt(e.attributes.raw.value, 10))
    })
}

function compactAll() {
    processText(".compact-number", numberFormatter.format)
}
