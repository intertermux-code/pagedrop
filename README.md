# pagedrop

[![PyPI version](https://img.shields.io/pypi/v/pagedrop.svg)](https://pypi.org/project/pagedrop/)
[![CI](https://github.com/intertermux-code/pagedrop/actions/workflows/test.yml/badge.svg)](https://github.com/intertermux-code/pagedrop/actions/workflows/test.yml)

A pip-installable, flag-compatible drop-in replacement for
[wkhtmltopdf](https://github.com/wkhtmltopdf/wkhtmltopdf). Same command line,
same header and footer variables, same exit codes — and a maintained engine
with no browser to download and no system libraries to install.

```console
$ pip install pagedrop
$ wkhtmltopdf --page-size A4 --margin-top 25mm \
    --header-left "ACME Corp" --footer-center "Page [page] of [topage]" \
    invoice.html invoice.pdf
```

Installing `pagedrop` puts a `wkhtmltopdf` executable on your `PATH` (and a
`pagedrop` alias). Every script, cron job, Makefile and `subprocess.run` call
that shells out to `wkhtmltopdf` keeps working unchanged.

Two subcommands go a step past the drop-in line: `pagedrop cover` fronts a
document with a cover page of its own, and `pagedrop serve` keeps the converter
resident and turns it into an HTTP service. Both are documented below.

## Why

wkhtmltopdf is archived. The repository went read-only in January 2023, its
patched Qt/WebKit build has known CVEs that will never be fixed, and the
Python wrapper `pdfkit` is unmaintained too. It is still the converter behind
an enormous amount of invoicing, statement and report plumbing, where the
rendering is incidental and nobody wants to rewrite a hundred call sites.

The alternatives all ask for something extra:

| | |
| --- | --- |
| Gotenberg | a Docker/Chromium HTTP service you deploy and operate |
| WeasyPrint | a Python library, with no flag-level compatibility and a Pango/Cairo install |
| paid APIs | a network call in the middle of your batch job |

pagedrop asks for one `pip install`.

## What it is honest about

pagedrop does not pretend to be WebKit. It maps the flags that real pipelines
pass onto a print-CSS engine, and **refuses the ones it cannot honour** rather
than accepting them and ignoring them — a silently dropped `--javascript-delay`
is how you end up with blank invoices at 3am.

```console
$ wkhtmltopdf --javascript-delay 2000 in.html out.pdf
wkhtmltopdf: option '--javascript-delay' is not supported: the print engine
runs no JavaScript, so there is nothing to wait for
$ echo $?
1
```

`wkhtmltopdf --help` lists every option it knows and which of the three
categories it falls into.

## Install

```console
$ python3 -m pip install pagedrop
```

The name is free on PyPI and the first upload has not happened yet, so until
then install from the checkout:

```console
$ python3 -m pip install -e ".[dev]"        # this repository
$ python3 -m pip install git+https://github.com/intertermux-code/pagedrop.git
```

Python 3.9 or newer. The dependencies are `xhtml2pdf` (the layout engine, on
top of ReportLab) and `pypdf` (for `--grayscale`, and for joining a cover to the
document it fronts); both are pure Python,
so there is nothing to compile and no font or browser to fetch.

If the real wkhtmltopdf is already on the machine, `PATH` decides which one
your scripts get. Check with `command -v wkhtmltopdf`, and either remove the
system package or put the pip `bin` directory first:

```console
$ which wkhtmltopdf                      # should be your venv or ~/.local/bin
$ wkhtmltopdf --version
wkhtmltopdf 0.1.0 (pagedrop shim, engine xhtml2pdf 0.2.27)
```

The engine version is the `xhtml2pdf` release pip resolved for your interpreter:
0.2.27 on Python 3.10 and newer, 0.2.17 on 3.9, because the newer releases need
3.10.

The version line says what it is. Scripts that grep for `0.12` need updating
once; nothing else does.

### Keeping pdfkit

`pdfkit` is only an argument-quoting layer around the binary, so it can be
pointed at the shim without touching the calling code:

```python
import pdfkit

pdfkit.configuration(wkhtmltopdf="/usr/local/bin/wkhtmltopdf")  # the shim
pdfkit.from_string(html, "invoice.pdf", options={"page-size": "A4", "footer-center": "Page [page]"})
```

## Migration

The switch is normally a one-line change in a Dockerfile or a requirements
file, with no edits to the call sites:

```dockerfile
# before
RUN apt-get install -y wkhtmltopdf
# after
RUN pip install pagedrop
```

Run your existing commands with the shim and read what it says. Anything it
refuses is a place where the two engines genuinely differ, and it names the
difference. A conversion that succeeds prints nothing.

### Flags honoured

| Flag | What it becomes |
| --- | --- |
| `-s, --page-size` | `@page` size: A3–A6, B4, B5, C5, Letter, Legal, Tabloid, Executive, Folio, Quarto, or `WIDTHxHEIGHT` such as `210mmx297mm` |
| `--page-width`, `--page-height` | explicit page box |
| `-O, --orientation` | Portrait / Landscape |
| `-T -B -L -R, --margin-*`, `-m --margin` | page margins, bare numbers in mm |
| `--margin-unit` | mm, cm, inch, pt, px |
| `--header-html`, `--footer-html` | the fragment rendered into the top / bottom margin of every page |
| `--header-left/center/right`, `--footer-left/center/right` | three-cell band in the margin |
| `--header-spacing`, `--footer-spacing` | gap between the band and the content |
| `--header-line`, `--footer-line` | rule below the header, above the footer |
| `--header-font-*`, `--footer-font-*` | name, size, colour of the band |
| `--cover` | a cover document in front of the page document, on its own paper and without its bands — see [Cover pages](#cover-pages) |
| `--title` | PDF information dictionary (falls back to the document's `<title>`) |
| `--encoding` | input decoding |
| `--log-level` | verbosity of the engine log: none, info, error |
| `--outline`, `--no-outline`, `--outline-depth` | PDF bookmarks from `h1`–`h6`, cut off at the depth asked for |
| `-g, --grayscale` | RGB fills and strokes rewritten to their luma equivalent |
| `--user-style-sheet` | CSS appended after the document's own |
| `--disable-local-file-access` | confine image and font reads to the document's directory |
| `--options-file` | extra arguments read from a file, `#` comments allowed |
| `--log-path` | engine warnings written to a file |
| `-q, --quiet` | suppress the shim's own notes |
| `--print-media-type`, `--disable-smart-shrinking`, `--enable-local-file-access`, `--disable-javascript`, `--no-stop-slow-scripts`, `--lowquality` | accepted: this engine already behaves that way |
| `--dpi 96`, `--zoom 1`, `--copies 1`, `--image-dpi 600`, `--image-quality 94` | accepted at wkhtmltopdf's default value, refused above it |

Anything not on that list is refused: with an explanation where the two engines
genuinely differ, and as an unknown option where the flag does not exist at
all. That is the right outcome while you are grepping for stragglers.

### Header and footer variables

Expanded in `--header-*`/`--footer-*` text and in the HTML files they name:

`[page]` `[frompage]` `[topage]` `[date]` `[isodate]` `[time]` `[timestamp]`
`[year]` `[month]` `[day]` `[title]` `[doctitle]` `[url]` `[webpage]`

`[page]` and `[topage]` are resolved **per page** — page 7 of 9 says 7 of 9 —
because they are handed to the engine as page-numbering tags rather than
substituted as text. `[section]` and `[subsection]` come out empty and print a
note on stderr: they depend on WebKit's per-page chapter tracking, which this
engine has no equivalent of.

Text given to `--header-left` and friends is HTML-escaped before it is placed,
so a `&` or `<` in a company name cannot break the band. The values expanded
into it are escaped too — a document's title, its name, and the placeholder
`<request>` the service uses where a file name would be.

Numbering is per document. A report of twelve pages says `Page 12 of 12` on its
last page whether or not a cover was put in front of it, and `[topage]` never
counts the cover.

## Cover pages

Real wkhtmltopdf has taken a cover as an object of its own, and so does this:

```console
$ wkhtmltopdf cover cover.html report.html report.pdf
```

The flat flag does the same job for a script that already names one document:

```console
$ wkhtmltopdf --cover cover.html report.html report.pdf
```

Options attach to the document they follow, which is how a cover gets its own
paper while the report keeps its margins and bands:

```console
$ wkhtmltopdf cover cover.html --page-size A5 \
    report.html --margin-top 25mm --header-left "ACME Corp" \
    --footer-center "Page [page] of [topage]" \
    report.pdf
```

The flags before the cover and the ones after the output belong to the whole
run, because there is no document for them to attach to: `--grayscale` at the
end of that line greys out every page of it, and a page size given out front is
given to both documents.

What "its own document" buys you:

- **Its own page.** The cover is rendered on its own and joined to the report
  with `pypdf`, so the `@page` rules in the cover's stylesheet govern it. Give
  it an explicit `--page-size`, `--page-width`/`--page-height` or `--margin` on
  the command line and those win instead: a page you asked for is an
  instruction, a default is not.
- **No running bands.** `--header-*` and `--footer-*` stay with the document
  they were written for. Name a band in the cover's own position on the line and
  the cover gets it.
- **Its own numbering.** `[page]` counts the report, as above.
- **The report's identity.** `--title` and the outline belong to the document
  being titled; the cover only fronts it.

A cover file that is not there is a clean exit 1 — `cannot read ...`, before
anything is rendered — and no PDF is written.

## Conversion service

`pagedrop serve` keeps the converter resident and answers HTTP, for a pipeline
that converts often enough to feel the interpreter and the engine import on every
document. This one is pagedrop's own: wkhtmltopdf never had a server mode.

```console
$ pagedrop serve --port 8080
pagedrop serve: listening on http://127.0.0.1:8080/ (GET /health, POST /convert)
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | JSON status: which pagedrop, which engine, how much work is in hand |
| `POST /convert` | the PDF |

```console
$ curl -s http://127.0.0.1:8080/health
{"status": "ok", "version": "0.1.0", "engine": "0.2.27", "converting": 0, "waiting": 0}
$ curl -s --data-binary @invoice.html -H 'Content-Type: text/html' \
    'http://127.0.0.1:8080/convert?margin-top=25mm&footer-center=Page%20%5Bpage%5D%20of%20%5Btopage%5D' \
    -o invoice.pdf
```

`POST /convert` reads the document two ways:

- **the body as the document.** `text/html`, `text/plain`, no `Content-Type` at
  all, and the `application/x-www-form-urlencoded` a bare `curl -d @file` sends
  are all taken as markup, with the options in the query string;
- **a JSON object.** `{"html": "...", "options": {"margin-top": "25mm"},
  "cover": "..."}`, where `html` is required and the other two are not.

`options` keys are the command line's flag names with or without their leading
dashes — the shape `pdfkit` already passes — and mean what they mean on the
command line, including being refused when the engine cannot honour them:

```console
$ curl -s -X POST -H 'Content-Type: application/json' \
    -d '{"html": "<h1>Q3</h1>", "options": {"page-size": "A5", "grayscale": true}, "cover": "<h1>Cover</h1>"}' \
    http://127.0.0.1:8080/convert -o q3.pdf
```

`cover` is the cover document as markup, the same object the `cover` command
fronts a document with. The `cover` *option* is refused: its value would name a
file on the server's disk rather than the requester's.

**Errors** are 4xx with a one-line JSON body, `{"error": "..."}`, and a stack
trace never reaches the client. `405` carries an `Allow` header, `404` names the
endpoints, `411` and `413` say what the request lacked, `415` says what it was
not, `400` says what was wrong with the document or its options, and anything
genuinely unforeseen is `500 internal server error` with its detail written to
the service's stderr.

**Concurrency** is one thread per connection with a bounded number of
conversions in flight, `--max-concurrent` (default 4). Requests past that wait
their turn rather than being turned away with a `503`, because a conversion is
short and a batch of invoices wants to arrive in order anyway. `/health` reports
the two halves of that as `converting` and `waiting`, which is what a supervisor
watches for a wedge. Threads, not processes: xhtml2pdf and ReportLab are pure
Python, so a second worker would not buy a second core — the bound is about
memory, queue depth and honesty in `/health`.

**Limits**: a body over `--max-body` (default 32MB) is refused before it is read,
and a connection that stops talking is dropped after 30 seconds. Both are per
request; nothing is kept between them.

**Address and port** come from `--host`/`--port` or from `PAGEDROP_HOST` and
`PAGEDROP_PORT`, the command line first. The default bind is the loopback
interface, and that is load-bearing: anyone who can reach the port can hand the
service markup and the options that read files off the disk (`--header-html` and
friends). Run it on a network you control, behind something that authenticates,
and do not put it on a public interface.

`SIGINT` and `SIGTERM` stop it between requests: the listening socket is closed,
the conversions in flight are answered, and the process exits 0 with a
`stopped` line on stderr. `--verbose` logs every request as it is served.

## Pagination

The page model is the part of wkhtmltopdf that pipelines lean on hardest, so
these are tested on the PDF that comes back, not on the markup that went in:

- **One page is not a special case.** `[page]` and `[topage]` agree: a document
  that fits says `Page 1 of 1`, on its only page.
- **An empty document is still a PDF.** An empty body, no body element at all, or
  a bare fragment with no `<html>` around it each produce one valid page. A
  fragment is wrapped rather than dropped, which is what a `POST` of `<p>…</p>`
  to the service relies on.
- **Content splits mid-element and keeps counting.** A paragraph broken across a
  page break, and a table long enough to run over several pages, carry the right
  `Page n of N` on every page they land on, and their text survives the break.
- **Bands are drawn on every page**, the first and the last included. There is no
  per-page exclusion, because the engine has no notion of "first page" for a
  margin box: a cover document is how a title page escapes the running header.
- **A band takes room from the page it was put in.** `--margin-top`/`--margin-bottom`
  say how much of the page the band may use, `--*-spacing` adds a gap between the
  band and the content, and the content area shrinks to whatever is left. The
  footer frame is measured from the bottom edge of the page inwards, so it stays
  inside the page box at any margin.
- **A page that cannot be laid out is refused before one is rendered.** A
  non-positive `--page-width`/`--page-height`, a negative margin, margins that
  leave no width or no height for the content, and a negative `--*-spacing` each
  get their own message and exit 1, rather than a ReportLab traceback or a PDF
  with a zero-sized box that a viewer refuses.

## Limitations, stated plainly

**No JavaScript.** This is the big one. A page that builds its table in a
`<script>` renders as an empty document. Print the data from your template
layer instead, or keep wkhtmltopdf for that one job.

**No reflow zoom.** `--zoom` and `--dpi` are refused. WebKit reflows the page
when it shrinks it; a print engine cannot, so there is nothing honest to map
them onto. Set the type scale in CSS (`body { font-size: 90% }`) instead.

**A smaller CSS subset.** xhtml2pdf implements print-oriented CSS 2.1 well and
nothing else: no `float`, no flexbox, no grid, no `position: fixed`. The engine
warns on stderr about properties it drops, and `--log-path` collects them.
Documents that were already written for print — the overwhelming majority of
invoices — usually need no changes.

**Fonts.** The base-14 fonts (Helvetica, Times, Courier) are always available.
`Arial` is not one of them and is substituted by Helvetica unless you register
it:

```css
@font-face { font-family: "Brand"; src: url("/usr/share/fonts/truetype/arial.ttf"); }
```

Absolute font and image paths are readable by default, matching
`--enable-local-file-access`. With `--disable-local-file-access` the search is
confined to the document's directory plus any directories named in
`PAGEDROP_RESOURCE_ROOTS` (path-separated). Engine releases that predate
resource policies cannot confine anything, and the shim refuses the flag there
instead of accepting it quietly.

**Header and footer HTML is inlined, not isolated.** wkhtmltopdf renders each
of those files as its own page. pagedrop hoists their `<style>` blocks into the
document and places their body content in the margin band, which is visually
equivalent for anything but a fragment that relies on its own `@page` rules —
those are dropped, deliberately, since they describe a different page.

**Band depth is not measured.** wkhtmltopdf grows the top margin to fit the
header it rendered. pagedrop cannot measure an HTML fragment before laying the
page out, so when you pass `--header-html` without `--margin-top` it reserves
15 mm and lets the band overflow if the fragment is taller. Set `--margin-top`
explicitly for anything but a one-line header.

**Tighter network rules than upstream, where the engine can enforce them.** The
engine's resource policy fetches over plain HTTP(S) only and refuses
destinations that resolve to loopback, private or link-local ranges — including
the cloud metadata service. That is a deliberate difference from wkhtmltopdf,
which would happily read `file:///` from a page fetched over the network.
Engine releases that predate the policy cannot refuse anything, and there the
network rules of the host apply: that is `xhtml2pdf` 0.2.17, the release
Python 3.9 resolves, so do not convert untrusted documents on 3.9.

**A cover, not a booklet.** One cover document in front of one page document is
the whole of it: no `--toc` pages, no `--copies` beyond one, no encrypted
output. A generated table of contents needs the page numbers of a document that
has not been laid out yet, which this engine only answers after the fact, so it
is refused rather than approximated — build one yourself with `pypdf` if you
need one, or write the contents page and hand it to `cover` as its own document.

## How it works

`--page-size`, the margins and the orientation become one `@page` rule; the
header and footer become `@frame` boxes positioned inside the page margins,
whose `-pdf-frame-content` is the band markup. Page numbering works because
xhtml2pdf resolves `<pdf:pagenumber/>` at draw time and needs two passes for
`<pdf:pagecount/>` — the same trick wkhtmltopdf uses, one layer down.

```
pagedrop/
  cli.py         argument handling, help page, exit codes, the subcommands
  flags.py       the wkhtmltopdf flag table and the translation into a Job
  cover.py       the cover command: two documents, rendered and joined
  server.py      the same conversion behind HTTP, on a bounded number of threads
  spec.py        the Job and header/footer bands a set of flags describes
  templating.py  [page]-style variable expansion
  fragments.py   inlining --header-html / --footer-html documents
  engine.py      the @page / @frame document handed to xhtml2pdf
  grayscale.py   RGB -> luma rewrite of the produced content streams
  resources.py   reading option files and fragments from disk, writing the PDF
  units.py       paper sizes and length units
  errors.py      the two failure kinds the CLI distinguishes
```

A cover is not a special case of this: it is a second `Job`, rendered and
grayscaled on its own and then appended to the document's PDF with `pypdf`,
which is what keeps its page settings, its numbering and its bands separate
without the engine having to know about any of that. The service is the same
`Job` built from a request's options instead of from argv.

## Development

```console
$ python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
$ .venv/bin/python -m pytest
$ .venv/bin/wkhtmltopdf examples/invoice.html out/invoice.pdf \
    --header-html examples/header.html --footer-html examples/footer.html \
    --margin-top 30mm --margin-bottom 25mm --title "2026-042"
$ .venv/bin/wkhtmltopdf cover examples/cover.html examples/invoice.html out/pack.pdf
$ .venv/bin/pagedrop serve --port 8080 --verbose
```

The suite has 202 tests. It renders real PDFs and reads them back with `pypdf`: page counts,
per-page footer numbering, margins that change pagination, metadata, outline
entries and the absence of RGB operators after `--grayscale`. The server is
tested over HTTP with `urllib` and `http.client` against a live service on a
port of its own, including concurrent conversions and the status of every
refusal; the cover tests count pages, compare the cover's page box against the
document's, and check that the document's bands did not follow the cover.


## Releasing

1. Bump the version in `pyproject.toml` and `pagedrop/__init__.py`.
2. `git tag vX.Y.Z`
3. Push the tag: `git push origin vX.Y.Z`.

`publish.yml` builds the sdist and wheel, runs `twine check`, and publishes to
PyPI via OIDC trusted publishing.

One-time manual step: register the trusted publisher on pypi.org for project
"pagedrop", owner `intertermux-code/pagedrop`, workflow filename `publish.yml`.
This must be done by the maintainer and cannot be automated here.

## License

MIT, see [LICENSE](LICENSE).
