# pagedrop

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
top of ReportLab) and `pypdf` (used for `--grayscale`); both are pure Python,
so there is nothing to compile and no font or browser to fetch.

If the real wkhtmltopdf is already on the machine, `PATH` decides which one
your scripts get. Check with `command -v wkhtmltopdf`, and either remove the
system package or put the pip `bin` directory first:

```console
$ which wkhtmltopdf                      # should be your venv or ~/.local/bin
$ wkhtmltopdf --version
wkhtmltopdf 0.1.0 (pagedrop shim, engine xhtml2pdf 0.2.26)
```

The engine version is the `xhtml2pdf` release pip resolved for your interpreter:
0.2.26 on Python 3.10 and newer, 0.2.17 on 3.9, because 0.2.26 needs 3.10.

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
so a `&` or `<` in a company name cannot break the band.

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

**Single document.** No `--cover`, no `--toc` documents, no `--copies` beyond
one, no encrypted output. Concatenate or stamp afterwards with `pypdf` if you
need them.

## How it works

`--page-size`, the margins and the orientation become one `@page` rule; the
header and footer become `@frame` boxes positioned inside the page margins,
whose `-pdf-frame-content` is the band markup. Page numbering works because
xhtml2pdf resolves `<pdf:pagenumber/>` at draw time and needs two passes for
`<pdf:pagecount/>` — the same trick wkhtmltopdf uses, one layer down.

```
pagedrop/
  cli.py         argument handling, help page, exit codes
  flags.py       the wkhtmltopdf flag table and the translation into a Job
  spec.py        the Job and header/footer bands a set of flags describes
  templating.py  [page]-style variable expansion
  fragments.py   inlining --header-html / --footer-html documents
  engine.py      the @page / @frame document handed to xhtml2pdf
  grayscale.py   RGB -> luma rewrite of the produced content streams
  resources.py   reading option files and fragments from disk or URL
  units.py       paper sizes and length units
  errors.py      the two failure kinds the CLI distinguishes
```

## Development

```console
$ python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
$ .venv/bin/python -m pytest
$ .venv/bin/wkhtmltopdf examples/invoice.html out/invoice.pdf \
    --header-html examples/header.html --footer-html examples/footer.html \
    --margin-top 30mm --margin-bottom 25mm --title "2026-042"
```

The suite renders real PDFs and reads them back with `pypdf`: page counts,
per-page footer numbering, margins that change pagination, metadata, outline
entries and the absence of RGB operators after `--grayscale`.

## License

MIT, see [LICENSE](LICENSE).
